"""`sunil.providers.registry` — the provider registry (ADR-003 §4.6)."""

from __future__ import annotations

from decimal import Decimal

import pytest
from pydantic import SecretStr
from sunil.core.registry.model_catalogue import ModelDefinition, ModelRegistry
from sunil.providers.anthropic import AnthropicProvider
from sunil.providers.base import UnknownProviderError
from sunil.providers.registry import ProviderRegistry, build_provider_registry
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


def _fake_settings() -> Settings:
    return Settings(
        _env_file=None,
        anthropic_api_key=SecretStr("sk-ant-fake-test-value"),
        github_token=SecretStr("github_pat_fake-test-value"),
        openai_api_key=SecretStr("sk-fake-test-value-for-openai"),
        session_secret=SecretStr("fake-test-session-secret"),
        owner_username="test-owner",
        owner_password=SecretStr("fake-test-owner-password"),
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
        settings=_fake_settings(), model_registry=_fake_model_registry()
    )

    provider = registry.get("anthropic")
    assert isinstance(provider, AnthropicProvider)
