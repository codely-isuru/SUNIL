"""``GatewayProvider`` — the DEFAULT transport lane (C2 §3).

One adapter speaking the **OpenAI-compatible** API to the self-hosted LiteLLM
proxy, with ``httpx`` and no SDK (M1 convention: the wire is the contract, and a
vendor SDK's own retry/base-URL behaviour is one more thing that can silently
outrank ours).

What this module does and does not own:

* **Owns the wire shape.** ``POST {base}/v1/chat/completions``, the virtual-key
  ``Authorization`` header, ``response_format={"type":"json_schema", …}`` when a
  schema is set, ``metadata`` for log correlation, and the SSE parse for
  ``stream()``.
* **Owns detection, never the re-ask.** It classifies failures into C2 §4's one
  exception family and raises. The single retry layer is
  ``core/routing/retry.py`` (C2 §4); the gateway itself runs ``num_retries: 0``
  (C2 §3) and this client sets no retry of its own.
* **Owns nothing about routing.** Capability and privacy policy are the router's
  (C2 §2), which is why this module never sees a capability name.
* **Sends no ``tools``, ever.** The request body is built field by field from
  C2's closed ``CompletionRequest``; there is no pass-through of caller-supplied
  keys, so the frozen no-tools shape cannot erode through this adapter. A
  response that nevertheless carries ``tool_calls`` is refused loudly.

**Model ids on this lane are the gateway aliases, unchanged** (C2 §2). The
direct lane's ``provider_model_id`` is deliberately NOT read here: that is what
makes the alias namespace lane-invariant.

**Cost is ours.** ``Usage.cost_usd`` is computed from ``config/models.yaml``
prices; a gateway-reported cost is never authoritative (C2 §2).

Secrets: keys are ``SecretStr`` and are unwrapped exactly once, at the point of
building the header — never stored on ``self`` as plaintext, so no ``repr()`` of
this object or of a traceback frame can print one (ADR-006).
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Mapping
from dataclasses import dataclass, field
from typing import Any, Literal

import httpx
from pydantic import SecretStr

from sunil.core.routing.catalogue import ModelCatalogue
from sunil.core.routing.pricing import compute_cost_usd
from sunil.providers.base import (
    ChatMessage,
    CompletionRequest,
    CompletionResult,
    GatewayModelParityError,
    ProviderError,
    StreamEvent,
    Usage,
)

#: Seconds. Matches the gateway's own ``request_timeout: 600`` so a long
#: streamed analysis call is not cut short by the client instead (ADR-028).
DEFAULT_TIMEOUT_S = 600.0

#: OpenAI's ``finish_reason`` vocabulary → C2 §2's.
_FINISH_REASONS: dict[str, Literal["stop", "max_tokens", "refusal", "error"]] = {
    "stop": "stop",
    "length": "max_tokens",
    "content_filter": "refusal",
    "refusal": "refusal",
}

#: Substrings that identify a LiteLLM virtual-key budget stop (observed in the
#: proxy's ``BudgetExceededError`` message). Checked only on the statuses the
#: proxy uses for it, so an unrelated 400 mentioning the word "budget" in a
#: prompt echo cannot be misclassified into a terminal kind.
_BUDGET_MARKERS = ("budget has been exceeded", "exceededbudget", "budget exceeded")
_BUDGET_STATUSES = (400, 402, 429)


@dataclass
class VirtualKeyring:
    """LiteLLM virtual keys (C2 §3): the per-agent key if one exists, else the
    default. Budgets and rate limits live ON the keys, inside LiteLLM — SUNIL
    holds no budget state of its own."""

    default: SecretStr
    per_agent: Mapping[str, SecretStr] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """An empty key is refused HERE, at construction.

        Found live against the pinned proxy on 2026-09-11: an empty key does not
        yield a clean 401. ``Authorization: Bearer `` is an illegal HTTP header
        value, so h11 raises ``LocalProtocolError`` before the request leaves
        the process and the adapter can only classify it as a transport failure
        — ``overloaded``, which is RETRYABLE. A typo'd or unset key would then
        be retried three times per turn and surfaced to the owner as an upstream
        outage. Fail closed on the configuration fault instead.
        """
        for label, key in (("default", self.default), *self.per_agent.items()):
            if not key.get_secret_value().strip():
                raise ValueError(
                    f"virtual key {label!r} is empty — the gateway lane needs a real "
                    "LiteLLM virtual key (C2 §3). An empty key cannot even be sent: "
                    "'Authorization: Bearer ' is an illegal header value."
                )

    def key_for(self, agent_id: str) -> SecretStr:
        return self.per_agent.get(agent_id, self.default)


def _usage_from(payload: Mapping[str, Any]) -> tuple[int, int]:
    usage = payload.get("usage") or {}
    return int(usage.get("prompt_tokens", 0) or 0), int(usage.get("completion_tokens", 0) or 0)


def _error_message(response: httpx.Response) -> str:
    try:
        body = response.json()
    except ValueError:
        return response.text[:400]
    error = body.get("error") if isinstance(body, Mapping) else None
    if isinstance(error, Mapping):
        return str(error.get("message", ""))[:400]
    return str(body)[:400]


def classify_http_error(
    response: httpx.Response, *, provider_model: str | None, usage: Usage | None = None
) -> ProviderError:
    """HTTP status → C2 §4 ``kind``, keyed on the STATUS, never on a message
    pattern (M1 A-16's rule: a name/phrase-keyed classifier mislabels the case
    the author did not foresee — 529 as permanent being the historical one).

    The single message exception is the virtual-key budget stop, which LiteLLM
    reports as an ordinary 400/429 and which C2 §4 gives its own,
    **non-retryable** kind: retrying an exhausted budget just spends the turn
    deadline.

    **``auth`` messages are redacted.** The pinned proxy echoes the presented
    key and its hash in the 401 body (observed live 2026-09-11), so copying that
    body into an exception would leak a credential fragment into every log line
    and traceback that renders it.
    """
    status = response.status_code
    message = _error_message(response)
    lowered = message.lower()

    if status in (401, 403):
        return ProviderError(
            kind="auth",
            retryable=False,
            provider_model=provider_model,
            usage=usage,
            message=(
                f"gateway rejected the credential (HTTP {status}); message withheld "
                "because the proxy echoes the presented key"
            ),
        )
    if status in _BUDGET_STATUSES and any(marker in lowered for marker in _BUDGET_MARKERS):
        return ProviderError(
            kind="budget_exceeded",
            retryable=False,
            provider_model=provider_model,
            usage=usage,
            message=f"virtual-key budget exhausted (HTTP {status}): {message}",
        )
    if status == 429:
        return ProviderError(
            kind="rate_limit",
            retryable=True,
            provider_model=provider_model,
            usage=usage,
            message=f"rate limited (HTTP 429): {message}",
        )
    if status >= 500:
        return ProviderError(
            kind="overloaded",
            retryable=True,
            provider_model=provider_model,
            usage=usage,
            message=f"upstream overloaded (HTTP {status}): {message}",
        )
    return ProviderError(
        kind="bad_request",
        retryable=False,
        provider_model=provider_model,
        usage=usage,
        message=f"request refused (HTTP {status}): {message}",
    )


def classify_transport_error(
    exc: httpx.HTTPError, *, provider_model: str | None
) -> ProviderError:
    """No HTTP status ever reached us. A timeout is ``timeout`` (C2 §4: retried
    once); any other transport failure is ``overloaded`` — transient, because a
    refused connection to a proxy that is restarting is exactly the case a
    single retry fixes."""
    if isinstance(exc, httpx.TimeoutException):
        return ProviderError(
            kind="timeout",
            retryable=True,
            provider_model=provider_model,
            message=f"gateway timeout: {type(exc).__name__}",
        )
    return ProviderError(
        kind="overloaded",
        retryable=True,
        provider_model=provider_model,
        message=f"gateway transport failure: {type(exc).__name__}: {exc}",
    )


def parse_structured_output(
    text: str, *, provider_model: str | None, usage: Usage
) -> dict:
    """Layer 2 of the plan-validation chain (M1 §6.1, ported verbatim in
    spirit): return an object ONLY on a clean parse.

    No fence stripping, no regex rescue, no "nudge and retry" — anything else is
    ``invalid_output``, carrying the usage the failed attempt burned (C2 §4 /
    M1 A-2) so the re-ask's cost is never invisible. The adapter raises; the
    SUNIL policy re-asks at most once.
    """

    def fail(reason: str) -> ProviderError:
        return ProviderError(
            kind="invalid_output",
            retryable=True,
            provider_model=provider_model,
            usage=usage,
            message=f"structured output {reason}",
        )

    if not text.strip():
        raise fail("was empty")
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as exc:
        raise fail(f"did not parse as JSON: {exc}") from exc
    if not isinstance(parsed, dict):
        raise fail(f"parsed to {type(parsed).__name__}, not an object")
    return parsed


class OpenAICompatibleChat:
    """The shared ``/v1/chat/completions`` client.

    Both the gateway lane and the direct OpenAI adapter speak this wire, so it
    lives in one place: a divergence between them would be a divergence in what
    the kill switch actually does.
    """

    def __init__(
        self,
        *,
        base_url: str,
        catalogue: ModelCatalogue,
        client: httpx.AsyncClient | None = None,
        timeout_s: float = DEFAULT_TIMEOUT_S,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._catalogue = catalogue
        self._timeout_s = timeout_s
        # ADR-017 test seam: an injected client (``MockTransport``) proves this
        # adapter's logic with no network and no key. Never a retrying client —
        # SUNIL owns retry (C2 §4) and each attempt must be individually
        # visible to the accounting rule.
        self._client = client or httpx.AsyncClient(timeout=timeout_s)

    @property
    def base_url(self) -> str:
        return self._base_url

    async def aclose(self) -> None:
        await self._client.aclose()

    # -- body building ------------------------------------------------------ #
    def build_body(
        self,
        request: CompletionRequest,
        *,
        wire_model: str,
        metadata: bool,
        stream: bool = False,
    ) -> dict[str, Any]:
        """Built field by field from C2's closed request model — there is no
        pass-through of unknown keys, so ``tools`` cannot appear here even if a
        caller smuggled one past pydantic (it cannot: ``extra="forbid"``)."""
        body: dict[str, Any] = {
            "model": wire_model,
            "messages": [self._message(message) for message in request.messages],
            "max_tokens": request.max_tokens,
            "temperature": request.temperature,
        }
        if request.json_schema is not None:
            # ``strict`` is deliberately NOT set: strict mode constrains the
            # schema subset (every property required, ``additionalProperties:
            # false``) and would reject valid plan schemas at the vendor with a
            # 400. SUNIL's own validator is the load-bearing one (C2 §3), and
            # the gateway is configured ``drop_params: false`` so this parameter
            # is either honoured or refused loudly — never silently dropped.
            body["response_format"] = {
                "type": "json_schema",
                "json_schema": {
                    "name": "sunil_structured_output",
                    "schema": request.json_schema,
                },
            }
        if metadata:
            # C2 §3 — correlation ids travel as metadata so gateway logs and
            # ``llm_calls`` rows line up. NEVER in the prompt.
            body["metadata"] = {
                "request_id": request.request_id,
                "agent_id": request.agent_id,
            }
        if stream:
            body["stream"] = True
            # Without this the proxy omits usage from streamed responses and the
            # A-2 accounting rule would silently record zero tokens per stream.
            body["stream_options"] = {"include_usage": True}
        return body

    @staticmethod
    def _message(message: ChatMessage) -> dict[str, str]:
        return {"role": message.role, "content": message.content}

    # -- calls -------------------------------------------------------------- #
    async def post(
        self, body: Mapping[str, Any], *, headers: Mapping[str, str], provider_model: str
    ) -> Mapping[str, Any]:
        try:
            response = await self._client.post(
                f"{self._base_url}/v1/chat/completions",
                json=dict(body),
                headers=dict(headers),
                timeout=self._timeout_s,
            )
        except httpx.HTTPError as exc:
            raise classify_transport_error(exc, provider_model=provider_model) from exc
        if response.status_code >= 400:
            raise classify_http_error(response, provider_model=provider_model)
        return response.json()

    def result_from(
        self, payload: Mapping[str, Any], *, request: CompletionRequest, catalogue_model: str
    ) -> CompletionResult:
        """Translate an OpenAI-compatible response into C2's result model."""
        provider_model = str(payload.get("model") or catalogue_model)
        input_tokens, output_tokens = _usage_from(payload)
        usage = self.usage_for(
            catalogue_model, input_tokens=input_tokens, output_tokens=output_tokens
        )
        choices = payload.get("choices") or []
        choice = choices[0] if choices else {}
        message = choice.get("message") or {}

        if message.get("tool_calls"):
            # We never send ``tools`` (C2 §2). A response carrying one means a
            # channel exists that this seam does not model — fail closed rather
            # than drop it silently, which is how a second path to a privileged
            # action starts.
            raise ProviderError(
                kind="bad_request",
                retryable=False,
                provider_model=provider_model,
                usage=usage,
                message=(
                    "response carried tool_calls on a seam that never sends tools — "
                    "refusing (C2 §2; the only path to a tool call is a validated "
                    "plan step through the C1 chokepoint)"
                ),
            )

        text = message.get("content") or ""
        parsed = (
            parse_structured_output(text, provider_model=provider_model, usage=usage)
            if request.json_schema is not None
            else None
        )
        return CompletionResult(
            text=text,
            parsed=parsed,
            usage=usage,
            provider_model=provider_model,
            finish_reason=_FINISH_REASONS.get(str(choice.get("finish_reason")), "error"),
        )

    def usage_for(self, catalogue_model: str, *, input_tokens: int, output_tokens: int) -> Usage:
        """C2 §2 — cost from ``config/models.yaml``, computed SUNIL-side."""
        entry = self._catalogue.get_model(catalogue_model)
        return Usage(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_usd=compute_cost_usd(
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                input_usd_per_mtok=entry.input_usd_per_mtok,
                output_usd_per_mtok=entry.output_usd_per_mtok,
            ),
        )

    async def stream_events(
        self,
        body: Mapping[str, Any],
        *,
        headers: Mapping[str, str],
        request: CompletionRequest,
        catalogue_model: str,
    ) -> AsyncIterator[StreamEvent]:
        """SSE → C2 ``StreamEvent``s.

        The token events are a PROJECTION; the single ``done`` event is
        authoritative (C2 §2), and concatenating the tokens reproduces
        ``done.result.text`` byte for byte because each token is emitted exactly
        as the wire delivered it — no re-splitting, no normalisation
        (ADR-027's partition property).
        """
        chunks: list[str] = []
        provider_model = catalogue_model
        finish = "stop"
        input_tokens = output_tokens = 0
        try:
            async with self._client.stream(
                "POST",
                f"{self._base_url}/v1/chat/completions",
                json=dict(body),
                headers=dict(headers),
                timeout=self._timeout_s,
            ) as response:
                if response.status_code >= 400:
                    await response.aread()
                    raise classify_http_error(response, provider_model=provider_model)
                async for line in response.aiter_lines():
                    line = line.strip()
                    if not line.startswith("data:"):
                        continue
                    data = line[len("data:") :].strip()
                    if data == "[DONE]":
                        break
                    try:
                        event = json.loads(data)
                    except json.JSONDecodeError:
                        continue
                    provider_model = str(event.get("model") or provider_model)
                    if event.get("usage"):
                        input_tokens, output_tokens = _usage_from(event)
                    for choice in event.get("choices") or []:
                        token = (choice.get("delta") or {}).get("content")
                        if token:
                            chunks.append(token)
                            yield StreamEvent(type="token", token=token)
                        if choice.get("finish_reason"):
                            finish = str(choice["finish_reason"])
        except httpx.HTTPError as exc:
            raise classify_transport_error(exc, provider_model=provider_model) from exc

        text = "".join(chunks)
        usage = self.usage_for(
            catalogue_model, input_tokens=input_tokens, output_tokens=output_tokens
        )
        parsed = (
            parse_structured_output(text, provider_model=provider_model, usage=usage)
            if request.json_schema is not None
            else None
        )
        yield StreamEvent(
            type="done",
            result=CompletionResult(
                text=text,
                parsed=parsed,
                usage=usage,
                provider_model=provider_model,
                finish_reason=_FINISH_REASONS.get(finish, "error"),
            ),
        )


class GatewayProvider:
    """C2 §3's default-lane ``LLMProvider``."""

    name = "gateway"

    def __init__(
        self,
        *,
        base_url: str,
        keys: VirtualKeyring,
        catalogue: ModelCatalogue,
        client: httpx.AsyncClient | None = None,
        timeout_s: float = DEFAULT_TIMEOUT_S,
    ) -> None:
        self._keys = keys
        self._chat = OpenAICompatibleChat(
            base_url=base_url, catalogue=catalogue, client=client, timeout_s=timeout_s
        )
        self._catalogue = catalogue

    @property
    def base_url(self) -> str:
        return self._chat.base_url

    async def aclose(self) -> None:
        await self._chat.aclose()

    # -- C2 §3 startup parity check ---------------------------------------- #
    async def start(self) -> None:
        """Fetch ``GET {base}/v1/models`` and refuse to boot if any
        ``config/models.yaml`` id is absent from the gateway's alias set
        (``GatewayModelParityError``, listing the offenders).

        A drifted namespace is a boot failure, never a runtime 400 (C2 §3).
        Extra deployments on the proxy are tolerated: SUNIL only ever names its
        own ids, so an operator's experiment cannot break a SUNIL request.

        Verified against the pinned proxy (LiteLLM v1.83.14-stable.patch.3) on
        2026-09-11: the response is ``{"object": "list", "data": [{"id":
        "claude-sonnet", …}, …]}``.
        """
        url = f"{self._chat.base_url}/v1/models"
        headers = {"Authorization": f"Bearer {self._keys.default.get_secret_value()}"}
        try:
            response = await self._chat._client.get(url, headers=headers)  # noqa: SLF001
        except httpx.HTTPError as exc:
            raise classify_transport_error(exc, provider_model=None) from exc
        if response.status_code >= 400:
            raise classify_http_error(response, provider_model=None)

        served = {
            str(entry.get("id"))
            for entry in (response.json().get("data") or [])
            if entry.get("id")
        }
        missing = sorted(set(self._catalogue.model_ids()) - served)
        if missing:
            raise GatewayModelParityError(
                "gateway model parity check failed at "
                f"{url}: config/models.yaml declares ids the gateway does not serve "
                f"(missing: {missing}). A drifted alias namespace is a boot failure — "
                "align config/models.yaml with infra/litellm/config.yaml's "
                "`model_name` set (C2 §2/§3)."
            )

    # -- C2 §2 protocol ----------------------------------------------------- #
    async def complete(self, request: CompletionRequest) -> CompletionResult:
        body = self._chat.build_body(request, wire_model=request.model, metadata=True)
        payload = await self._chat.post(
            body, headers=self._headers(request), provider_model=request.model
        )
        return self._chat.result_from(payload, request=request, catalogue_model=request.model)

    def stream(self, request: CompletionRequest) -> AsyncIterator[StreamEvent]:
        body = self._chat.build_body(
            request, wire_model=request.model, metadata=True, stream=True
        )
        return self._chat.stream_events(
            body,
            headers=self._headers(request),
            request=request,
            catalogue_model=request.model,
        )

    # -- internals ---------------------------------------------------------- #
    def _headers(self, request: CompletionRequest) -> dict[str, str]:
        # The secret is unwrapped here and nowhere else, into a local that dies
        # with the call (ADR-006).
        key = self._keys.key_for(request.agent_id)
        return {
            "Authorization": f"Bearer {key.get_secret_value()}",
            "Content-Type": "application/json",
        }
