"""`workflows` writer (FR-063).

Mirrors `core/tasks/service.py`'s status discipline: the workflow
lifecycle also has no `cancelled` state in M1 (ADR-010) — `WorkflowStatus`
(mirrored from `TaskStatus` per `db/models.py`'s own note that "a
workflow's lifecycle is the same shape as its task's in M1") is the
single source of legal values.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from sunil.db.base import utc_now
from sunil.db.models import Workflow, WorkflowStatus, WorkflowTrigger

LEGAL_WORKFLOW_STATUSES: frozenset[str] = frozenset(status.value for status in WorkflowStatus)

_TERMINAL_STATUSES = frozenset({WorkflowStatus.COMPLETED.value, WorkflowStatus.FAILED.value})


async def create_workflow(
    session: AsyncSession,
    *,
    owner_user_id: str,
    request_id: str,
) -> Workflow:
    """One `Workflow` per turn, trigger always `chat_message` in M1
    (FR-063: "creates a Task record and a Workflow record referencing
    it, linked to the request ID and conversation")."""
    workflow = Workflow(
        owner_user_id=owner_user_id,
        trigger=WorkflowTrigger.CHAT_MESSAGE.value,
        status=WorkflowStatus.PENDING.value,
        schedule=None,
        request_id=request_id,
    )
    session.add(workflow)
    await session.commit()
    return workflow


async def transition_workflow_status(
    session: AsyncSession,
    workflow: Workflow,
    *,
    to_status: str,
) -> Workflow:
    if to_status not in LEGAL_WORKFLOW_STATUSES:
        raise ValueError(
            f"{to_status!r} is not a legal workflow status; must be one of "
            f"{sorted(LEGAL_WORKFLOW_STATUSES)} (no `cancelled` state, ADR-010)"
        )

    workflow.status = to_status
    if to_status in _TERMINAL_STATUSES:
        workflow.completed_at = utc_now()

    session.add(workflow)
    await session.commit()
    return workflow
