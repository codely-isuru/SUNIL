"""The audit spine: `LiveTraceContext` → `emit_stage` → `audit_events`.

ROADMAP §28's claim is that a turn is reconstructable from stored records alone.
These tests are what make that a property rather than an aspiration: one row per
stage, ordered, at most once each, redacted, and written in its own transaction
so a later rollback cannot take the spine with it.
"""

from __future__ import annotations

import pytest
from sqlalchemy import select

from sunil.core.audit.writer import write_audit_event
from sunil.core.trace.context import (
    DuplicateStageEmission,
    LiveTraceContext,
    NullTraceContext,
)
from sunil.core.trace.stages import ALL_STAGES_IN_ORDER, TraceStage
from sunil.db.models import AuditEvent


def trace(session_factory, **overrides) -> LiveTraceContext:
    kwargs = {
        "request_id": "req-1",
        "user_id": "owner",
        "conversation_id": "conv-1",
        "sessionmaker": session_factory,
        "turn_deadline_s": 40.0,
    }
    return LiveTraceContext(**{**kwargs, **overrides})


async def test_every_stage_lands_as_one_row_in_order(session_factory) -> None:
    ctx = trace(session_factory)

    for stage in ALL_STAGES_IN_ORDER:
        await ctx.emit(stage, summary=f"{stage.value} happened")

    async with session_factory() as session:
        rows = list(
            (
                await session.execute(
                    select(AuditEvent)
                    .where(AuditEvent.request_id == "req-1")
                    .order_by(AuditEvent.seq)
                )
            ).scalars()
        )

    assert [row.stage for row in rows] == [stage.value for stage in ALL_STAGES_IN_ORDER]
    assert [row.seq for row in rows] == list(range(1, 13))


async def test_a_second_emission_of_the_same_stage_is_refused(session_factory) -> None:
    """Retries belong in `detail` (`provider_attempts`, `plan_attempts`), never as
    a second stage event — enforced here, not left to caller discipline."""
    ctx = trace(session_factory)
    await ctx.emit(TraceStage.LLM_IO, summary="first")

    with pytest.raises(DuplicateStageEmission):
        await ctx.emit(TraceStage.LLM_IO, summary="second")


async def test_a_secret_in_a_detail_never_reaches_the_row(session_factory) -> None:
    from sunil.redaction import register

    register("audit-leak-secret-value", name="probe")
    ctx = trace(session_factory)

    await ctx.emit(
        TraceStage.TOOL_RESULT,
        summary="carrying audit-leak-secret-value",
        detail={"token": "audit-leak-secret-value", "nested": ["audit-leak-secret-value"]},
    )

    async with session_factory() as session:
        row = (await session.execute(select(AuditEvent))).scalar_one()

    assert "audit-leak-secret-value" not in row.summary
    assert "audit-leak-secret-value" not in str(row.detail)


async def test_the_audit_row_survives_a_rolled_back_business_transaction(
    session_factory,
) -> None:
    """The writer opens and commits its OWN short-lived session: an audit row
    must not vanish because an unrelated later write in the same request rolled
    back."""
    async with session_factory() as business_session:
        await write_audit_event(
            session_factory,
            request_id="req-2",
            seq=1,
            stage=TraceStage.REQUEST_RECEIVED,
            task_id=None,
            actor="api",
            summary="written inside a doomed transaction",
            detail=None,
        )
        business_session.add(
            AuditEvent(
                request_id="req-2", seq=99, stage=TraceStage.FINAL_RESPONSE.value,
                actor="api", summary="rolled back", task_id=None, detail=None,
            )
        )
        await business_session.rollback()

    async with session_factory() as session:
        rows = list((await session.execute(select(AuditEvent))).scalars())

    assert [row.seq for row in rows] == [1]


async def test_offsets_are_monotonic_from_the_turns_own_start(session_factory) -> None:
    clock = iter([100.0, 100.5, 101.25])  # construction, then one read per emit
    ctx = trace(session_factory, clock=lambda: next(clock))

    await ctx.emit(TraceStage.REQUEST_RECEIVED, summary="a")
    await ctx.emit(TraceStage.CONTEXT_LOADED, summary="b")

    async with session_factory() as session:
        rows = list(
            (await session.execute(select(AuditEvent).order_by(AuditEvent.seq))).scalars()
        )
    assert [row.detail["offset_ms"] for row in rows] == [500, 1250]


def test_remaining_deadline_never_goes_negative(session_factory) -> None:
    """A caller doing `if remaining < attempt_timeout` gets a clean "no budget
    left" rather than also having to handle a sign flip."""
    clock = iter([0.0, 100.0])
    ctx = trace(session_factory, turn_deadline_s=40.0, clock=lambda: next(clock))

    assert ctx.remaining_deadline_s() == 0.0


async def test_null_trace_context_records_without_a_database() -> None:
    """The seam every lane builds against before the emitter exists — and the one
    a unit test uses when the assertion is about the caller, not the spine."""
    ctx = NullTraceContext(request_id="req-null")

    await ctx.emit(TraceStage.PLAN_CREATED, summary="planned", detail={"steps": 1})

    assert ctx.emitted[0][0] is TraceStage.PLAN_CREATED
    assert ctx.remaining_deadline_s() == float("inf")
