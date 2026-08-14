"""`sunil.providers.anthropic.AnthropicProvider` — the verified surface of
`ARCHITECTURE_V1.md` §4.3, checked against the installed `anthropic`
0.122.0 package. No network, no key (`docs/M1_BUILD_PLAN.md` T6) — a fake
`messages.create` client stands in, and real `anthropic` exception
*instances* are raised through it so the adapter's own `except` clauses
are genuinely exercised.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from pydantic import SecretStr
from sunil.core.registry.model_catalogue import CapabilityDefinition, ModelDefinition, ModelRegistry
from sunil.providers.anthropic import AnthropicProvider
from sunil.providers.base import (
    ChatTurn,
    LLMRequest,
    ProviderPermanentError,
    ProviderTransientError,
    StructuredOutputError,
)

from .conftest import (
    FakeAnthropicClient,
    make_anthropic_message,
    make_authentication_error,
    make_bad_request_error,
    make_connection_error,
    make_internal_server_error,
    make_not_found_error,
    make_overloaded_error,
    make_permission_denied_error,
    make_rate_limit_error,
    make_timeout_error,
    make_unprocessable_entity_error,
)

_FAKE_SECRET = SecretStr("sk-ant-not-a-real-key-test-only")


def _model_registry() -> ModelRegistry:
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
        capabilities={
            "general_reasoning": CapabilityDefinition(
                capability="general_reasoning",
                provider="anthropic",
                model="claude-sonnet-5",
                max_tokens=1024,
                timeout_s=20.0,
            )
        },
    )


def _text_request(**kwargs: object) -> LLMRequest:
    return LLMRequest(
        system="You are helpful.",
        messages=[ChatTurn(role="user", content="hello")],
        max_tokens=100,
        **kwargs,  # type: ignore[arg-type]
    )


async def test_generate_free_text_happy_path() -> None:
    client = FakeAnthropicClient([make_anthropic_message(text="hi there")])
    provider = AnthropicProvider(
        api_key=_FAKE_SECRET, model_registry=_model_registry(), client=client
    )

    response = await provider.generate("claude-sonnet-5", _text_request())

    assert response.text == "hi there"
    assert response.data is None
    assert response.provider == "anthropic"
    assert response.model == "claude-sonnet-5"
    assert response.input_tokens == 10
    assert response.output_tokens == 20
    assert response.provider_request_id == "req_fake_abc123"


async def test_generate_structured_output_happy_path() -> None:
    client = FakeAnthropicClient([make_anthropic_message(text='{"intent": "check_status"}')])
    provider = AnthropicProvider(
        api_key=_FAKE_SECRET, model_registry=_model_registry(), client=client
    )

    response = await provider.generate(
        "claude-sonnet-5", _text_request(json_schema={"type": "object"})
    )

    assert response.text is None
    assert response.data == {"intent": "check_status"}


async def test_output_config_is_sent_only_when_a_schema_is_requested() -> None:
    client = FakeAnthropicClient([make_anthropic_message(text="hi")])
    provider = AnthropicProvider(
        api_key=_FAKE_SECRET, model_registry=_model_registry(), client=client
    )

    await provider.generate("claude-sonnet-5", _text_request())

    assert "output_config" not in client.messages.calls[0]


async def test_output_config_carries_the_json_schema_verbatim() -> None:
    client = FakeAnthropicClient([make_anthropic_message(text="{}")])
    provider = AnthropicProvider(
        api_key=_FAKE_SECRET, model_registry=_model_registry(), client=client
    )
    schema = {"type": "object", "properties": {"x": {"type": "string"}}}

    await provider.generate("claude-sonnet-5", _text_request(json_schema=schema))

    sent = client.messages.calls[0]["output_config"]
    assert sent == {"format": {"type": "json_schema", "schema": schema}}


async def test_timeout_s_is_forwarded_to_the_per_call_timeout() -> None:
    client = FakeAnthropicClient([make_anthropic_message(text="hi")])
    provider = AnthropicProvider(
        api_key=_FAKE_SECRET, model_registry=_model_registry(), client=client
    )

    await provider.generate("claude-sonnet-5", _text_request(), timeout_s=12.5)

    assert client.messages.calls[0]["timeout"] == 12.5


@pytest.mark.parametrize(
    "make_error",
    [make_connection_error, make_timeout_error, make_rate_limit_error, make_internal_server_error],
)
async def test_verified_transient_errors_map_to_provider_transient_error(make_error) -> None:
    client = FakeAnthropicClient([make_error()])
    provider = AnthropicProvider(
        api_key=_FAKE_SECRET, model_registry=_model_registry(), client=client
    )

    with pytest.raises(ProviderTransientError):
        await provider.generate("claude-sonnet-5", _text_request())


@pytest.mark.parametrize(
    "make_error",
    [
        make_bad_request_error,
        make_authentication_error,
        make_permission_denied_error,
        make_not_found_error,
        make_unprocessable_entity_error,
    ],
)
async def test_verified_permanent_errors_map_to_provider_permanent_error(make_error) -> None:
    client = FakeAnthropicClient([make_error()])
    provider = AnthropicProvider(
        api_key=_FAKE_SECRET, model_registry=_model_registry(), client=client
    )

    with pytest.raises(ProviderPermanentError):
        await provider.generate("claude-sonnet-5", _text_request())


async def test_an_unlisted_anthropic_error_is_treated_as_permanent_not_silently_retried() -> None:
    """`OverloadedError` is not on §4.3's verified transient/permanent
    lists. The adapter must not guess it is safe to retry — it fails
    closed as permanent instead."""
    client = FakeAnthropicClient([make_overloaded_error()])
    provider = AnthropicProvider(
        api_key=_FAKE_SECRET, model_registry=_model_registry(), client=client
    )

    with pytest.raises(ProviderPermanentError):
        await provider.generate("claude-sonnet-5", _text_request())


async def test_structured_output_error_when_response_has_no_text_block() -> None:
    from types import SimpleNamespace

    message = SimpleNamespace(
        content=[SimpleNamespace(type="tool_use")],
        usage=SimpleNamespace(input_tokens=3, output_tokens=1),
        stop_reason="tool_use",
    )
    message._request_id = "req_no_text"
    client = FakeAnthropicClient([message])
    provider = AnthropicProvider(
        api_key=_FAKE_SECRET, model_registry=_model_registry(), client=client
    )

    with pytest.raises(StructuredOutputError) as exc_info:
        await provider.generate("claude-sonnet-5", _text_request(json_schema={"type": "object"}))

    # Tokens were still consumed — must not be lost (§13.1).
    assert exc_info.value.input_tokens == 3
    assert exc_info.value.output_tokens == 1


async def test_structured_output_error_on_non_json_text_never_falls_back_to_regex() -> None:
    """§6.1 Layer 2: 'never falls back to regex, never strips markdown
    fences and retries.' A response wrapped in a markdown fence must raise,
    not be silently unwrapped."""
    client = FakeAnthropicClient([make_anthropic_message(text='```json\n{"a": 1}\n```')])
    provider = AnthropicProvider(
        api_key=_FAKE_SECRET, model_registry=_model_registry(), client=client
    )

    with pytest.raises(StructuredOutputError):
        await provider.generate("claude-sonnet-5", _text_request(json_schema={"type": "object"}))


async def test_structured_output_error_when_json_is_not_an_object() -> None:
    client = FakeAnthropicClient([make_anthropic_message(text="[1, 2, 3]")])
    provider = AnthropicProvider(
        api_key=_FAKE_SECRET, model_registry=_model_registry(), client=client
    )

    with pytest.raises(StructuredOutputError):
        await provider.generate("claude-sonnet-5", _text_request(json_schema={"type": "object"}))


async def test_capabilities_delegates_to_the_model_registry_no_second_price_table() -> None:
    provider = AnthropicProvider(
        api_key=_FAKE_SECRET, model_registry=_model_registry(), client=FakeAnthropicClient([])
    )

    capabilities = provider.capabilities("claude-sonnet-5")

    assert capabilities.input_usd_per_mtok == Decimal("2")
    assert capabilities.output_usd_per_mtok == Decimal("10")
    assert capabilities.supports_structured_output is True


async def test_the_api_key_never_appears_on_the_provider_object_or_in_an_error_message() -> None:
    secret_value = "sk-ant-super-secret-value-should-never-leak"  # noqa: S105
    provider = AnthropicProvider(
        api_key=SecretStr(secret_value),
        model_registry=_model_registry(),
        client=FakeAnthropicClient([make_bad_request_error()]),
    )

    with pytest.raises(ProviderPermanentError) as exc_info:
        await provider.generate("claude-sonnet-5", _text_request())

    assert secret_value not in str(exc_info.value)
    assert secret_value not in repr(provider)
    assert not hasattr(provider, "api_key")
    assert not hasattr(provider, "_api_key")
