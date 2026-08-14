"""The provider registry (ADR-003 §4.6): where a provider is registered
once, by name, so the Model Router can look it up by the string
`config/models.yaml` names in a capability's `provider` field — never by
importing the vendor module itself.

Adding a second provider (§4.6, and the test of whether this task was
built right): write `sunil/providers/openai.py` implementing
`LLMProvider`, register it with one more `registry.register(...)` line in
`build_provider_registry()` below, add its models/pricing to
`config/models.yaml`, point a capability at it. Zero changes to
`core/orchestrator`, `core/agent_framework`, `agents/*` or `tools/*`.
"""

from __future__ import annotations

from sunil.core.registry.model_catalogue import ModelRegistry
from sunil.providers.anthropic import AnthropicProvider
from sunil.providers.base import LLMProvider, UnknownProviderError
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
    return registry
