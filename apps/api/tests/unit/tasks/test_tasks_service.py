"""`sunil.core.tasks.service` (T11a) — FR-063, FR-065.

FR-065's lifecycle is exactly `pending -> in_progress -> completed|failed`
— **no `cancelled` state** (ADR-010: Cancel stays client-side in M1).
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sunil.core.tasks.service import create_task, transition_task_status
from sunil.db.models import Conversation, TaskStatusEvent, User, Workflow


async def test_create_task_persists_a_pending_task_row(
    session: AsyncSession,
    user_and_conversation: tuple[User, Conversation],
    workflow: Workflow,
) -> None:
    _user, conversation = user_and_conversation

    task = await create_task(
        session,
        workflow_id=workflow.id,
        conversation_id=conversation.id,
        request_id="req-1",
        objective="Check on Sample Project.",
        assigned_agent="project_manager",
    )

    assert task.id
    assert task.status == "pending"
    assert task.workflow_id == workflow.id
    assert task.conversation_id == conversation.id
    assert task.request_id == "req-1"
    assert task.objective == "Check on Sample Project."
    assert task.assigned_agent == "project_manager"


async def test_create_task_writes_a_status_event_for_the_initial_pending_state(
    session: AsyncSession,
    user_and_conversation: tuple[User, Conversation],
    workflow: Workflow,
) -> None:
    _user, conversation = user_and_conversation

    task = await create_task(
        session,
        workflow_id=workflow.id,
        conversation_id=conversation.id,
        request_id="req-1",
        objective="x",
        assigned_agent="project_manager",
    )

    result = await session.execute(
        select(TaskStatusEvent).where(TaskStatusEvent.task_id == task.id)
    )
    events = list(result.scalars().all())
    assert len(events) == 1
    assert events[0].from_status is None
    assert events[0].to_status == "pending"


async def test_transition_task_status_updates_status_and_records_an_event(
    session: AsyncSession,
    user_and_conversation: tuple[User, Conversation],
    workflow: Workflow,
) -> None:
    _user, conversation = user_and_conversation
    task = await create_task(
        session,
        workflow_id=workflow.id,
        conversation_id=conversation.id,
        request_id="req-1",
        objective="x",
        assigned_agent="project_manager",
    )

    await transition_task_status(session, task, to_status="in_progress")

    assert task.status == "in_progress"
    assert task.started_at is not None

    result = await session.execute(
        select(TaskStatusEvent)
        .where(TaskStatusEvent.task_id == task.id)
        .order_by(TaskStatusEvent.at)
    )
    events = list(result.scalars().all())
    assert [e.to_status for e in events] == ["pending", "in_progress"]
    assert events[1].from_status == "pending"


async def test_transition_to_completed_sets_completed_at(
    session: AsyncSession,
    user_and_conversation: tuple[User, Conversation],
    workflow: Workflow,
) -> None:
    _user, conversation = user_and_conversation
    task = await create_task(
        session,
        workflow_id=workflow.id,
        conversation_id=conversation.id,
        request_id="req-1",
        objective="x",
        assigned_agent="project_manager",
    )

    await transition_task_status(session, task, to_status="in_progress")
    await transition_task_status(session, task, to_status="completed")

    assert task.status == "completed"
    assert task.completed_at is not None


async def test_transition_to_failed_records_the_failure_kind(
    session: AsyncSession,
    user_and_conversation: tuple[User, Conversation],
    workflow: Workflow,
) -> None:
    _user, conversation = user_and_conversation
    task = await create_task(
        session,
        workflow_id=workflow.id,
        conversation_id=conversation.id,
        request_id="req-1",
        objective="x",
        assigned_agent="project_manager",
    )

    await transition_task_status(session, task, to_status="failed", failure_kind="plan_rejected")

    assert task.status == "failed"
    assert task.completed_at is not None
    assert task.failure_kind == "plan_rejected"


async def test_the_lifecycle_has_no_cancelled_state() -> None:
    """FR-065 / ADR-010: the lifecycle is exactly pending -> in_progress ->
    completed|failed. This test is the tripwire against ever adding
    `cancelled` "out of tidiness" -- both QA's and Security's tests assume
    its absence."""
    from sunil.core.tasks.service import LEGAL_TASK_STATUSES

    assert LEGAL_TASK_STATUSES == frozenset({"pending", "in_progress", "completed", "failed"})
    assert "cancelled" not in LEGAL_TASK_STATUSES
