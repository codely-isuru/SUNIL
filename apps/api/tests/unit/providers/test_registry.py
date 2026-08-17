"""`sunil.providers.registry` — the provider registry (ADR-003 §4.6)."""

from __future__ import annotations

from decimal import Decimal

import pytest
from pydantic import SecretStr
from sunil.core.registry.agents import AgentDefinition, AgentRegistry
from sunil.core.registry.errors import RegistryCrossValidationError
from sunil.core.registry.model_catalogue import CapabilityDefinition, ModelDefinition, ModelRegistry
from sunil.providers.anthropic import AnthropicProvider
from sunil.providers.base import UnknownProviderError
from sunil.providers.openai import OpenAIProvider
from sunil.providers.registry import (
    ProviderRegistry,
    build_provider_registry,
    validate_capability_providers,
)
from sunil.settings import Settings


def test_register_and_get_round_trip() -> None:
    registry = ProviderRegistry()

    class _StubProvider:
        name = "stub"

        def capabilities(self, model: str) -> None:  # pragma: no cover - unused here
            raise NotImplementedError

        async def generate(
            self, model: str, request: object, *, timeout_s: float | None = None
        ):  # pragma: no cover
            raise NotImplementedError

    stub = _StubProvider()
    registry.register(stub)

    assert registry.get("stub") is stub
    assert registry.provider_names() == ["stub"]


def test_unknown_provider_raises_a_named_error_not_a_keyerror() -> None:
    registry = ProviderRegistry()

    with pytest.raises(UnknownProviderError):
        registry.get("no_such_provider")


def _fake_settings(
    *, anthropic_api_key: SecretStr | None, openai_api_key: SecretStr | None
) -> Settings:
    return Settings(
        _env_file=None,
        anthropic_api_key=anthropic_api_key,
        github_token=SecretStr("github_pat_fake-test-value"),
        openai_api_key=openai_api_key,
        session_secret=SecretStr("fake-test-session-secret"),
        owner_username="test-owner",
        owner_password=SecretStr("fake-test-owner-password"),
    )


def _fake_settings_both_keys() -> Settings:
    return _fake_settings(
        anthropic_api_key=SecretStr("sk-ant-fake-test-value"),
        openai_api_key=SecretStr("sk-fake-test-value-for-openai"),
    )


def _fake_model_registry() -> ModelRegistry:
    return ModelRegistry(
        pricing_version="2026-08-14",
        models={
            "claude-sonnet-5": ModelDefinition(
                model_id="claude-sonnet-5",
                provider="anthropic",
                context_window=1_000_000,
                max_output=128_000,
                input_usd_per_mtok=Decimal("2"),
                output_usd_per_mtok=Decimal("10"),
                supports_structured_output=True,
            )
        },
        capabilities={},
    )


def test_build_provider_registry_registers_anthropic_by_default() -> None:
    """No network call happens here — constructing `AsyncAnthropic` is
    pure object setup, never an HTTP request."""
    registry = build_provider_registry(
        settings=_fake_settings_both_keys(), model_registry=_fake_model_registry()
    )

    provider = registry.get("anthropic")
    assert isinstance(provider, AnthropicProvider)


def test_build_provider_registry_registers_openai_too() -> None:
    """T23, ADR-003 §4.6's own stated test: 'adding a second provider' is
    one more `registry.register(...)` line here and nothing else changes
    upstream. No network call happens here — constructing `AsyncOpenAI` is
    pure object setup, never an HTTP request."""
    registry = build_provider_registry(
        settings=_fake_settings_both_keys(), model_registry=_fake_model_registry()
    )

    provider = registry.get("openai")
    assert isinstance(provider, OpenAIProvider)
    # Both providers coexist — registering the second one must never
    # evict or shadow the first.
    assert isinstance(registry.get("anthropic"), AnthropicProvider)
    assert set(registry.provider_names()) == {"anthropic", "openai"}


# -- Optional provider keys (T25) --------------------------------------------
# The owner has an OpenAI key and no Anthropic key. A provider whose key is
# absent must be absent from the registry, not broken (a `None` `api_key`
# reaching `AnthropicProvider.__init__`/`OpenAIProvider.__init__` would crash
# on `.get_secret_value()` -- this is the guard that keeps that from ever
# happening, not just a happy assumption).


def test_build_provider_registry_registers_only_openai_when_only_its_key_is_present() -> None:
    registry = build_provider_registry(
        settings=_fake_settings(anthropic_api_key=None, openai_api_key=SecretStr("sk-fake")),
        model_registry=_fake_model_registry(),
    )

    assert registry.provider_names() == ["openai"]
    with pytest.raises(UnknownProviderError):
        registry.get("anthropic")


def test_build_provider_registry_registers_only_anthropic_when_only_its_key_is_present() -> None:
    registry = build_provider_registry(
        settings=_fake_settings(anthropic_api_key=SecretStr("sk-ant-fake"), openai_api_key=None),
        model_registry=_fake_model_registry(),
    )

    assert registry.provider_names() == ["anthropic"]
    with pytest.raises(UnknownProviderError):
        registry.get("openai")


def test_build_provider_registry_registers_nothing_when_no_key_is_present() -> None:
    """A boot with no provider key at all is legal at this layer -- fail-
    closed moves to `validate_capability_providers()` below, which knows
    whether an unregistered provider is actually reachable."""
    registry = build_provider_registry(
        settings=_fake_settings(anthropic_api_key=None, openai_api_key=None),
        model_registry=_fake_model_registry(),
    )

    assert registry.provider_names() == []


# -- validate_capability_providers (T25) -------------------------------------
# "Fail closed where it actually matters": a capability an agent actually
# uses (preferred_capability/escalation_capability, config/agents.yaml) that
# resolves to an unregistered provider is a loud startup failure naming the
# capability, the provider and the missing env var. A capability nobody
# references (kept only so a later key needs a config edit, not code -- T24's
# general_reasoning_anthropic) is not checked at all.


def _agent(
    agent_id: str, *, preferred_capability: str, escalation_capability: str
) -> AgentDefinition:
    return AgentDefinition(
        id=agent_id,
        role="test role",
        instructions=["do the thing"],
        objectives=["report status"],
        memory_scope=["short_term"],
        preferred_capability=preferred_capability,
        escalation_capability=escalation_capability,
    )


def _model_registry_with_capabilities(
    *capabilities: tuple[str, str],
) -> ModelRegistry:
    """`capabilities` is (capability_name, provider) pairs; every capability
    points at the same placeholder model id for that provider."""
    models: dict[str, ModelDefinition] = {}
    caps: dict[str, CapabilityDefinition] = {}
    for capability_name, provider in capabilities:
        model_id = f"{provider}-model"
        models.setdefault(
            model_id,
            ModelDefinition(
                model_id=model_id,
                provider=provider,
                context_window=1_000_000,
                max_output=128_000,
                input_usd_per_mtok=Decimal("1"),
                output_usd_per_mtok=Decimal("1"),
                supports_structured_output=True,
            ),
        )
        caps[capability_name] = CapabilityDefinition(
            capability=capability_name,
            provider=provider,
            model=model_id,
            max_tokens=1024,
            timeout_s=20.0,
        )
    return ModelRegistry(pricing_version="test-pricing", models=models, capabilities=caps)


def test_validate_capability_providers_passes_when_every_reachable_capability_has_a_provider() -> (
    None
):
    agents = AgentRegistry(
        {
            "project_manager": _agent(
                "project_manager",
                preferred_capability="general_reasoning",
                escalation_capability="complex_reasoning",
            )
        }
    )
    model_registry = _model_registry_with_capabilities(
        ("general_reasoning", "openai"), ("complex_reasoning", "anthropic")
    )
    provider_registry = build_provider_registry(
        settings=_fake_settings_both_keys(), model_registry=model_registry
    )

    validate_capability_providers(
        agents=agents, model_registry=model_registry, provider_registry=provider_registry
    )  # must not raise


def test_validate_capability_providers_refuses_to_boot_on_missing_provider_key() -> None:
    """The owner's exact situation: general_reasoning points at openai, but
    no OpenAI key -- this must fail loudly, naming the capability, the
    provider and the missing env var."""
    agents = AgentRegistry(
        {
            "project_manager": _agent(
                "project_manager",
                preferred_capability="general_reasoning",
                escalation_capability="complex_reasoning",
            )
        }
    )
    model_registry = _model_registry_with_capabilities(
        ("general_reasoning", "openai"), ("complex_reasoning", "anthropic")
    )
    # Only anthropic has a key -- openai (what general_reasoning needs) does not.
    provider_registry = build_provider_registry(
        settings=_fake_settings(anthropic_api_key=SecretStr("sk-ant-fake"), openai_api_key=None),
        model_registry=model_registry,
    )

    with pytest.raises(RegistryCrossValidationError) as exc_info:
        validate_capability_providers(
            agents=agents, model_registry=model_registry, provider_registry=provider_registry
        )

    message = str(exc_info.value)
    assert "general_reasoning" in message
    assert "openai" in message
    assert "OPENAI_API_KEY" in message


def test_validate_capability_providers_ignores_escalation_capability() -> None:
    """`escalation_capability` is deliberately excluded (see the function's
    own docstring): `ask_model(..., use_escalation=True)` is real, wired
    plumbing (`core/agent_framework/base.py`) but M1 has zero call sites
    that ever pass `True` — checking it would force an Anthropic key onto
    an owner who only has an OpenAI one, to satisfy a code path nothing in
    M1 can reach. `complex_reasoning` (the real M1 escalation capability,
    unchanged by T24) pointing at an unregistered provider must not block
    boot, mirroring T24's own `general_reasoning_anthropic` case."""
    agents = AgentRegistry(
        {
            "project_manager": _agent(
                "project_manager",
                preferred_capability="general_reasoning",
                escalation_capability="complex_reasoning",
            )
        }
    )
    model_registry = _model_registry_with_capabilities(
        ("general_reasoning", "openai"), ("complex_reasoning", "anthropic")
    )
    # Only openai has a key -- anthropic (what complex_reasoning needs) does not.
    provider_registry = build_provider_registry(
        settings=_fake_settings(anthropic_api_key=None, openai_api_key=SecretStr("sk-fake")),
        model_registry=model_registry,
    )

    validate_capability_providers(
        agents=agents, model_registry=model_registry, provider_registry=provider_registry
    )  # must not raise -- escalation_capability is unreachable in M1


def test_validate_capability_providers_ignores_an_unreferenced_capability() -> None:
    """T24's `general_reasoning_anthropic`: defined so a later Anthropic key
    needs a config edit, not code -- no agent points at it, so it sitting
    on an unregistered provider must not block boot.

    Both reachable capabilities (`general_reasoning`, `complex_reasoning`)
    point at `openai` here so they stay satisfied by the OpenAI-only key,
    isolating the one thing under test: the unreferenced
    `general_reasoning_anthropic` capability, pointed at the provider with
    no key."""
    agents = AgentRegistry(
        {
            "project_manager": _agent(
                "project_manager",
                preferred_capability="general_reasoning",
                escalation_capability="complex_reasoning",
            )
        }
    )
    model_registry = _model_registry_with_capabilities(
        ("general_reasoning", "openai"),
        ("complex_reasoning", "openai"),
        ("general_reasoning_anthropic", "anthropic"),
    )
    provider_registry = build_provider_registry(
        settings=_fake_settings(anthropic_api_key=None, openai_api_key=SecretStr("sk-fake")),
        model_registry=model_registry,
    )

    validate_capability_providers(
        agents=agents, model_registry=model_registry, provider_registry=provider_registry
    )  # must not raise -- general_reasoning_anthropic is unreferenced
