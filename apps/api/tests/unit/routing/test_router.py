"""`sunil.core.routing.router.ModelRouter` — the Model Router (ADR-003,
§4.5, §5.3). All tests run against `FakeProvider` — no network, no key
(`docs/M1_BUILD_PLAN.md` T6).
"""

from __future__ import annotations

import asyncio
from decimal import Decimal

import pytest
from sunil.core.registry.model_catalogue import CapabilityDefinition, ModelDefinition, ModelRegistry
from sunil.core.routing.retry import MAX_ATTEMPTS, TurnDeadlineExceeded
from sunil.core.routing.router import (
    ErrorKind,
    ModelRouter,
    NullLLMCallRecorder,
    ProviderExhaustedError,
)
from sunil.providers.base import (
    ChatTurn,
    LLMPurpose,
    LLMRequest,
    LLMResponse,
    ProviderPermanentError,
    ProviderTransientError,
    StructuredOutputError,
)

from .conftest import (
    FakeProvider,
    FakeTraceContext,
    make_model_capabilities,
    make_model_registry,
    make_provider_registry,
)


def _request(*, json_schema: dict | None = None) -> LLMRequest:
    return LLMRequest(
        system="You are a test.",
        messages=[ChatTurn(role="user", content="hello")],
        max_tokens=100,
        json_schema=json_schema,
    )


def _response(*, input_tokens: int = 10, output_tokens: int = 20) -> LLMResponse:
    return LLMResponse(
        text="a reply",
        data=None,
        provider="fake",
        model="fake-model-1",
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        stop_reason="end_turn",
        provider_request_id="req_fake_1",
        latency_ms=5,
    )


async def test_happy_path_records_exactly_one_attempt_and_returns_the_response() -> None:
    fake = FakeProvider(
        "fake",
        capabilities_by_model={"fake-model-1": make_model_capabilities()},
        responses=[_response()],
    )
    recorder = NullLLMCallRecorder()
    router = ModelRouter(
        model_registry=make_model_registry(),
        provider_registry=make_provider_registry(fake),
        recorder=recorder,
    )

    response = await router.run(
        capability="general_reasoning",
        request=_request(),
        purpose=LLMPurpose.PLAN,
        ctx=FakeTraceContext(),
        request_id="req-1",
    )

    assert response.text == "a reply"
    assert len(fake.calls) == 1
    assert len(recorder.recorded) == 1
    record = recorder.recorded[0]
    assert record.attempt == 1
    assert record.purpose == LLMPurpose.PLAN
    assert record.error_kind is None
    assert record.pricing_version == "test-pricing"
    assert record.cost_micro_usd > 0


async def test_transient_failure_then_success_records_two_attempts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sleeps: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        sleeps.append(seconds)

    monkeypatch.setattr(asyncio, "sleep", fake_sleep)

    fake = FakeProvider(
        "fake",
        capabilities_by_model={"fake-model-1": make_model_capabilities()},
        responses=[ProviderTransientError("connection reset"), _response()],
    )
    recorder = NullLLMCallRecorder()
    router = ModelRouter(
        model_registry=make_model_registry(),
        provider_registry=make_provider_registry(fake),
        recorder=recorder,
    )

    response = await router.run(
        capability="general_reasoning",
        request=_request(),
        purpose=LLMPurpose.ANALYSIS,
        ctx=FakeTraceContext(),
        request_id="req-2",
    )

    assert response.text == "a reply"
    assert len(fake.calls) == 2
    assert len(sleeps) == 1  # backoff before the second attempt only
    assert [r.attempt for r in recorder.recorded] == [1, 2]
    assert recorder.recorded[0].error_kind == ErrorKind.TRANSIENT_PROVIDER_ERROR
    assert recorder.recorded[1].error_kind is None


async def test_permanent_error_raises_immediately_with_no_retry() -> None:
    fake = FakeProvider(
        "fake",
        capabilities_by_model={"fake-model-1": make_model_capabilities()},
        responses=[ProviderPermanentError("bad request")],
    )
    recorder = NullLLMCallRecorder()
    router = ModelRouter(
        model_registry=make_model_registry(),
        provider_registry=make_provider_registry(fake),
        recorder=recorder,
    )

    with pytest.raises(ProviderExhaustedError):
        await router.run(
            capability="general_reasoning",
            request=_request(),
            purpose=LLMPurpose.PLAN,
            ctx=FakeTraceContext(),
            request_id="req-3",
        )

    assert len(fake.calls) == 1  # never retried
    assert len(recorder.recorded) == 1
    assert recorder.recorded[0].error_kind == ErrorKind.PERMANENT_PROVIDER_ERROR


async def test_structured_output_error_raises_immediately_with_no_retry() -> None:
    """A `StructuredOutputError` is a `ProviderPermanentError` subclass —
    retrying a response the model already produced and got wrong would
    not fix a schema mismatch (§6.1 Layer 2)."""
    error = StructuredOutputError(
        "did not parse", input_tokens=42, output_tokens=7, provider_request_id="req_bad"
    )
    fake = FakeProvider(
        "fake",
        capabilities_by_model={"fake-model-1": make_model_capabilities()},
        responses=[error],
    )
    recorder = NullLLMCallRecorder()
    router = ModelRouter(
        model_registry=make_model_registry(),
        provider_registry=make_provider_registry(fake),
        recorder=recorder,
    )

    with pytest.raises(ProviderExhaustedError):
        await router.run(
            capability="general_reasoning",
            request=_request(json_schema={"type": "object"}),
            purpose=LLMPurpose.PLAN,
            ctx=FakeTraceContext(),
            request_id="req-4",
        )

    assert len(fake.calls) == 1
    assert len(recorder.recorded) == 1
    # A schema-conformance failure still consumed real tokens — that cost
    # must not be lost (§13.1).
    assert recorder.recorded[0].input_tokens == 42
    assert recorder.recorded[0].output_tokens == 7
    assert recorder.recorded[0].cost_micro_usd > 0
    assert recorder.recorded[0].error_kind == ErrorKind.STRUCTURED_OUTPUT_ERROR


async def test_exhausts_after_max_attempts_transient_failures(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_sleep(seconds: float) -> None:
        return None

    monkeypatch.setattr(asyncio, "sleep", fake_sleep)

    failures = [ProviderTransientError(f"attempt {i} failed") for i in range(MAX_ATTEMPTS)]
    fake = FakeProvider(
        "fake",
        capabilities_by_model={"fake-model-1": make_model_capabilities()},
        responses=list(failures),
    )
    recorder = NullLLMCallRecorder()
    router = ModelRouter(
        model_registry=make_model_registry(),
        provider_registry=make_provider_registry(fake),
        recorder=recorder,
    )

    with pytest.raises(ProviderExhaustedError) as exc_info:
        await router.run(
            capability="general_reasoning",
            request=_request(),
            purpose=LLMPurpose.PLAN,
            ctx=FakeTraceContext(),
            request_id="req-5",
        )

    assert len(fake.calls) == MAX_ATTEMPTS
    assert len(recorder.recorded) == MAX_ATTEMPTS
    assert all(r.error_kind == ErrorKind.TRANSIENT_PROVIDER_ERROR for r in recorder.recorded)
    # The last underlying provider error is chained, not swallowed.
    assert isinstance(exc_info.value.__cause__, ProviderTransientError)


async def test_turn_deadline_breach_prevents_the_attempt_and_records_nothing() -> None:
    """§5.3: an attempt whose own timeout exceeds the remaining budget is
    never started — so nothing is recorded as an `llm_calls` row for it."""
    fake = FakeProvider(
        "fake",
        capabilities_by_model={"fake-model-1": make_model_capabilities()},
        responses=[],
    )
    recorder = NullLLMCallRecorder()
    router = ModelRouter(
        model_registry=make_model_registry(timeout_s=20.0),
        provider_registry=make_provider_registry(fake),
        recorder=recorder,
    )
    ctx = FakeTraceContext(remaining_values=[5.0])  # less than the 20s the capability needs

    with pytest.raises(TurnDeadlineExceeded) as exc_info:
        await router.run(
            capability="general_reasoning",
            request=_request(),
            purpose=LLMPurpose.PLAN,
            ctx=ctx,
            request_id="req-6",
        )

    assert exc_info.value.remaining_s == 5.0
    assert exc_info.value.needed_s == 20.0
    assert len(fake.calls) == 0
    assert len(recorder.recorded) == 0


async def test_a_second_provider_needs_no_change_to_this_router() -> None:
    """ADR-003's own test of whether the abstraction is right: register a
    second, independent fake provider under a different capability and run
    a full request through it, with zero edits to `router.py`,
    `capabilities.py` or `pricing.py` — the same code every other test in
    this module already exercises."""
    provider_a = FakeProvider(
        "provider_a",
        capabilities_by_model={"model-a": make_model_capabilities()},
        responses=[_response()],
    )
    provider_b = FakeProvider(
        "provider_b",
        capabilities_by_model={"model-b": make_model_capabilities(input_usd_per_mtok="99")},
        responses=[_response()],
    )
    model_registry = ModelRegistry(
        pricing_version="test-pricing",
        models={
            "model-a": ModelDefinition(
                model_id="model-a",
                provider="provider_a",
                context_window=1_000,
                max_output=1_000,
                input_usd_per_mtok=Decimal("2"),
                output_usd_per_mtok=Decimal("10"),
                supports_structured_output=True,
            ),
            "model-b": ModelDefinition(
                model_id="model-b",
                provider="provider_b",
                context_window=1_000,
                max_output=1_000,
                input_usd_per_mtok=Decimal("99"),
                output_usd_per_mtok=Decimal("99"),
                supports_structured_output=True,
            ),
        },
        capabilities={
            "capability_a": CapabilityDefinition(
                capability="capability_a",
                provider="provider_a",
                model="model-a",
                max_tokens=100,
                timeout_s=20.0,
            ),
            "capability_b": CapabilityDefinition(
                capability="capability_b",
                provider="provider_b",
                model="model-b",
                max_tokens=100,
                timeout_s=20.0,
            ),
        },
    )
    provider_registry = make_provider_registry(provider_a, provider_b)
    router = ModelRouter(model_registry=model_registry, provider_registry=provider_registry)

    response_a = await router.run(
        capability="capability_a",
        request=_request(),
        purpose=LLMPurpose.PLAN,
        ctx=FakeTraceContext(),
        request_id="req-a",
    )
    response_b = await router.run(
        capability="capability_b",
        request=_request(),
        purpose=LLMPurpose.ANALYSIS,
        ctx=FakeTraceContext(),
        request_id="req-b",
    )

    assert response_a.text == "a reply"
    assert response_b.text == "a reply"
    assert len(provider_a.calls) == 1
    assert len(provider_b.calls) == 1
