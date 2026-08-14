"""`sunil.providers.anthropic.AnthropicProvider` — the verified surface of
`ARCHITECTURE_V1.md` §4.3, checked against the installed `anthropic`
0.122.0 package. No network, no key (`docs/M1_BUILD_PLAN.md` T6) — a fake
`messages.create` client stands in, and real `anthropic` exception
*instances* are raised through it so the adapter's own `except` clauses
are genuinely exercised.

Error classification is **status-code-keyed, not name-keyed** (A-16):
`OverloadedError` (529) must be transient even though its *name* suggests
nothing about retryability, and any status the document does not name
(`>= 500`) must still classify correctly.
"""

from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace

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
    make_conflict_error,
    make_connection_error,
    make_internal_server_error,
    make_not_found_error,
    make_overloaded_error,
    make_permission_denied_error,
    make_rate_limit_error,
    make_request_too_large_error,
    make_timeout_error,
    make_unprocessable_entity_error,
)

_FAKE_SECRET = SecretStr("sk-ant-not-a-real-key-test-only")
# Never dereferenced (a fake client is always injected) — any string
# satisfies the constructor. Real validation of what a base URL may be
# lives on `Settings`, not on this class.
_FAKE_BASE_URL = "https://api.anthropic.com"


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


def _build_provider(client: object, *, api_key: SecretStr = _FAKE_SECRET) -> AnthropicProvider:
    return AnthropicProvider(
        api_key=api_key, base_url=_FAKE_BASE_URL, model_registry=_model_registry(), client=client
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
    provider = _build_provider(client)

    response = await provider.generate("claude-sonnet-5", _text_request())

    assert response.text == "hi there"
    assert response.data is None
    assert response.provider == "anthropic"
    assert response.model == "claude-sonnet-5"
    assert response.input_tokens == 10
    assert response.output_tokens == 20
    assert response.provider_request_id == "req_fake_abc123"
    assert response.attempts == 1


async def test_generate_structured_output_happy_path() -> None:
    client = FakeAnthropicClient([make_anthropic_message(text='{"intent": "check_status"}')])
    provider = _build_provider(client)

    response = await provider.generate(
        "claude-sonnet-5", _text_request(json_schema={"type": "object"})
    )

    assert response.text is None
    assert response.data == {"intent": "check_status"}


async def test_output_config_is_sent_only_when_a_schema_is_requested() -> None:
    client = FakeAnthropicClient([make_anthropic_message(text="hi")])
    provider = _build_provider(client)

    await provider.generate("claude-sonnet-5", _text_request())

    assert "output_config" not in client.messages.calls[0]


async def test_output_config_carries_the_json_schema_verbatim() -> None:
    client = FakeAnthropicClient([make_anthropic_message(text="{}")])
    provider = _build_provider(client)
    schema = {"type": "object", "properties": {"x": {"type": "string"}}}

    await provider.generate("claude-sonnet-5", _text_request(json_schema=schema))

    sent = client.messages.calls[0]["output_config"]
    assert sent == {"format": {"type": "json_schema", "schema": schema}}


async def test_effort_is_sent_inside_output_config_never_as_a_top_level_kwarg() -> None:
    """A-15: `effort` is a field of `output_config`, verified directly
    against `anthropic/types/output_config_param.py` in the installed
    0.122.0 package — the architecture doc's prose was wrong before
    2026-08-14 and this is the corrected, tested behaviour. Do not "fix"
    this back to a top-level `effort=` kwarg."""
    client = FakeAnthropicClient([make_anthropic_message(text="hi")])
    provider = _build_provider(client)

    await provider.generate("claude-sonnet-5", _text_request(effort="high"))

    sent = client.messages.calls[0]
    assert "effort" not in sent
    assert sent["output_config"] == {"effort": "high"}


async def test_timeout_s_is_forwarded_to_the_per_call_timeout() -> None:
    client = FakeAnthropicClient([make_anthropic_message(text="hi")])
    provider = _build_provider(client)

    await provider.generate("claude-sonnet-5", _text_request(), timeout_s=12.5)

    assert client.messages.calls[0]["timeout"] == 12.5


async def test_base_url_is_passed_explicitly_to_the_real_client(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A-11/ADR-017: the one thing that must never regress back to a
    hard-coded/omitted value — a real client is constructed here (network
    is never touched merely by constructing it) so the actual kwarg SUNIL
    sends is inspected, not assumed."""
    captured: dict[str, object] = {}

    class _CapturingAsyncAnthropic:
        def __init__(self, **kwargs: object) -> None:
            captured.update(kwargs)

    monkeypatch.setattr("sunil.providers.anthropic.AsyncAnthropic", _CapturingAsyncAnthropic)

    AnthropicProvider(
        api_key=_FAKE_SECRET,
        base_url="http://127.0.0.1:9999",
        model_registry=_model_registry(),
    )

    assert captured["base_url"] == "http://127.0.0.1:9999"
    assert captured["max_retries"] == 0


@pytest.mark.parametrize(
    "make_error",
    [make_connection_error, make_timeout_error, make_rate_limit_error, make_internal_server_error],
)
async def test_verified_transient_errors_map_to_provider_transient_error(make_error) -> None:
    client = FakeAnthropicClient([make_error()])
    provider = _build_provider(client)

    with pytest.raises(ProviderTransientError):
        await provider.generate("claude-sonnet-5", _text_request())


async def test_an_unnamed_5xx_status_is_transient_by_status_code_alone() -> None:
    """A-16: `OverloadedError` (529) is not on §4.3's old name-keyed list
    but 529 is `>= 500`, so it must be transient — 529 means 'try again',
    and failing a turn on it would be a self-inflicted outage."""
    client = FakeAnthropicClient([make_overloaded_error()])
    provider = _build_provider(client)

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
        make_conflict_error,
        make_request_too_large_error,
    ],
)
async def test_verified_permanent_errors_map_to_provider_permanent_error(make_error) -> None:
    client = FakeAnthropicClient([make_error()])
    provider = _build_provider(client)

    with pytest.raises(ProviderPermanentError):
        await provider.generate("claude-sonnet-5", _text_request())


async def test_an_exception_with_no_status_code_at_all_is_permanent_by_design() -> None:
    """A-16's catch-all: an `AnthropicError` that is neither a connection
    failure nor an `APIStatusError` (so it carries no `status_code` to
    key off) is classified permanent — 'including any exception class
    this document does not name'."""
    import anthropic

    class _MysteryAnthropicError(anthropic.AnthropicError):
        pass

    client = FakeAnthropicClient([_MysteryAnthropicError("something new")])
    provider = _build_provider(client)

    with pytest.raises(ProviderPermanentError):
        await provider.generate("claude-sonnet-5", _text_request())


async def test_structured_output_error_when_response_has_no_text_block() -> None:
    message = SimpleNamespace(
        content=[SimpleNamespace(type="tool_use")],
        usage=SimpleNamespace(input_tokens=3, output_tokens=1),
        stop_reason="tool_use",
    )
    message._request_id = "req_no_text"
    client = FakeAnthropicClient([message])
    provider = _build_provider(client)

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
    provider = _build_provider(client)

    with pytest.raises(StructuredOutputError):
        await provider.generate("claude-sonnet-5", _text_request(json_schema={"type": "object"}))


async def test_structured_output_error_when_json_is_not_an_object() -> None:
    client = FakeAnthropicClient([make_anthropic_message(text="[1, 2, 3]")])
    provider = _build_provider(client)

    with pytest.raises(StructuredOutputError):
        await provider.generate("claude-sonnet-5", _text_request(json_schema={"type": "object"}))


async def test_capabilities_delegates_to_the_model_registry_no_second_price_table() -> None:
    provider = _build_provider(FakeAnthropicClient([]))

    capabilities = provider.capabilities("claude-sonnet-5")

    assert capabilities.input_usd_per_mtok == Decimal("2")
    assert capabilities.output_usd_per_mtok == Decimal("10")
    assert capabilities.supports_structured_output is True


async def test_the_api_key_never_appears_on_the_provider_object_or_in_an_error_message() -> None:
    secret_value = "sk-ant-super-secret-value-should-never-leak"  # noqa: S105
    provider = _build_provider(
        FakeAnthropicClient([make_bad_request_error()]), api_key=SecretStr(secret_value)
    )

    with pytest.raises(ProviderPermanentError) as exc_info:
        await provider.generate("claude-sonnet-5", _text_request())

    assert secret_value not in str(exc_info.value)
    assert secret_value not in repr(provider)
    assert not hasattr(provider, "api_key")
    assert not hasattr(provider, "_api_key")
