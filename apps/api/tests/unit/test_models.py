"""Unit tests for `sunil.db.models` (T2).

Uses a shared-connection in-memory SQLite engine (`StaticPool`) so
`Base.metadata.create_all()` and every subsequent statement in a test see
the same database — a plain in-memory SQLite URL hands out a *new*, empty
database per connection otherwise, silently.

Per the L-002 lesson (backend_engineer memory): every assertion here is
scoped to the engine created inside that test's own fixture, never to
state that might have leaked from another test or a prior run.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from datetime import UTC, datetime

import pytest
import pytest_asyncio
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool
from sunil.db.base import Base
from sunil.db.capture import CapturePolicy, RetentionClass, Sensitivity
from sunil.db.models import (
    AuditEvent,
    Conversation,
    Message,
    MessageRole,
    TaskStatusEvent,
    User,
)


@pytest_asyncio.fixture
async def session() -> AsyncGenerator[AsyncSession]:
    """A fresh, isolated in-memory schema for exactly one test."""
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    sessionmaker = async_sessionmaker(engine, expire_on_commit=False)
    async with sessionmaker() as s:
        yield s

    await engine.dispose()


def _capture_kwargs(
    *,
    policy: CapturePolicy = CapturePolicy.REDACTED_FULL,
    sensitivity: Sensitivity = Sensitivity.INTERNAL,
    retention: RetentionClass = RetentionClass.STANDARD,
    training_eligible: bool = True,
) -> dict:
    return {
        "capture_policy": policy.value,
        "sensitivity": sensitivity.value,
        "retention_class": retention.value,
        "training_eligible": training_eligible,
    }


@pytest.mark.asyncio
async def test_all_twelve_tables_exist_after_create_all(session: AsyncSession) -> None:
    expected = {
        "users",
        "conversations",
        "messages",
        "workflows",
        "tasks",
        "task_status_events",
        "plans",
        "tool_calls",
        "approvals",
        "memories",
        "llm_calls",
        "audit_events",
    }
    assert expected == set(Base.metadata.tables.keys())


@pytest.mark.asyncio
async def test_user_id_and_created_at_are_generated(session: AsyncSession) -> None:
    user = User(name="Isuru", username="isuru", password_hash="scrypt$fake$for$test$only")
    session.add(user)
    await session.flush()

    assert user.id is not None and len(user.id) == 36
    assert user.created_at is not None
    assert user.created_at.tzinfo is not None


@pytest.mark.asyncio
async def test_message_role_check_constraint_rejects_an_invalid_value(
    session: AsyncSession,
) -> None:
    """Proves the enum CheckConstraint is real, not just documentation —
    per the memory principle 'prove fences, don't trust them': write the
    deliberate violation and confirm it is rejected."""
    user = User(name="Isuru", username="isuru2", password_hash="x")
    session.add(user)
    await session.flush()

    conversation = Conversation(user_id=user.id)
    session.add(conversation)
    await session.flush()

    bad_message = Message(
        conversation_id=conversation.id,
        seq=1,
        role="not_a_real_role",  # violates ck_messages_role
        content="hi",
        **_capture_kwargs(),
    )
    session.add(bad_message)

    with pytest.raises(IntegrityError):
        await session.flush()


@pytest.mark.asyncio
async def test_message_role_check_constraint_accepts_every_enum_value(
    session: AsyncSession,
) -> None:
    user = User(name="Isuru", username="isuru3", password_hash="x")
    session.add(user)
    await session.flush()
    conversation = Conversation(user_id=user.id)
    session.add(conversation)
    await session.flush()

    for i, role in enumerate(MessageRole):
        session.add(
            Message(
                conversation_id=conversation.id,
                seq=i,
                role=role.value,
                content="ok",
                **_capture_kwargs(),
            )
        )
    await session.flush()  # must not raise


@pytest.mark.asyncio
async def test_capture_columns_are_not_nullable(session: AsyncSession) -> None:
    """Every capture-table insert must go through `resolve_capture()` and
    set all four columns explicitly — an omission must fail loudly."""
    user = User(name="Isuru", username="isuru4", password_hash="x")
    session.add(user)
    await session.flush()
    conversation = Conversation(user_id=user.id)
    session.add(conversation)
    await session.flush()

    message_missing_capture_policy = Message(
        conversation_id=conversation.id,
        seq=0,
        role=MessageRole.USER.value,
        content="hi",
        sensitivity=Sensitivity.INTERNAL.value,
        retention_class=RetentionClass.STANDARD.value,
        training_eligible=True,
        # capture_policy omitted deliberately
    )
    session.add(message_missing_capture_policy)

    with pytest.raises(IntegrityError):
        await session.flush()


@pytest.mark.asyncio
async def test_audit_events_unique_request_id_seq_is_enforced(session: AsyncSession) -> None:
    """ET-6 is graded on `(request_id, seq)` being unique per turn."""
    first = AuditEvent(
        request_id="req-1",
        seq=1,
        stage="message_received",
        actor="api.chat",
        summary="received",
    )
    session.add(first)
    await session.flush()

    duplicate = AuditEvent(
        request_id="req-1",
        seq=1,  # same (request_id, seq) pair
        stage="context_loaded",
        actor="core.conversations",
        summary="also seq 1",
    )
    session.add(duplicate)

    with pytest.raises(IntegrityError):
        await session.flush()


@pytest.mark.asyncio
async def test_audit_events_stage_check_constraint_rejects_unknown_stage(
    session: AsyncSession,
) -> None:
    bad = AuditEvent(
        request_id="req-2",
        seq=1,
        stage="not_one_of_the_twelve",
        actor="api.chat",
        summary="bad stage",
    )
    session.add(bad)

    with pytest.raises(IntegrityError):
        await session.flush()


@pytest.mark.asyncio
async def test_audit_events_has_no_capture_columns(session: AsyncSession) -> None:
    """§7.3.1: a capture policy must never be able to suppress an audit
    row — enforced structurally by not having the columns at all."""
    columns = set(AuditEvent.__table__.columns.keys())
    assert "capture_policy" not in columns
    assert "training_eligible" not in columns


@pytest.mark.asyncio
async def test_task_status_event_records_a_transition(session: AsyncSession) -> None:
    user = User(name="Isuru", username="isuru5", password_hash="x")
    session.add(user)
    await session.flush()

    from sunil.db.models import Task, TaskStatus, Workflow, WorkflowStatus, WorkflowTrigger

    conversation = Conversation(user_id=user.id)
    session.add(conversation)
    await session.flush()

    workflow = Workflow(
        owner_user_id=user.id,
        trigger=WorkflowTrigger.CHAT_MESSAGE.value,
        status=WorkflowStatus.PENDING.value,
        request_id="req-3",
    )
    session.add(workflow)
    await session.flush()

    task = Task(
        workflow_id=workflow.id,
        conversation_id=conversation.id,
        request_id="req-3",
        objective="check on a project",
        status=TaskStatus.PENDING.value,
        assigned_agent="project_manager",
    )
    session.add(task)
    await session.flush()

    event = TaskStatusEvent(
        task_id=task.id,
        from_status=None,
        to_status=TaskStatus.IN_PROGRESS.value,
        at=datetime.now(UTC),
    )
    session.add(event)
    await session.flush()

    assert event.id is not None
    assert event.task_id == task.id
