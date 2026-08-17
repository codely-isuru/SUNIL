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

from sunil.core.registry.agents import AgentRegistry
from sunil.core.registry.errors import RegistryCrossValidationError
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

    **T25 (2026-08-17): a provider whose API key is absent is simply not
    registered, not broken.** `anthropic_api_key`/`openai_api_key` are now
    `SecretStr | None` — the owner has an OpenAI key and no Anthropic key,
    so `Settings` must still construct, and this function must still boot
    an app with only one provider available. Fail-closed moves to
    `validate_capability_providers()` below: an *unreachable* capability
    pointing at the missing provider is fine (it may simply be unused,
    e.g. `general_reasoning_anthropic`); a *reachable* one is a loud
    startup failure there, not a silent gap here.
    """
    registry = ProviderRegistry()
    if settings.anthropic_api_key is not None:
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
    if settings.openai_api_key is not None:
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


def validate_capability_providers(
    *, agents: AgentRegistry, model_registry: ModelRegistry, provider_registry: ProviderRegistry
) -> None:
    """T25: refuse to boot if a capability an agent can actually reach
    resolves to a provider with no registered API key.

    "Reachable" means named by some agent's `preferred_capability`
    (`config/agents.yaml`) — the orchestrator's own plan-generation call
    resolves against the same capability name as the one M1 agent's
    `preferred_capability` (`core/orchestrator/turn.py`'s
    `_PLAN_CAPABILITY`, documented in `ARCHITECTURE_V1.md` §4.4/§5.1 as
    "the orchestrator's own plan call resolves against the same
    capability the PM agent's analysis call uses"), so checking every
    agent's declared `preferred_capability` covers it without importing
    `turn.py`'s private constant here.

    **`escalation_capability` is deliberately excluded, checked rather
    than assumed:** `core/agent_framework/base.py`'s `ask_model(...,
    use_escalation: bool = False)` is real, wired plumbing, but grepping
    the whole package for `use_escalation` turns up zero call sites that
    ever pass `True` — M1 has "no escalation logic that fires it"
    (`config/agents.yaml`'s own comment, `ARCHITECTURE_V1.md` §4.5).
    Checking it here would force the owner to configure an Anthropic key
    solely to satisfy a code path nothing in M1 can reach, which is
    exactly the "invent a fake credential" habit ET-10 exists to
    discourage, applied to a real one this time. When M6 adds escalation
    logic that actually calls `use_escalation=True`, this function must
    be revisited to cover `escalation_capability` too — a comment, not a
    silent gap, so the next engineer to add that logic finds this rather
    than rediscovers the hole.

    A capability nobody's `preferred_capability` references at all (T24's
    `general_reasoning_anthropic`, kept only so a later key is a config
    edit, not code) is, for the identical reason, not checked either —
    fail-closed belongs where a real turn could reach an absent provider,
    not on every capability that merely exists.

    Raises `RegistryCrossValidationError` naming, for every problem found
    (not just the first): the capability, the provider it resolves to,
    and the environment variable that would register it — never a bare
    `KeyError` or an unattributed pydantic complaint.
    """
    problems: list[str] = []
    checked: set[str] = set()
    for agent in agents.values():
        capability_name = agent.preferred_capability
        if capability_name in checked:
            continue
        checked.add(capability_name)

        capability = model_registry.get_capability(capability_name)
        if capability.provider in provider_registry.provider_names():
            continue
        env_var = f"{capability.provider.upper()}_API_KEY"
        problems.append(
            f"agent {agent.id!r}.preferred_capability names capability "
            f"{capability_name!r}, which resolves to provider {capability.provider!r} "
            f"— no {env_var} is set, so that provider is not registered "
            "(config/models.yaml, sunil/settings.py)"
        )

    if problems:
        raise RegistryCrossValidationError(problems)
