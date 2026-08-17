"""The OpenAI provider adapter — the second registered provider (T23),
proving ADR-003's §4.6 recipe ("adding a provider without touching
agents") against a real second vendor rather than a fake. Verified
against the installed `openai==3.1.0` package rather than assumed, the
same discipline T6 applied to `anthropic` (`docs/M1_BUILD_PLAN.md` T6
"load the claude-api skill rather than guessing").

This is one of two modules in SUNIL permitted to import a vendor SDK
(the other is `sunil/providers/anthropic.py`) — every other package
depends on `sunil.providers.base`'s protocol and dataclasses instead
(ADR-003, FR-040), checked by T19's AST-walking import-boundary test.

**Findings from reading the installed SDK, not the vendor's docs or this
docstring's own prior draft (the same rule that caught A-15 for
Anthropic's `effort` placement):**

1. `AsyncOpenAI` depends on `httpx2` ("the next generation HTTP client",
   same author as `httpx`), not the `httpx` used elsewhere in this
   codebase (the GitHub adapter, Anthropic's test-double injection). This
   module never imports `httpx2` directly — it only constructs
   `AsyncOpenAI(...)` and lets that package manage its own transport —
   but it is worth recording because it is a second, independent HTTP
   stack now present in the dependency tree.
2. **`base_url` must be passed explicitly, same ADR-017 reasoning as
   Anthropic (A-11).** Read from the installed SDK's `_client.py`, the
   precedence is `base_url` kwarg -> `OPENAI_BASE_URL` env -> default
   `https://api.openai.com/v1` — note the `/v1` suffix, which Anthropic's
   bare host does not have. A hard-coded canonical kwarg would still work
   today, but would silently outrank `Settings.openai_base_url` (and
   therefore QA's loopback test seam) exactly the way a hard-coded
   Anthropic `base_url` would have.
3. `chat.completions.create` has **no separate `system=` parameter** —
   the system role is just the first entry in `messages`.
4. `max_tokens` **is deprecated in favor of `max_completion_tokens`**
   (verified from the installed SDK's own docstring: "This value is now
   deprecated ... and is not compatible with o-series models"). A newly
   written adapter sends the non-deprecated kwarg.
5. **Structured output is opt-in, not unconditional (the load-bearing
   difference from Anthropic).** `response_format={"type": "json_schema",
   "json_schema": {"name": ..., "schema": ..., "strict": ...}}` — `strict`
   is `Optional[bool]`, and the installed SDK's own docstring says
   plainly: "If set to true, the model will always follow the exact
   schema... Only a subset of JSON Schema is supported when `strict` is
   `true`." Anthropic's `output_config` enforces schema conformance
   *unconditionally* by constrained decoding — there is no boolean to
   flip. This adapter always sets `strict: True` whenever `json_schema`
   is set, so a caller of `LLMRequest.json_schema` gets the strongest
   guarantee this provider is capable of, but the guarantee itself is a
   narrower subset than Anthropic's: the installed SDK's own
   `openai/lib/_pydantic.py` strict-schema helper requires
   `additionalProperties: false` on every object **and every property
   listed in `required`** (no property may be merely absent — "optional"
   under strict mode means typed nullable, not omitted). `LLMRequest`'s
   shape (`json_schema: dict | None`) does not need to change — the field
   still means "give me the strongest schema-conformance guarantee this
   provider can offer" for both providers — but a schema built only to
   satisfy Anthropic's envelope (§4.3) is not guaranteed to satisfy
   OpenAI's narrower one. Concretely: `core/orchestrator/plan_schema.py`'s
   `steps[].tool` property is absent from that object's `required` list,
   which is legal for Anthropic and would not be strict-conformant for
   OpenAI. No M1 capability points at this provider for planning, so this
   is not a live defect today — it is a real, load-bearing gap the next
   engineer who repoints a structured-output capability at `openai` must
   close in `plan_schema.py` (not this file), not rediscover at runtime.
6. `reasoning_effort: Optional[Literal["none", "minimal", "low", "medium",
   "high", "xhigh", "max"]]` is the verified equivalent of Anthropic's
   `effort`. Every value `ARCHITECTURE_V1.md` §4.4 permits for `effort`
   (`low | medium | high | xhigh | max`) is also a legal
   `reasoning_effort` value, so passing `request.effort` through verbatim
   is safe over the exact value space SUNIL ever sets — a strict superset,
   not a guess. Not independently verified via a live call whether
   `gpt-5.1` actually changes behaviour on it (M1 never sets `effort`, so
   this is untested in practice, same as the Anthropic side).
7. **Errors are classified by `status_code`, not by exception class name
   (A-16), same rule as Anthropic.** `openai.APIStatusError` is directly
   constructible (not abstract) and unnamed 5xx statuses reach it with no
   named subclass at all — see `_classify_and_raise()`.

**Model catalogue note (owed to the DM, not silently guessed):** the
pinned model id `gpt-5.1-2025-11-13` is a real, verified entry from the
installed SDK's own `openai.types.shared.chat_model.ChatModel` Literal —
not invented. Its context window, max output and per-token pricing are
**not** verifiable from any local source (the SDK ships no such static
metadata, and this environment has no network access to a pricing page);
`config/models.yaml` carries these as clearly-marked placeholders, not
silently-guessed numbers — see that file's own comment.
"""

from __future__ import annotations

import json
import time
from typing import Any, NoReturn

import openai
from openai import AsyncOpenAI
from pydantic import SecretStr

from sunil.core.registry.model_catalogue import ModelRegistry
from sunil.providers.base import (
    LLMRequest,
    LLMResponse,
    ModelCapabilities,
    ProviderPermanentError,
    ProviderTransientError,
    StructuredOutputError,
)

# A-16, applied identically to the second provider: status codes that
# mean "try again" — 408 (request timeout), 429 (rate limited), and any
# 5xx. Not a name-keyed list, precisely so an unnamed `APIStatusError`
# (or a class this document does not name) is still classified correctly
# by its status code alone.
_TRANSIENT_STATUS_CODES = frozenset({408, 429})

_STRUCTURED_OUTPUT_SCHEMA_NAME = "sunil_structured_output"


def _classify_and_raise(exc: openai.OpenAIError) -> NoReturn:
    """A-16's rule, in order, mirrored exactly from
    `sunil.providers.anthropic._classify_and_raise` — never keys off an
    exception *class name*, only `APIConnectionError`/`APITimeoutError`
    (no status at all) and `status_code` decide transient vs permanent."""
    if isinstance(exc, openai.APIConnectionError):
        # Covers APITimeoutError too (it subclasses APIConnectionError).
        # No HTTP status ever reached us — always transient.
        raise ProviderTransientError(f"transient provider error: {exc}") from exc

    if isinstance(exc, openai.APIStatusError):
        if exc.status_code in _TRANSIENT_STATUS_CODES or exc.status_code >= 500:
            raise ProviderTransientError(
                f"transient provider error ({exc.status_code}): {exc}"
            ) from exc
        raise ProviderPermanentError(
            f"permanent provider error ({exc.status_code}): {exc}"
        ) from exc

    # Anything else `openai.OpenAIError` covers that carries no status at
    # all and is not a connection error either — fail permanent by design
    # (A-16): "including any exception class this document does not name"
    # is not silently retried on an assumption.
    raise ProviderPermanentError(f"unclassified provider error: {exc}") from exc


class OpenAIProvider:
    """Implements `sunil.providers.base.LLMProvider`.

    `capabilities()` delegates to the T3 `ModelRegistry` rather than
    holding a second, potentially-divergent copy of the price table —
    `config/models.yaml` is the one place prices live (§4.4), same as the
    Anthropic provider.
    """

    name = "openai"

    def __init__(
        self,
        *,
        api_key: SecretStr,
        base_url: str,
        model_registry: ModelRegistry,
        client: Any | None = None,
    ) -> None:
        self._model_registry = model_registry
        # The secret is unwrapped exactly once, right here, to construct
        # the client — it is never assigned to an attribute of this
        # object as a plain string, so there is nowhere on `self` a stray
        # `repr()`/log call could print it from (same discipline as
        # `AnthropicProvider`).
        #
        # `client` is a test-only seam: unit tests inject a fake object
        # satisfying `await client.chat.completions.create(**kwargs)` so
        # this adapter's own logic (exception mapping, structured-output
        # parsing) is provable with no network and no key.
        self._client = client or AsyncOpenAI(
            api_key=api_key.get_secret_value(),
            # A-11/ADR-017: explicit, never left to the SDK's own
            # OPENAI_BASE_URL reading — see module docstring point 2.
            base_url=base_url,
            # SUNIL owns retry (ADR-003): each attempt is individually
            # persisted, so the SDK must never retry silently underneath us.
            max_retries=0,
        )

    def capabilities(self, model: str) -> ModelCapabilities:
        definition = self._model_registry.get_model(model)
        return ModelCapabilities(
            context_window=definition.context_window,
            max_output=definition.max_output,
            supports_structured_output=definition.supports_structured_output,
            input_usd_per_mtok=definition.input_usd_per_mtok,
            output_usd_per_mtok=definition.output_usd_per_mtok,
        )

    async def generate(
        self, model: str, request: LLMRequest, *, timeout_s: float | None = None
    ) -> LLMResponse:
        messages: list[dict[str, str]] = [{"role": "system", "content": request.system}]
        messages.extend({"role": turn.role, "content": turn.content} for turn in request.messages)

        kwargs: dict[str, Any] = {
            "model": model,
            # Verified against the installed SDK: `max_tokens` is
            # deprecated in favour of `max_completion_tokens` — see
            # module docstring point 4. Do not "fix" this back to the
            # deprecated kwarg.
            "max_completion_tokens": request.max_tokens,
            "messages": messages,
        }
        if request.temperature is not None:
            kwargs["temperature"] = request.temperature
        if request.stop_sequences:
            kwargs["stop"] = request.stop_sequences
        if request.effort is not None:
            # Verified safe over the exact value space SUNIL ever sets —
            # see module docstring point 6.
            kwargs["reasoning_effort"] = request.effort
        if request.json_schema is not None:
            # T23 finding (module docstring point 5): `strict` is
            # optional on this SDK and the schema-conformance guarantee
            # is conditional on it — always set `True` so a caller who
            # asks for `json_schema` gets the strongest guarantee this
            # provider can offer, unlike Anthropic where there is no such
            # flag because the guarantee is unconditional.
            kwargs["response_format"] = {
                "type": "json_schema",
                "json_schema": {
                    "name": _STRUCTURED_OUTPUT_SCHEMA_NAME,
                    "schema": request.json_schema,
                    "strict": True,
                },
            }
        if timeout_s is not None:
            kwargs["timeout"] = timeout_s

        started = time.monotonic()
        try:
            completion = await self._client.chat.completions.create(**kwargs)
        except openai.OpenAIError as exc:
            _classify_and_raise(exc)  # A-16: status-code-keyed, never name-keyed
        latency_ms = int((time.monotonic() - started) * 1000)

        input_tokens = completion.usage.prompt_tokens
        output_tokens = completion.usage.completion_tokens
        provider_request_id = completion.id
        choice = completion.choices[0]
        message = choice.message

        text: str | None = None
        data: dict[str, Any] | None = None

        if request.json_schema is not None:
            # Layer 2 of the plan-validation chain (§6.1): return `data`
            # ONLY on a schema-conformant parse. Never fall back to
            # regex, never strip markdown fences and retry — anything
            # else is a `StructuredOutputError`, full stop. Same rule as
            # the Anthropic adapter, applied identically.
            if message.refusal is not None:
                raise StructuredOutputError(
                    f"model refused to produce structured output: {message.refusal}",
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    provider_request_id=provider_request_id,
                )
            if message.content is None:
                raise StructuredOutputError(
                    "structured output requested but the response carried no message content",
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    provider_request_id=provider_request_id,
                )
            try:
                parsed = json.loads(message.content)
            except json.JSONDecodeError as exc:
                raise StructuredOutputError(
                    f"structured output did not parse as JSON: {exc}",
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    provider_request_id=provider_request_id,
                ) from exc
            if not isinstance(parsed, dict):
                raise StructuredOutputError(
                    f"structured output parsed to {type(parsed).__name__}, not an object",
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    provider_request_id=provider_request_id,
                )
            data = parsed
        else:
            text = message.content if message.content is not None else (message.refusal or "")

        return LLMResponse(
            text=text,
            data=data,
            provider=self.name,
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            stop_reason=choice.finish_reason,
            provider_request_id=provider_request_id,
            latency_ms=latency_ms,
            # This one call is attempt-agnostic — the Model Router
            # overwrites this with the real attempt count (A-17).
            attempts=1,
        )
