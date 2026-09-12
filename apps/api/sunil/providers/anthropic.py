"""``AnthropicProvider`` — the direct (fallback) lane for Anthropic models
(C2 §3).

Reached only when the ADR-033 kill switch is set to ``direct``. ``httpx``
against the Messages API, no SDK: the M1 adapter used the vendor SDK and had to
fight its base-URL precedence and its own retry layer (A-11/A-16) — on this lane
the wire is small enough that owning it outright is cheaper than out-ranking a
client library.

Shape notes, ported from the M1 adapter's **verified** SDK surface rather than
invented (M1 T6: "load the claude-api skill rather than guessing"):

* ``system`` is a top-level parameter, NOT a message role — sending a system
  turn in ``messages`` silently changes the prompt;
* structured output rides ``output_config.format = {"type": "json_schema",
  "schema": …}``;
* usage is ``{"input_tokens", "output_tokens"}`` (not OpenAI's ``prompt``/
  ``completion`` names);
* errors are classified **by status code, never by exception/error name**
  (M1 A-16: a name-keyed classifier called 529 permanent, which is wrong).

Caveat recorded rather than hidden: the HTTP field names above are transcribed
from the M1 adapter that was verified against the installed SDK, and this
environment has no network to re-verify them against the live API. The direct
lane is the documented FALLBACK — the default lane is the gateway, which is
verified live. Anyone flipping the kill switch for real should run one live
smoke call first.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Mapping
from typing import Any, Literal

import httpx
from pydantic import SecretStr

from sunil.core.routing.catalogue import ModelCatalogue
from sunil.core.routing.pricing import compute_cost_usd
from sunil.providers.base import (
    CompletionRequest,
    CompletionResult,
    ProviderError,
    StreamEvent,
    Usage,
)
from sunil.providers.gateway import (
    DEFAULT_TIMEOUT_S,
    classify_http_error,
    classify_transport_error,
    parse_structured_output,
)

#: ADR-017's canonical value for the direct lane.
CANONICAL_BASE_URL = "https://api.anthropic.com"

#: Pinned; the vendor requires it on every Messages request.
ANTHROPIC_VERSION = "2023-06-01"

_STOP_REASONS: dict[str, Literal["stop", "max_tokens", "refusal", "error"]] = {
    "end_turn": "stop",
    "stop_sequence": "stop",
    "tool_use": "error",  # we never send tools — see below
    "max_tokens": "max_tokens",
    "refusal": "refusal",
}


class AnthropicProvider:
    name = "anthropic"

    def __init__(
        self,
        *,
        api_key: SecretStr,
        base_url: str = CANONICAL_BASE_URL,
        catalogue: ModelCatalogue,
        client: httpx.AsyncClient | None = None,
        timeout_s: float = DEFAULT_TIMEOUT_S,
    ) -> None:
        self._api_key = api_key
        self._catalogue = catalogue
        self._base_url = base_url.rstrip("/")
        self._timeout_s = timeout_s
        # ADR-017 test seam; never a retrying client (SUNIL owns retry, C2 §4).
        self._client = client or httpx.AsyncClient(timeout=timeout_s)

    async def aclose(self) -> None:
        await self._client.aclose()

    # -- C2 §2 protocol ----------------------------------------------------- #
    async def complete(self, request: CompletionRequest) -> CompletionResult:
        wire_model = self._wire_model(request.model)
        body = self._build_body(request, wire_model=wire_model)
        try:
            response = await self._client.post(
                f"{self._base_url}/v1/messages",
                json=body,
                headers=self._headers(),
                timeout=self._timeout_s,
            )
        except httpx.HTTPError as exc:
            raise classify_transport_error(exc, provider_model=wire_model) from exc
        if response.status_code >= 400:
            raise classify_http_error(response, provider_model=wire_model)
        return self._result_from(response.json(), request=request, wire_model=wire_model)

    def stream(self, request: CompletionRequest) -> AsyncIterator[StreamEvent]:
        """Not implemented on the fallback lane.

        ADR-028: only the analysis call streams, and the default lane is the
        gateway. Implementing a second SSE dialect (the Messages API's
        ``content_block_delta`` events) for a lane that exists as a kill switch
        would be untested code on a path nobody exercises — worse than a loud
        refusal. It raises rather than returning an empty iterator so a caller
        can never mistake it for "the model said nothing".
        """
        raise NotImplementedError(
            "the direct Anthropic lane does not stream — ADR-028's streaming leg "
            "runs on the gateway lane (flip SUNIL_LLM_PROVIDER_LANE back to "
            "`gateway`, or implement the Messages SSE dialect here deliberately)"
        )

    # -- internals ---------------------------------------------------------- #
    def _wire_model(self, alias: str) -> str:
        entry = self._catalogue.get_model(alias)
        if entry.provider != self.name:
            raise ProviderError(
                kind="bad_request",
                retryable=False,
                provider_model=None,
                message=(
                    f"model {alias!r} is assigned to provider {entry.provider!r} in "
                    f"config/models.yaml, not to {self.name!r} — refusing before the "
                    "wire (a routing bug, not a vendor error)"
                ),
            )
        return entry.provider_model_id

    def _headers(self) -> dict[str, str]:
        return {
            "x-api-key": self._api_key.get_secret_value(),
            "anthropic-version": ANTHROPIC_VERSION,
            "Content-Type": "application/json",
        }

    def _build_body(self, request: CompletionRequest, *, wire_model: str) -> dict[str, Any]:
        system = "\n\n".join(
            message.content for message in request.messages if message.role == "system"
        )
        body: dict[str, Any] = {
            "model": wire_model,
            "max_tokens": request.max_tokens,
            "temperature": request.temperature,
            "messages": [
                # ``tool`` is not a role this API accepts; C2 allows it on the
                # seam, so it is carried as a user turn with its content intact
                # rather than dropped (dropping a turn rewrites the prompt).
                {
                    "role": "user" if message.role == "tool" else message.role,
                    "content": message.content,
                }
                for message in request.messages
                if message.role != "system"
            ],
        }
        if system:
            body["system"] = system
        if request.json_schema is not None:
            body["output_config"] = {
                "format": {"type": "json_schema", "schema": request.json_schema}
            }
        return body

    def _result_from(
        self, payload: Mapping[str, Any], *, request: CompletionRequest, wire_model: str
    ) -> CompletionResult:
        provider_model = str(payload.get("model") or wire_model)
        usage_payload = payload.get("usage") or {}
        entry = self._catalogue.get_model(request.model)
        input_tokens = int(usage_payload.get("input_tokens", 0) or 0)
        output_tokens = int(usage_payload.get("output_tokens", 0) or 0)
        usage = Usage(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_usd=compute_cost_usd(
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                input_usd_per_mtok=entry.input_usd_per_mtok,
                output_usd_per_mtok=entry.output_usd_per_mtok,
            ),
        )

        blocks = payload.get("content") or []
        if any(block.get("type") == "tool_use" for block in blocks):
            raise ProviderError(
                kind="bad_request",
                retryable=False,
                provider_model=provider_model,
                usage=usage,
                message=(
                    "response carried a tool_use block on a seam that never sends "
                    "tools — refusing (C2 §2)"
                ),
            )
        text = "".join(block.get("text", "") for block in blocks if block.get("type") == "text")
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
            finish_reason=_STOP_REASONS.get(str(payload.get("stop_reason")), "stop"),
        )
