"""``sunil.db`` — the schema rules that carry a security property.

Not an ORM smoke test: every assertion below is a rule from ARCHITECTURE_V2 §1
(one portable schema, Postgres deployed / SQLite for unit tests), C1's `tool_calls`
provenance requirement, or the R2 rule that this module declares NO `approvals`
table. The audit spine's uniqueness constraint is the one that actually stops a
class of bug.
"""

from __future__ import annotations

import pytest
from sqlalchemy import inspect, select
from sqlalchemy.exc import IntegrityError

from sunil.core.trace.stages import ALL_STAGES_IN_ORDER, TraceStage
from sunil.db import models
from sunil.db.models import AuditEvent, Conversation, ToolCall


async def test_audit_events_cannot_hold_two_rows_at_the_same_seq(session_factory) -> None:
    """`UniqueConstraint(request_id, seq)`: the spine is an ordered chain, so two
    writers claiming the same position must be an error, not a coin flip."""
    async with session_factory() as session:
        session.add(
            AuditEvent(
                request_id="req-1", seq=1, stage=TraceStage.REQUEST_RECEIVED.value,
                actor="api", summary="first", task_id=None, detail=None,
            )
        )
        await session.commit()

    async with session_factory() as session:
        session.add(
            AuditEvent(
                request_id="req-1", seq=1, stage=TraceStage.CONTEXT_LOADED.value,
                actor="api", summary="collides", task_id=None, detail=None,
            )
        )
        with pytest.raises(IntegrityError):
            await session.commit()


async def test_audit_events_stage_is_constrained_to_the_twelve(session_factory) -> None:
    """A CHECK constraint over the enum, not a free string: a typo'd stage name
    would otherwise sit in the spine looking like a thirteenth stage."""
    async with session_factory() as session:
        session.add(
            AuditEvent(
                request_id="req-2", seq=1, stage="not_a_stage", actor="api",
                summary="x", task_id=None, detail=None,
            )
        )
        with pytest.raises(IntegrityError):
            await session.commit()


async def test_the_twelve_stages_are_exactly_the_spine(session_factory) -> None:
    assert len(ALL_STAGES_IN_ORDER) == 12
    assert ALL_STAGES_IN_ORDER[0] is TraceStage.REQUEST_RECEIVED
    assert ALL_STAGES_IN_ORDER[-1] is TraceStage.FINAL_RESPONSE


async def test_audit_events_carry_no_capture_policy_columns(session_factory) -> None:
    """ADR-014's capture columns are deliberately absent here: a capture policy
    must never be able to suppress an audit row (§7.3.1)."""
    columns = {c.name for c in AuditEvent.__table__.columns}

    assert not columns & {"capture_policy", "training_eligible", "retention_class"}


async def test_the_spine_declares_no_approvals_table_of_its_own(session_factory) -> None:
    """Wave-1 ruling R2, re-pointed. This module used to assert C4's persisted
    shape off `db/models.py::Approval` — a class whose VARCHAR timestamps and
    single index contradicted every deployed database, so the tests passed
    against a table no deployment has.

    The true shape is pinned where the true declaration lives:
    `tests/unit/approvals/test_migration_matches_table.py` (declaration vs
    migration) and `tests/unit/approvals/test_real_service_contract.py` (C4 §6's
    behaviours, including the explicit-`pending` insert and the status
    transitions). What remains for THIS module is the absence itself, and the
    fence that makes it safe — `tests/unit/test_alembic_autogenerate_fence.py`.
    """
    from sunil.db.base import Base

    assert "approvals" not in Base.metadata.tables
    assert not hasattr(models, "Approval")


async def test_tool_calls_record_adapter_provenance_per_c1(session_factory) -> None:
    """C1 §2: `adapter_kind`/`server_id` land on the row so "audit shows adapter
    type per call" is a database fact, not an inference — and both are nullable
    because step 1 can exit before any adapter is resolved."""
    columns = inspect(ToolCall).columns

    assert columns["adapter_kind"].nullable is True
    assert columns["server_id"].nullable is True
    for required in ("request_id", "task_id", "agent_id", "tool", "operation", "outcome"):
        assert columns[required].nullable is False


async def test_conversations_record_the_creating_lanes_channel(session_factory) -> None:
    """C5 §2.3 blast radius: the bearer lane may only reach conversations it
    created, which is only decidable if the channel is stored at creation."""
    async with session_factory() as session:
        session.add(Conversation(id="c-1", channel="service", user_id=None))
        session.add(Conversation(id="c-2", channel="web", user_id="owner"))
        await session.commit()

    async with session_factory() as session:
        session.add(Conversation(id="c-3", channel="telepathy", user_id=None))
        with pytest.raises(IntegrityError):
            await session.commit()
