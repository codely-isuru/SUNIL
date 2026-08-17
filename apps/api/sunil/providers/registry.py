"""The provider registry (ADR-003 §4.6): where a provider is registered
once, by name, so the Model Router can look it up by the string
`config/models.yaml` names in a capability's `provider` field — never by
importing the vendor module itself.

**T23 (2026-08-17) did exactly this for `openai`** — the recipe held
unchanged: `sunil/providers/openai.py` implementing `LLMProvider`, one
more `registry.register(...)` line below, models/pricing added to
`config/models.yaml`, a capability pointed at it. Zero changes to
`core/orchestrator`, `core/agent_framework`, `agents/*` or `tools/*` were
needed — `test_a_second_provider_needs_no_change_to_this_router`
(`tests/unit/routing/test_router.py`) already proved this with a fake
provider; this is the same proof against a real, second vendor.
"""

from __future__ import annotations

from sunil.core.registry.model_catalogue import ModelRegistry
from sunil.providers.anthropic import AnthropicProvider
from sunil.providers.base import LLMProvider, UnknownProviderError
from sunil.providers.openai import OpenAIProvider
from sunil.settings import Settings


class ProviderRegistry:
    def __init__(self) -> None:
        self._providers: dict[str, LLMProvider] = {}

    def register(self, provider: LLMProvider) -> None:
        self._providers[provider.name] = provider

    def get(self, name: str) -> LLMProvider:
        try:
            return self._providers[name]
        except KeyError:
            raise UnknownProviderError(name) from None

    def provider_names(self) -> list[str]:
        return list(self._providers.keys())


def build_provider_registry(
    *, settings: Settings, model_registry: ModelRegistry
) -> ProviderRegistry:
    """The one place providers are wired up for real. Construction happens
    once (`sunil/main.py`'s lifespan, §3.2) and the registry is threaded to
    the Model Router from there — nothing downstream constructs a provider
    itself.
    """
    registry = ProviderRegistry()
    registry.register(
        AnthropicProvider(
            api_key=settings.anthropic_api_key,
            # A-11/ADR-017: explicit, from Settings — never the SDK's own
            # env reading, and never a hard-coded canonical literal (which
            # would outrank QA's ANTHROPIC_BASE_URL test seam).
            base_url=settings.anthropic_base_url,
            model_registry=model_registry,
        )
    )
    # A second provider is one more line here (§4.6) — nothing else changes.
    registry.register(
        OpenAIProvider(
            api_key=settings.openai_api_key,
            # A-11/ADR-017: explicit, from Settings — never the SDK's own
            # env reading, and never a hard-coded canonical literal
            # (which would outrank QA's OPENAI_BASE_URL test seam).
            base_url=settings.openai_base_url,
            model_registry=model_registry,
        )
    )
    return registry
