"""The Anthropic provider adapter — the verified surface of
`ARCHITECTURE_V1.md` §4.3, checked against the installed `anthropic`
0.122.0 package rather than guessed (`docs/M1_BUILD_PLAN.md` T6 "load the
claude-api skill rather than guessing").

This is the only module in SUNIL permitted to `import anthropic` — every
other package depends on `sunil.providers.base`'s protocol and dataclasses
instead (ADR-003, FR-040).
"""

from __future__ import annotations

import json
import time
from typing import Any

import anthropic
from anthropic import AsyncAnthropic
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

# §4.3, verified against the live SDK: connection failures, timeouts, rate
# limits and 5xx are retryable; everything else that names a concrete
# problem with *this* request is not.
_TRANSIENT_EXCEPTIONS: tuple[type[Exception], ...] = (
    anthropic.APIConnectionError,  # covers APITimeoutError too (subclass)
    anthropic.RateLimitError,
    anthropic.InternalServerError,
)
_PERMANENT_EXCEPTIONS: tuple[type[Exception], ...] = (
    anthropic.BadRequestError,
    anthropic.AuthenticationError,
    anthropic.PermissionDeniedError,
    anthropic.NotFoundError,
    anthropic.UnprocessableEntityError,
)


class AnthropicProvider:
    """Implements `sunil.providers.base.LLMProvider`.

    `capabilities()` delegates to the T3 `ModelRegistry` rather than
    holding a second, potentially-divergent copy of the price table —
    `config/models.yaml` is the one place prices live (§4.4).
    """

    name = "anthropic"

    def __init__(
        self,
        *,
        api_key: SecretStr,
        model_registry: ModelRegistry,
        client: Any | None = None,
    ) -> None:
        self._model_registry = model_registry
        # The secret is unwrapped exactly once, right here, to construct
        # the client — it is never assigned to an attribute of this object
        # as a plain string, so there is nowhere on `self` a stray
        # `repr()`/log call could print it from (`docs/M1_BUILD_PLAN.md`
        # T6 "unwrap at the single point of use").
        #
        # `client` is a test-only seam: unit tests inject a fake object
        # satisfying `await client.messages.create(**kwargs)` so this
        # adapter's own logic (exception mapping, structured-output
        # parsing) is provable with no network and no key.
        self._client = client or AsyncAnthropic(
            api_key=api_key.get_secret_value(),
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
        kwargs: dict[str, Any] = {
            "model": model,
            "max_tokens": request.max_tokens,
            "system": request.system,
            "messages": [{"role": turn.role, "content": turn.content} for turn in request.messages],
        }
        if request.temperature is not None:
            kwargs["temperature"] = request.temperature
        if request.stop_sequences:
            kwargs["stop_sequences"] = request.stop_sequences

        output_config: dict[str, Any] = {}
        if request.json_schema is not None:
            output_config["format"] = {"type": "json_schema", "schema": request.json_schema}
        if request.effort is not None:
            # `effort` lives inside `output_config` on the verified SDK
            # surface, not as a top-level `messages.create()` parameter —
            # confirmed against the installed 0.122.0 client rather than
            # assumed from the architecture doc's prose.
            output_config["effort"] = request.effort
        if output_config:
            kwargs["output_config"] = output_config

        if timeout_s is not None:
            kwargs["timeout"] = timeout_s

        started = time.monotonic()
        try:
            message = await self._client.messages.create(**kwargs)
        except _TRANSIENT_EXCEPTIONS as exc:
            raise ProviderTransientError(f"transient provider error: {exc}") from exc
        except _PERMANENT_EXCEPTIONS as exc:
            raise ProviderPermanentError(f"permanent provider error: {exc}") from exc
        except anthropic.AnthropicError as exc:
            # Anything the SDK raises that is not on the two verified
            # lists above (e.g. a future exception type, or a vendor-side
            # error this architecture's verified surface does not name)
            # is treated as permanent, not silently retried on an
            # assumption `ARCHITECTURE_V1.md` §4.3 never made.
            raise ProviderPermanentError(f"unclassified provider error: {exc}") from exc
        latency_ms = int((time.monotonic() - started) * 1000)

        input_tokens = message.usage.input_tokens
        output_tokens = message.usage.output_tokens
        provider_request_id = getattr(message, "_request_id", None)

        text: str | None = None
        data: dict[str, Any] | None = None

        text_blocks = [
            block.text for block in message.content if getattr(block, "type", None) == "text"
        ]

        if request.json_schema is not None:
            # Layer 2 of the plan-validation chain (§6.1): return `data`
            # ONLY on a schema-conformant parse. Never fall back to regex,
            # never strip markdown fences and retry — anything else is a
            # `StructuredOutputError`, full stop.
            if not text_blocks:
                raise StructuredOutputError(
                    "structured output requested but the response carried no text block",
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    provider_request_id=provider_request_id,
                )
            try:
                parsed = json.loads(text_blocks[0])
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
            text = "".join(text_blocks)

        return LLMResponse(
            text=text,
            data=data,
            provider=self.name,
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            stop_reason=message.stop_reason,
            provider_request_id=provider_request_id,
            latency_ms=latency_ms,
        )
