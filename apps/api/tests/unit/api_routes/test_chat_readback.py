"""`sunil.api.routes.chat`'s trace/usage readback helpers (T11a).

§8.1's own canonical query: the trace is reconstructable from
`audit_events` alone. These functions are what the chat response's
`trace[]`/`usage` fields are actually built from, so they read the
database directly rather than trusting whatever a `TraceContext` held in
memory during the turn (which is a different object, possibly a `Null`
one in a unit test).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession
from sunil.api.routes.chat import read_trace_entries, read_usage
from sunil.db.models import AuditEvent, LLMCall


async def _add_audit_event(
    session: AsyncSession, *, request_id: str, seq: int, stage: str, at, detail=None
) -> None:
    session.add(
        AuditEvent(
            request_id=request_id,
            seq=seq,
            stage=stage,
            task_id=None,
            actor="test",
            summary=stage,
            detail=detail,
            at=at,
        )
    )


async def test_read_trace_entries_returns_rows_in_seq_order_with_offsets(
    session: AsyncSession,
) -> None:
    start = datetime(2026, 8, 17, 0, 0, 0, tzinfo=UTC)
    await _add_audit_event(session, request_id="req-1", seq=1, stage="message_received", at=start)
    await _add_audit_event(
        session,
        request_id="req-1",
        seq=2,
        stage="context_loaded",
        at=start + timedelta(milliseconds=250),
        detail={"foo": "bar"},
    )
    await session.commit()

    entries = await read_trace_entries(session, request_id="req-1")

    assert [e.stage for e in entries] == ["message_received", "context_loaded"]
    assert entries[0].offset_ms == 0
    assert entries[1].offset_ms == 250
    assert entries[1].detail == {"foo": "bar"}


async def test_read_trace_entries_is_empty_for_an_unknown_request(
    session: AsyncSession,
) -> None:
    entries = await read_trace_entries(session, request_id="no-such-request")

    assert entries == []


async def test_read_trace_entries_only_returns_rows_for_the_given_request_id(
    session: AsyncSession,
) -> None:
    start = datetime(2026, 8, 17, 0, 0, 0, tzinfo=UTC)
    await _add_audit_event(session, request_id="req-1", seq=1, stage="message_received", at=start)
    await _add_audit_event(session, request_id="req-2", seq=1, stage="message_received", at=start)
    await session.commit()

    entries = await read_trace_entries(session, request_id="req-1")

    assert len(entries) == 1


async def test_read_usage_sums_every_llm_call_row_for_the_request(
    session: AsyncSession,
) -> None:
    session.add(
        LLMCall(
            request_id="req-1",
            task_id=None,
            agent_id=None,
            purpose="plan",
            capability="general_reasoning",
            provider="anthropic",
            model="claude-sonnet-5",
            attempt=1,
            request_system=None,
            request_messages=None,
            request_schema=None,
            response_text=None,
            response_json=None,
            stop_reason=None,
            input_tokens=100,
            output_tokens=20,
            cost_micro_usd=5_000,
            pricing_version="2026-08-14",
            latency_ms=500,
            capture_policy="redacted_full",
            sensitivity="internal",
            retention_class="standard",
            training_eligible=True,
        )
    )
    session.add(
        LLMCall(
            request_id="req-1",
            task_id=None,
            agent_id=None,
            purpose="analysis",
            capability="general_reasoning",
            provider="anthropic",
            model="claude-sonnet-5",
            attempt=1,
            request_system=None,
            request_messages=None,
            request_schema=None,
            response_text=None,
            response_json=None,
            stop_reason=None,
            input_tokens=200,
            output_tokens=40,
            cost_micro_usd=7_000,
            pricing_version="2026-08-14",
            latency_ms=600,
            capture_policy="redacted_full",
            sensitivity="internal",
            retention_class="standard",
            training_eligible=True,
        )
    )
    await session.commit()

    usage = await read_usage(session, request_id="req-1")

    assert usage.input_tokens == 300
    assert usage.output_tokens == 60
    assert usage.cost_usd == 0.012


async def test_read_usage_is_zero_when_no_llm_calls_exist(session: AsyncSession) -> None:
    usage = await read_usage(session, request_id="no-such-request")

    assert usage.input_tokens == 0
    assert usage.output_tokens == 0
    assert usage.cost_usd == 0.0
