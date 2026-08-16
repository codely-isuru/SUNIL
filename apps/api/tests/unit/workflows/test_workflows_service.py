"""`sunil.core.workflows.service` (T11a) — FR-063."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession
from sunil.core.workflows.service import create_workflow, transition_workflow_status
from sunil.db.models import User


async def test_create_workflow_persists_a_pending_row_linked_to_the_request(
    session: AsyncSession, user: User
) -> None:
    workflow = await create_workflow(session, owner_user_id=user.id, request_id="req-1")

    assert workflow.id
    assert workflow.owner_user_id == user.id
    assert workflow.request_id == "req-1"
    assert workflow.status == "pending"
    assert workflow.trigger == "chat_message"
    assert workflow.schedule is None
    assert workflow.completed_at is None


async def test_transition_workflow_status_to_completed_sets_completed_at(
    session: AsyncSession, user: User
) -> None:
    workflow = await create_workflow(session, owner_user_id=user.id, request_id="req-1")

    await transition_workflow_status(session, workflow, to_status="completed")

    assert workflow.status == "completed"
    assert workflow.completed_at is not None


async def test_transition_workflow_status_rejects_an_illegal_value(
    session: AsyncSession, user: User
) -> None:
    import pytest

    workflow = await create_workflow(session, owner_user_id=user.id, request_id="req-1")

    with pytest.raises(ValueError, match="cancelled"):
        await transition_workflow_status(session, workflow, to_status="cancelled")
