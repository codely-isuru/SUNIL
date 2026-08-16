"""Unit tests for the trace spine end-to-end (T4): `LiveTraceContext`,
`emit_stage()`, and `write_audit_event()` together.

Uses a shared-connection in-memory SQLite engine (`StaticPool`) — same
pattern as `test_models.py` — so every `emit()` call and every assertion
in a test see the same database.

Per the backend_engineer memory's L-002 lesson and its "prove fences,
don't trust them" principle: the duplicate-stage test writes the
deliberate violation and confirms it is rejected, and the ET-6 test
queries `audit_events` with the exact query `ARCHITECTURE_V1.md` §8.1
specifies, rather than trusting that `emit()` did the right thing.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool
from sunil.core.trace.context import (
    DuplicateStageEmission,
    LiveTraceContext,
    NullTraceContext,
    TraceContext,
)
from sunil.core.trace.stages import ALL_STAGES_IN_ORDER, TraceStage
from sunil.db.base import Base
from sunil.db.models import AuditEvent
from sunil.redaction import register, reset_registry_for_tests


@pytest_asyncio.fixture
async def sessionmaker() -> AsyncGenerator[async_sessionmaker]:
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    yield async_sessionmaker(engine, expire_on_commit=False)

    await engine.dispose()


@pytest.fixture(autouse=True)
def _clean_registry():
    reset_registry_for_tests()
    yield
    reset_registry_for_tests()


class _FakeClock:
    """A monotonic clock a test can advance by hand — no `time.sleep()`
    needed to prove offsets and the deadline behave correctly."""

    def __init__(self, start: float = 0.0) -> None:
        self._now = start

    def __call__(self) -> float:
        return self._now

    def advance(self, seconds: float) -> None:
        self._now += seconds


@pytest.mark.asyncio
async def test_null_trace_context_still_satisfies_the_protocol() -> None:
    """T1's null object must keep satisfying T4's (refined) Protocol."""
    ctx = NullTraceContext(request_id="r1")
    assert isinstance(ctx, TraceContext)

    await ctx.emit(TraceStage.MESSAGE_RECEIVED, summary="received", detail={"x": 1})

    assert ctx.emitted == [(TraceStage.MESSAGE_RECEIVED, "received", {"x": 1}, None)]
    assert ctx.remaining_deadline_s() == float("inf")


@pytest.mark.asyncio
async def test_emitting_all_twelve_stages_writes_them_in_order_seq_1_to_12(
    sessionmaker: async_sessionmaker,
) -> None:
    """This is ET-6's own query (`ARCHITECTURE_V1.md` §8.1), run directly:
    `SELECT stage, seq FROM audit_events WHERE request_id = :rid ORDER BY
    seq` must return all twelve stages, in the enum's order, none missing.
    """
    ctx = LiveTraceContext(
        request_id="req-et6",
        user_id="user-1",
        conversation_id="conv-1",
        sessionmaker=sessionmaker,
        turn_deadline_s=40.0,
    )

    for stage in ALL_STAGES_IN_ORDER:
        await ctx.emit(stage, summary=f"stage {stage.value}")

    async with sessionmaker() as session:
        rows = (
            await session.scalars(
                select(AuditEvent)
                .where(AuditEvent.request_id == "req-et6")
                .order_by(AuditEvent.seq)
            )
        ).all()

    assert [row.stage for row in rows] == [s.value for s in ALL_STAGES_IN_ORDER]
    assert [row.seq for row in rows] == list(range(1, 13))


@pytest.mark.asyncio
async def test_emitting_a_stage_twice_raises_and_does_not_double_write(
    sessionmaker: async_sessionmaker,
) -> None:
    ctx = LiveTraceContext(
        request_id="req-dup",
        user_id=None,
        conversation_id=None,
        sessionmaker=sessionmaker,
        turn_deadline_s=40.0,
    )

    await ctx.emit(TraceStage.MESSAGE_RECEIVED, summary="first")

    with pytest.raises(DuplicateStageEmission):
        await ctx.emit(TraceStage.MESSAGE_RECEIVED, summary="second attempt")

    async with sessionmaker() as session:
        rows = (
            await session.scalars(select(AuditEvent).where(AuditEvent.request_id == "req-dup"))
        ).all()

    assert len(rows) == 1
    assert rows[0].summary == "first"


@pytest.mark.asyncio
async def test_a_failed_turn_can_still_emit_final_response_deterministically(
    sessionmaker: async_sessionmaker,
) -> None:
    """ADR-015: no LLM call produces `final_response` in M1 — it is
    emitted by deterministic orchestrator code on every path, including a
    failure. Nothing in the emitter special-cases it; proven by emitting
    it directly, on its own, with no other stage emitted first."""
    ctx = LiveTraceContext(
        request_id="req-fail",
        user_id=None,
        conversation_id=None,
        sessionmaker=sessionmaker,
        turn_deadline_s=40.0,
    )

    await ctx.emit(
        TraceStage.FINAL_RESPONSE,
        summary="turn failed",
        detail={"failure_kind": "provider_error"},
    )

    async with sessionmaker() as session:
        row = (
            await session.scalars(select(AuditEvent).where(AuditEvent.request_id == "req-fail"))
        ).one()

    assert row.stage == TraceStage.FINAL_RESPONSE.value
    assert row.detail == {"failure_kind": "provider_error"}


@pytest.mark.asyncio
async def test_offset_ms_advances_with_the_clock(sessionmaker: async_sessionmaker) -> None:
    """`offset_ms` is not a DB column (it lives in the §6 response
    `trace[]`, assembled by T11a/T11b from data the context already has) —
    tested directly against the clock the context was built with."""
    clock = _FakeClock(start=100.0)
    ctx = LiveTraceContext(
        request_id="req-offsets",
        user_id=None,
        conversation_id=None,
        sessionmaker=sessionmaker,
        turn_deadline_s=40.0,
        clock=clock,
    )

    assert ctx._offset_ms() == 0

    clock.advance(2.5)
    assert ctx._offset_ms() == 2500

    await ctx.emit(TraceStage.MESSAGE_RECEIVED, summary="t0")  # must not disturb the clock
    assert ctx._offset_ms() == 2500

    clock.advance(0.001)
    assert ctx._offset_ms() == 2501


@pytest.mark.asyncio
async def test_remaining_deadline_s_counts_down_and_clamps_at_zero(
    sessionmaker: async_sessionmaker,
) -> None:
    clock = _FakeClock(start=0.0)
    ctx = LiveTraceContext(
        request_id="req-deadline",
        user_id=None,
        conversation_id=None,
        sessionmaker=sessionmaker,
        turn_deadline_s=40.0,
        clock=clock,
    )

    assert ctx.remaining_deadline_s() == pytest.approx(40.0)

    clock.advance(15.0)
    assert ctx.remaining_deadline_s() == pytest.approx(25.0)

    clock.advance(100.0)  # well past the deadline
    assert ctx.remaining_deadline_s() == 0.0  # never negative


@pytest.mark.asyncio
async def test_a_registered_secret_in_detail_never_reaches_the_persisted_row(
    sessionmaker: async_sessionmaker,
) -> None:
    """ET-10, exercised against the real write path: register a secret,
    put it in `detail`, emit, then read the row back and confirm the raw
    value is not there."""
    register("sk-ant-fake-persisted-secret", name="anthropic_api_key")

    ctx = LiveTraceContext(
        request_id="req-et10",
        user_id=None,
        conversation_id=None,
        sessionmaker=sessionmaker,
        turn_deadline_s=40.0,
    )

    await ctx.emit(
        TraceStage.LLM_IO,
        summary="called the model with sk-ant-fake-persisted-secret",
        detail={"note": "used key sk-ant-fake-persisted-secret"},
    )

    async with sessionmaker() as session:
        row = (
            await session.scalars(select(AuditEvent).where(AuditEvent.request_id == "req-et10"))
        ).one()

    assert "sk-ant-fake-persisted-secret" not in row.summary
    assert "sk-ant-fake-persisted-secret" not in row.detail["note"]
    assert "«redacted:anthropic_api_key»" in row.detail["note"]


@pytest.mark.asyncio
async def test_a_secret_bearing_object_in_detail_never_reaches_the_persisted_row(
    sessionmaker: async_sessionmaker,
) -> None:
    """T4's review bounce (blocker 2): a raw exception or a custom object in
    a stage's `detail` — entirely plausible on `tool_result`, `agent_result`
    and failure paths once T6/T8/T9/T10 exist — must not leak the secret it
    carries into the persisted `audit_events` table. QA's exact class of
    reproduction, run against the real write path rather than a mock.
    """

    class _ToolFailure(Exception):
        pass

    register("sk-ant-fake-object-in-detail-secret", name="anthropic_api_key")

    ctx = LiveTraceContext(
        request_id="req-et10-object",
        user_id=None,
        conversation_id=None,
        sessionmaker=sessionmaker,
        turn_deadline_s=40.0,
    )

    await ctx.emit(
        TraceStage.TOOL_RESULT,
        summary="tool call failed",
        detail={
            "error": _ToolFailure("auth failed with sk-ant-fake-object-in-detail-secret"),
            "nested": {"cause": _ToolFailure("sk-ant-fake-object-in-detail-secret")},
        },
    )

    async with sessionmaker() as session:
        row = (
            await session.scalars(
                select(AuditEvent).where(AuditEvent.request_id == "req-et10-object")
            )
        ).one()

    serialised = str(row.detail)
    assert "sk-ant-fake-object-in-detail-secret" not in serialised
    assert isinstance(row.detail["error"], str)
    assert isinstance(row.detail["nested"]["cause"], str)
