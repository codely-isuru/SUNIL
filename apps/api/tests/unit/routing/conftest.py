"""Shared fixtures for `sunil.core.routing` unit tests — a fake
`LLMProvider` (no network, no key) and a deadline-controllable fake
`TraceContext`, per `docs/M1_BUILD_PLAN.md` T6: "Unit tests run against a
fake provider — no network, no key."
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from sunil.core.registry.model_catalogue import CapabilityDefinition, ModelDefinition, ModelRegistry
from sunil.providers.base import LLMRequest, LLMResponse, ModelCapabilities
from sunil.providers.registry import ProviderRegistry


@dataclass
class FakeProviderCall:
    model: str
    request: LLMRequest
    timeout_s: float | None


class FakeProvider:
    """A hand-rolled `LLMProvider` — no network, no vendor SDK, no key.
    `responses` is consumed in order, one entry per `generate()` call;
    an `Exception` instance in the list is raised instead of returned, so
    a test can script "fail, fail, succeed"."""

    def __init__(
        self,
        name: str,
        *,
        capabilities_by_model: dict[str, ModelCapabilities],
        responses: list[LLMResponse | Exception],
    ) -> None:
        self.name = name
        self._capabilities_by_model = capabilities_by_model
        self._responses = list(responses)
        self.calls: list[FakeProviderCall] = []

    def capabilities(self, model: str) -> ModelCapabilities:
        return self._capabilities_by_model[model]

    async def generate(
        self, model: str, request: LLMRequest, *, timeout_s: float | None = None
    ) -> LLMResponse:
        self.calls.append(FakeProviderCall(model=model, request=request, timeout_s=timeout_s))
        outcome = self._responses.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


@dataclass
class FakeTraceContext:
    """Satisfies the parts of `TraceContext` the router actually uses.
    `remaining_values` is popped once per `remaining_deadline_s()` call so
    a test can simulate a shrinking (or, simplest, constant) deadline
    across retries; the last value is reused once the list is exhausted.
    """

    request_id: str = "test-request"
    user_id: str | None = None
    conversation_id: str | None = None
    remaining_values: list[float] = field(default_factory=lambda: [1000.0])
    emitted: list[Any] = field(default_factory=list)

    async def emit(
        self,
        stage: Any,
        *,
        summary: str,
        detail: dict[str, Any] | None = None,
        task_id: str | None = None,
    ) -> None:
        self.emitted.append((stage, summary, detail, task_id))

    def remaining_deadline_s(self) -> float:
        if len(self.remaining_values) > 1:
            return self.remaining_values.pop(0)
        return self.remaining_values[0]


def make_model_capabilities(
    *,
    input_usd_per_mtok: str = "2",
    output_usd_per_mtok: str = "10",
    context_window: int = 1_000_000,
    max_output: int = 128_000,
    supports_structured_output: bool = True,
) -> ModelCapabilities:
    return ModelCapabilities(
        context_window=context_window,
        max_output=max_output,
        supports_structured_output=supports_structured_output,
        input_usd_per_mtok=Decimal(input_usd_per_mtok),
        output_usd_per_mtok=Decimal(output_usd_per_mtok),
    )


def make_model_registry(
    *,
    capability: str = "general_reasoning",
    provider: str = "fake",
    model: str = "fake-model-1",
    max_tokens: int = 1024,
    timeout_s: float = 20.0,
) -> ModelRegistry:
    """A minimal, hand-built `ModelRegistry` — no YAML, no filesystem — so
    `core/routing` unit tests never depend on T3's loader or on
    `config/models.yaml`'s actual contents."""
    return ModelRegistry(
        pricing_version="test-pricing",
        models={
            model: ModelDefinition(
                model_id=model,
                provider=provider,
                context_window=1_000_000,
                max_output=128_000,
                input_usd_per_mtok=Decimal("2"),
                output_usd_per_mtok=Decimal("10"),
                supports_structured_output=True,
            )
        },
        capabilities={
            capability: CapabilityDefinition(
                capability=capability,
                provider=provider,
                model=model,
                max_tokens=max_tokens,
                timeout_s=timeout_s,
            )
        },
    )


def make_provider_registry(*providers: FakeProvider) -> ProviderRegistry:
    registry = ProviderRegistry()
    for provider in providers:
        registry.register(provider)
    return registry
