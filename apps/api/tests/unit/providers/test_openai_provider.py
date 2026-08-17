"""`sunil.providers.openai.OpenAIProvider` — the second registered
provider (T23, ADR-003 §4.6: "adding a provider without touching
agents"). Verified against the installed `openai==3.1.0` package rather
than assumed, exactly as T6 did for `anthropic` (`docs/M1_BUILD_PLAN.md`
T6 "load the claude-api skill rather than guessing" — the same
discipline, applied to a second vendor).

No network, no key — a fake `chat.completions.create` client stands in,
and real `openai` exception *instances* are raised through it so the
adapter's own `except` clauses are genuinely exercised (mirrors
`test_anthropic_provider.py`'s pattern exactly).

Error classification is **status-code-keyed, not name-keyed** (A-16,
applied identically to the second provider): an unnamed `APIStatusError`
at 529 must be transient, and any status the document does not name
(`>= 500`) must still classify correctly.
"""

from __future__ import annotations

import os
from decimal import Decimal

import pytest
from pydantic import SecretStr
from sunil.core.registry.model_catalogue import CapabilityDefinition, ModelDefinition, ModelRegistry
from sunil.providers.base import (
    ChatTurn,
    LLMRequest,
    ProviderPermanentError,
    ProviderTransientError,
    StructuredOutputError,
)
from sunil.providers.openai import OpenAIProvider

from .conftest import (
    FakeOpenAIClient,
    make_openai_authentication_error,
    make_openai_bad_request_error,
    make_openai_conflict_error,
    make_openai_connection_error,
    make_openai_internal_server_error,
    make_openai_message,
    make_openai_not_found_error,
    make_openai_permission_denied_error,
    make_openai_rate_limit_error,
    make_openai_timeout_error,
    make_openai_unnamed_5xx_error,
    make_openai_unprocessable_entity_error,
)

_FAKE_SECRET = SecretStr("sk-not-a-real-key-test-only")
# Never dereferenced (a fake client is always injected) — any string
# satisfies the constructor. Real validation of what a base URL may be
# lives on `Settings`, not on this class.
_FAKE_BASE_URL = "https://api.openai.com/v1"


def _model_registry() -> ModelRegistry:
    return ModelRegistry(
        pricing_version="2026-08-14",
        models={
            "gpt-5.1-2025-11-13": ModelDefinition(
                model_id="gpt-5.1-2025-11-13",
                provider="openai",
                context_window=400_000,
                max_output=128_000,
                input_usd_per_mtok=Decimal("0"),
                output_usd_per_mtok=Decimal("0"),
                supports_structured_output=True,
            )
        },
        capabilities={
            "general_reasoning_openai": CapabilityDefinition(
                capability="general_reasoning_openai",
                provider="openai",
                model="gpt-5.1-2025-11-13",
                max_tokens=1024,
                timeout_s=20.0,
            )
        },
    )


def _build_provider(client: object, *, api_key: SecretStr = _FAKE_SECRET) -> OpenAIProvider:
    return OpenAIProvider(
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
    client = FakeOpenAIClient([make_openai_message(content="hi there")])
    provider = _build_provider(client)

    response = await provider.generate("gpt-5.1-2025-11-13", _text_request())

    assert response.text == "hi there"
    assert response.data is None
    assert response.provider == "openai"
    assert response.model == "gpt-5.1-2025-11-13"
    assert response.input_tokens == 10
    assert response.output_tokens == 20
    assert response.provider_request_id == "chatcmpl_fake_abc123"
    assert response.attempts == 1


async def test_system_prompt_becomes_the_first_message_not_a_top_level_kwarg() -> None:
    """Verified against the installed SDK: `chat.completions.create` has no
    separate `system=` parameter (unlike Anthropic) — the system role is
    just the first entry in `messages`."""
    client = FakeOpenAIClient([make_openai_message(content="hi")])
    provider = _build_provider(client)

    await provider.generate("gpt-5.1-2025-11-13", _text_request())

    sent = client.chat.completions.calls[0]
    assert "system" not in sent
    assert sent["messages"][0] == {"role": "system", "content": "You are helpful."}
    assert sent["messages"][1] == {"role": "user", "content": "hello"}


async def test_max_tokens_is_sent_as_max_completion_tokens_not_the_deprecated_kwarg() -> None:
    """Verified against the installed SDK's own docstring: `max_tokens` "is
    now deprecated in favor of `max_completion_tokens`" — do not send the
    deprecated kwarg for a newly-written adapter."""
    client = FakeOpenAIClient([make_openai_message(content="hi")])
    provider = _build_provider(client)

    await provider.generate("gpt-5.1-2025-11-13", _text_request())

    sent = client.chat.completions.calls[0]
    assert sent["max_completion_tokens"] == 100
    assert "max_tokens" not in sent


async def test_generate_structured_output_happy_path() -> None:
    client = FakeOpenAIClient([make_openai_message(content='{"intent": "check_status"}')])
    provider = _build_provider(client)

    response = await provider.generate(
        "gpt-5.1-2025-11-13", _text_request(json_schema={"type": "object"})
    )

    assert response.text is None
    assert response.data == {"intent": "check_status"}


async def test_response_format_is_sent_only_when_a_schema_is_requested() -> None:
    client = FakeOpenAIClient([make_openai_message(content="hi")])
    provider = _build_provider(client)

    await provider.generate("gpt-5.1-2025-11-13", _text_request())

    assert "response_format" not in client.chat.completions.calls[0]


async def test_response_format_carries_the_json_schema_with_strict_true() -> None:
    """T23 finding: OpenAI's schema-conformance guarantee is opt-in via
    `strict: true` (verified from the installed SDK's own
    `JSONSchema.strict` docstring) — unlike Anthropic's unconditional
    constrained decoding. The adapter always sets it so a caller who asks
    for `json_schema` gets the strongest guarantee this provider has."""
    client = FakeOpenAIClient([make_openai_message(content="{}")])
    provider = _build_provider(client)
    schema = {"type": "object", "properties": {"x": {"type": "string"}}}

    await provider.generate("gpt-5.1-2025-11-13", _text_request(json_schema=schema))

    sent = client.chat.completions.calls[0]["response_format"]
    assert sent == {
        "type": "json_schema",
        "json_schema": {"name": "sunil_structured_output", "schema": schema, "strict": True},
    }


async def test_effort_is_sent_as_reasoning_effort() -> None:
    """Verified against the installed SDK's `ReasoningEffort` Literal:
    every value M1/`ARCHITECTURE_V1.md` §4.4 permits for `effort`
    (low/medium/high/xhigh/max) is also a legal `reasoning_effort` value
    for this provider — a strict superset, so passing it through verbatim
    is safe over the exact value space SUNIL ever sets. Not independently
    verified via a live call whether `gpt-5.1` actually changes behaviour
    on it — see the module docstring in `providers/openai.py`."""
    client = FakeOpenAIClient([make_openai_message(content="hi")])
    provider = _build_provider(client)

    await provider.generate("gpt-5.1-2025-11-13", _text_request(effort="high"))

    sent = client.chat.completions.calls[0]
    assert sent["reasoning_effort"] == "high"


async def test_stop_sequences_are_sent_as_stop() -> None:
    client = FakeOpenAIClient([make_openai_message(content="hi")])
    provider = _build_provider(client)

    await provider.generate("gpt-5.1-2025-11-13", _text_request(stop_sequences=["END"]))

    assert client.chat.completions.calls[0]["stop"] == ["END"]


async def test_timeout_s_is_forwarded_to_the_per_call_timeout() -> None:
    client = FakeOpenAIClient([make_openai_message(content="hi")])
    provider = _build_provider(client)

    await provider.generate("gpt-5.1-2025-11-13", _text_request(), timeout_s=12.5)

    assert client.chat.completions.calls[0]["timeout"] == 12.5


async def test_base_url_is_passed_explicitly_to_the_real_client(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A-11/ADR-017 applied to the second provider: the one thing that must
    never regress back to a hard-coded/omitted value — a real client class
    is substituted here (never actually constructed against the network)
    so the actual kwarg SUNIL sends is inspected, not assumed."""
    captured: dict[str, object] = {}

    class _CapturingAsyncOpenAI:
        def __init__(self, **kwargs: object) -> None:
            captured.update(kwargs)

    monkeypatch.setattr("sunil.providers.openai.AsyncOpenAI", _CapturingAsyncOpenAI)

    OpenAIProvider(
        api_key=_FAKE_SECRET,
        base_url="http://127.0.0.1:9999",
        model_registry=_model_registry(),
    )

    assert captured["base_url"] == "http://127.0.0.1:9999"
    assert captured["max_retries"] == 0


@pytest.mark.parametrize(
    "make_error",
    [
        make_openai_connection_error,
        make_openai_timeout_error,
        make_openai_rate_limit_error,
        make_openai_internal_server_error,
    ],
)
async def test_verified_transient_errors_map_to_provider_transient_error(make_error) -> None:
    client = FakeOpenAIClient([make_error()])
    provider = _build_provider(client)

    with pytest.raises(ProviderTransientError):
        await provider.generate("gpt-5.1-2025-11-13", _text_request())


async def test_an_unnamed_5xx_status_is_transient_by_status_code_alone() -> None:
    """A-16: a bare `openai.APIStatusError` at 529 is not a named subclass
    at all — a stronger proof than Anthropic's `OverloadedError` case that
    classification is by `status_code`, never by class name."""
    client = FakeOpenAIClient([make_openai_unnamed_5xx_error()])
    provider = _build_provider(client)

    with pytest.raises(ProviderTransientError):
        await provider.generate("gpt-5.1-2025-11-13", _text_request())


@pytest.mark.parametrize(
    "make_error",
    [
        make_openai_bad_request_error,
        make_openai_authentication_error,
        make_openai_permission_denied_error,
        make_openai_not_found_error,
        make_openai_unprocessable_entity_error,
        make_openai_conflict_error,
    ],
)
async def test_verified_permanent_errors_map_to_provider_permanent_error(make_error) -> None:
    client = FakeOpenAIClient([make_error()])
    provider = _build_provider(client)

    with pytest.raises(ProviderPermanentError):
        await provider.generate("gpt-5.1-2025-11-13", _text_request())


async def test_an_exception_with_no_status_code_at_all_is_permanent_by_design() -> None:
    """A-16's catch-all, applied identically to the second provider: an
    `OpenAIError` that is neither a connection failure nor an
    `APIStatusError` (so it carries no `status_code` to key off) is
    classified permanent — 'including any exception class this document
    does not name'."""
    import openai

    class _MysteryOpenAIError(openai.OpenAIError):
        pass

    client = FakeOpenAIClient([_MysteryOpenAIError("something new")])
    provider = _build_provider(client)

    with pytest.raises(ProviderPermanentError):
        await provider.generate("gpt-5.1-2025-11-13", _text_request())


async def test_structured_output_error_on_refusal() -> None:
    """A model refusal carries `message.refusal`, not `message.content` —
    §6.1 Layer 2 must not silently treat a refusal as parseable data."""
    client = FakeOpenAIClient(
        [make_openai_message(content=None, refusal="I can't help with that.")]
    )
    provider = _build_provider(client)

    with pytest.raises(StructuredOutputError):
        await provider.generate("gpt-5.1-2025-11-13", _text_request(json_schema={"type": "object"}))


async def test_structured_output_error_when_message_has_no_content() -> None:
    client = FakeOpenAIClient([make_openai_message(content=None, refusal=None)])
    provider = _build_provider(client)

    with pytest.raises(StructuredOutputError) as exc_info:
        await provider.generate("gpt-5.1-2025-11-13", _text_request(json_schema={"type": "object"}))

    # Tokens were still consumed — must not be lost (§13.1).
    assert exc_info.value.input_tokens == 10
    assert exc_info.value.output_tokens == 20


async def test_structured_output_error_on_non_json_text_never_falls_back_to_regex() -> None:
    """§6.1 Layer 2: 'never falls back to regex, never strips markdown
    fences and retries.' A response wrapped in a markdown fence must raise,
    not be silently unwrapped."""
    client = FakeOpenAIClient([make_openai_message(content='```json\n{"a": 1}\n```')])
    provider = _build_provider(client)

    with pytest.raises(StructuredOutputError):
        await provider.generate("gpt-5.1-2025-11-13", _text_request(json_schema={"type": "object"}))


async def test_structured_output_error_when_json_is_not_an_object() -> None:
    client = FakeOpenAIClient([make_openai_message(content="[1, 2, 3]")])
    provider = _build_provider(client)

    with pytest.raises(StructuredOutputError):
        await provider.generate("gpt-5.1-2025-11-13", _text_request(json_schema={"type": "object"}))


async def test_capabilities_delegates_to_the_model_registry_no_second_price_table() -> None:
    provider = _build_provider(FakeOpenAIClient([]))

    capabilities = provider.capabilities("gpt-5.1-2025-11-13")

    assert capabilities.supports_structured_output is True


async def test_the_api_key_never_appears_on_the_provider_object_or_in_an_error_message() -> None:
    secret_value = "sk-super-secret-openai-value-should-never-leak"  # noqa: S105
    provider = _build_provider(
        FakeOpenAIClient([make_openai_bad_request_error()]), api_key=SecretStr(secret_value)
    )

    with pytest.raises(ProviderPermanentError) as exc_info:
        await provider.generate("gpt-5.1-2025-11-13", _text_request())

    assert secret_value not in str(exc_info.value)
    assert secret_value not in repr(provider)
    assert not hasattr(provider, "api_key")
    assert not hasattr(provider, "_api_key")


# ---------------------------------------------------------------------------
# Live — hits the real OpenAI API. Skipped (not failed) when no real key is
# present; deselected in CI via `-m "not live"` (mirrors the pattern
# `tests/exit/test_et01_coherent_traceable_response.py` uses for Anthropic —
# skip on missing Day-3 secrets is a different state to a RED test blocked
# on missing code). Not an exit-level end-to-end turn: no M1 capability
# routes through `openai` yet (`general_reasoning` stays on Anthropic — see
# `config/models.yaml`'s own T23 comment), so the meaningful live proof at
# this stage is the adapter itself talking to the real endpoint, not a full
# chat turn through the orchestrator.
# ---------------------------------------------------------------------------


@pytest.mark.live
async def test_live_generate_free_text_against_the_real_api() -> None:
    key = os.environ.get("OPENAI_API_KEY")
    if not key:
        pytest.skip(
            "blocked on secrets, not on code: needs a real OPENAI_API_KEY in the "
            "environment. Not a red test result."
        )

    provider = OpenAIProvider(
        api_key=SecretStr(key),
        base_url=os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1"),
        model_registry=_model_registry(),
    )

    response = await provider.generate(
        "gpt-5.1-2025-11-13",
        LLMRequest(
            system="Reply with exactly the single word: pong",
            messages=[ChatTurn(role="user", content="ping")],
            max_tokens=16,
        ),
        timeout_s=20.0,
    )

    assert response.provider == "openai"
    assert response.text is not None and response.text.strip()
    assert response.input_tokens > 0
    assert response.output_tokens > 0
    assert response.provider_request_id
