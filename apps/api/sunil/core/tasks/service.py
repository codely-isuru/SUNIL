"""`tasks` + `task_status_events` writers (FR-063, FR-065).

FR-065: "The Orchestrator tracks task status through a defined lifecycle
(at minimum: `pending` -> `in_progress` -> `completed`/`failed`) and
persists every transition." ADR-010 kept Cancel client-side in M1
specifically to avoid adding a `cancelled` state three days out — do not
reintroduce one here "for completeness"; QA's and Security's tests both
assert its absence.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from sunil.db.base import utc_now
from sunil.db.models import Task, TaskStatus, TaskStatusEvent

# The exact FR-065 lifecycle. Frozen deliberately -- see the module
# docstring and test_the_lifecycle_has_no_cancelled_state.
LEGAL_TASK_STATUSES: frozenset[str] = frozenset(status.value for status in TaskStatus)

_TERMINAL_STATUSES = frozenset({TaskStatus.COMPLETED.value, TaskStatus.FAILED.value})


async def create_task(
    session: AsyncSession,
    *,
    workflow_id: str,
    conversation_id: str,
    request_id: str,
    objective: str,
    assigned_agent: str,
    priority: str = "normal",
    model_used: str | None = None,
) -> Task:
    """Create a `Task` in its initial `pending` state and write the
    corresponding `task_status_events` row (`from_status=None`,
    `to_status="pending"`) — a task's status history starts here, not
    with an implicit first row nobody wrote (FR-065's own "persists every
    transition").
    """
    task = Task(
        workflow_id=workflow_id,
        conversation_id=conversation_id,
        request_id=request_id,
        objective=objective,
        status=TaskStatus.PENDING.value,
        priority=priority,
        assigned_agent=assigned_agent,
        model_used=model_used,
    )
    session.add(task)
    await session.flush()  # assign task.id before the status event references it

    session.add(
        TaskStatusEvent(task_id=task.id, from_status=None, to_status=TaskStatus.PENDING.value)
    )
    await session.commit()
    return task


async def transition_task_status(
    session: AsyncSession,
    task: Task,
    *,
    to_status: str,
    failure_kind: str | None = None,
) -> Task:
    """Move `task` to `to_status`, stamping `started_at`/`completed_at`
    as appropriate and writing the `task_status_events` row. Raises
    `ValueError` for anything outside `LEGAL_TASK_STATUSES` — structural
    protection against a future caller passing `"cancelled"` or a typo,
    matching the same "fail loud, not silently" discipline as the
    registry errors elsewhere in this codebase.
    """
    if to_status not in LEGAL_TASK_STATUSES:
        raise ValueError(
            f"{to_status!r} is not a legal task status; must be one of "
            f"{sorted(LEGAL_TASK_STATUSES)} (FR-065 — no `cancelled` state, ADR-010)"
        )

    from_status = task.status
    task.status = to_status

    if to_status == TaskStatus.IN_PROGRESS.value and task.started_at is None:
        task.started_at = utc_now()

    if to_status in _TERMINAL_STATUSES:
        task.completed_at = utc_now()

    if to_status == TaskStatus.FAILED.value and failure_kind is not None:
        task.failure_kind = failure_kind

    session.add(TaskStatusEvent(task_id=task.id, from_status=from_status, to_status=to_status))
    await session.commit()
    return task
