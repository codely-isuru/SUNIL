"""`sunil.providers.base` — the SUNIL-owned provider abstraction (ADR-003,
§4.2). Shape and exception-hierarchy sanity checks; no network, no vendor
SDK involved at all — this module does not import one."""

from __future__ import annotations

import dataclasses

import pytest
from sunil.providers.base import (
    ChatTurn,
    LLMPurpose,
    LLMRequest,
    LLMResponse,
    ModelCapabilities,
    ProviderError,
    ProviderPermanentError,
    ProviderTransientError,
    StructuredOutputError,
    UnknownProviderError,
)


def test_llm_purpose_has_the_three_members_but_m1_writes_only_two() -> None:
    """`FINAL_RESPONSE` is defined (it is in the DB check constraint) but
    no M1 code path uses it (ADR-015) — this test only proves the enum
    shape, not usage."""
    assert {p.value for p in LLMPurpose} == {"plan", "analysis", "final_response"}


def test_chat_turn_is_frozen() -> None:
    turn = ChatTurn(role="user", content="hi")
    with pytest.raises(dataclasses.FrozenInstanceError):
        turn.content = "changed"  # type: ignore[misc]


def test_llm_request_is_frozen() -> None:
    request = LLMRequest(system="s", messages=[ChatTurn(role="user", content="hi")], max_tokens=10)
    with pytest.raises(dataclasses.FrozenInstanceError):
        request.max_tokens = 20  # type: ignore[misc]


def test_llm_response_is_frozen() -> None:
    response = LLMResponse(
        text="hi",
        data=None,
        provider="fake",
        model="fake-model",
        input_tokens=1,
        output_tokens=1,
        stop_reason="end_turn",
        provider_request_id=None,
        latency_ms=1,
    )
    with pytest.raises(dataclasses.FrozenInstanceError):
        response.text = "changed"  # type: ignore[misc]


def test_model_capabilities_is_frozen() -> None:
    capabilities = ModelCapabilities(
        context_window=1,
        max_output=1,
        supports_structured_output=True,
        input_usd_per_mtok=1,  # type: ignore[arg-type]
        output_usd_per_mtok=1,  # type: ignore[arg-type]
    )
    with pytest.raises(dataclasses.FrozenInstanceError):
        capabilities.max_output = 2  # type: ignore[misc]


def test_exception_hierarchy_matches_adr_003() -> None:
    assert issubclass(ProviderTransientError, ProviderError)
    assert issubclass(ProviderPermanentError, ProviderError)
    assert issubclass(StructuredOutputError, ProviderPermanentError)
    assert issubclass(UnknownProviderError, ProviderError)


def test_provider_error_carries_optional_token_and_request_id_info() -> None:
    error = ProviderTransientError(
        "boom", input_tokens=5, output_tokens=7, provider_request_id="r1"
    )

    assert error.input_tokens == 5
    assert error.output_tokens == 7
    assert error.provider_request_id == "r1"


def test_provider_error_defaults_leave_token_info_unknown() -> None:
    """A connection failure that never got a response has nothing to
    report — `None`, not `0`, so a caller can tell "no attempt data" apart
    from "zero tokens were used"."""
    error = ProviderTransientError("boom")

    assert error.input_tokens is None
    assert error.output_tokens is None
    assert error.provider_request_id is None


def test_unknown_provider_error_names_the_missing_provider() -> None:
    error = UnknownProviderError("openai")

    assert error.provider_name == "openai"
    assert "openai" in str(error)
