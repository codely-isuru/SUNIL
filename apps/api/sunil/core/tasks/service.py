"""Task creation and transitions.

Two rules this module exists to hold:

* **Every transition writes a `task_status_events` row.** A task's history is a
  record, not an inference from `completed_at` being null.
* **`project_key` is write-once, at creation, from the `ValidatedPlan`** (C6 §3 /
  ADR-036's Q2 ruling). There is deliberately no setter and no update path: the
  column exists so `GET /api/v1/tasks?project_key=…` is a query rather than a
  per-row audit join, and a value that could drift later would answer that query
  with a different project from the one the plan was validated against.

A task is created only AFTER plan validation, which is why `create_task` takes a
`ValidatedPlan` and not a draft: a task row is a claim that governed work
started, and no such claim exists for a plan that was rejected.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from sunil.core.orchestrator.guards import require_validated_plan
from sunil.db.base import new_uuid, utc_now
from sunil.db.models import Task, TaskStatus, TaskStatusEvent

#: The agent a plan is assigned to when it names several: the first, which is the
#: plan's own ordering and the one the C5 envelope reports as `assigned_agent`.
def _assigned_agent(plan_agents: list[str]) -> str:
    return plan_agents[0]


async def create_task(
    session: AsyncSession,
    *,
    plan: object,
    conversation_id: str,
    request_id: str,
    privacy_level: str = "internal",
) -> Task:
    """Insert a `pending` task for a validated plan, plus its first status event.

    `plan` goes through the ADR-004 Amendment 1 guard rather than being trusted:
    this is the function that turns a plan into the `task_id` every `tool_calls`
    row is written against, so a non-validated plan reaching it would create the
    authorising record for a call that was never validated.
    """
    validated = require_validated_plan(plan)
    task = Task(
        id=new_uuid(),
        conversation_id=conversation_id,
        request_id=request_id,
        objective=validated.objective,
        status=TaskStatus.PENDING.value,
        assigned_agent=_assigned_agent(validated.agents),
        # Write-once, from the plan (C6 §3). Nothing in this module updates it.
        project_key=validated.project_key,
        privacy_level=privacy_level,
    )
    session.add(task)
    # No `id`: `task_status_events.id` is database-assigned and monotonic, which
    # is what makes C6 §2.2's "ties keep write order" true (see the model).
    session.add(TaskStatusEvent(task_id=task.id, from_status=None, to_status=task.status))
    await session.flush()
    return task


async def transition(
    session: AsyncSession,
    task: Task,
    *,
    to_status: TaskStatus,
    failure_kind: str | None = None,
) -> Task:
    """Move a task to `to_status`, recording the transition.

    `project_key` is never touched here — see the module docstring.
    """
    from_status = task.status
    if from_status == to_status.value:
        return task

    task.status = to_status.value
    if to_status is TaskStatus.IN_PROGRESS and task.started_at is None:
        task.started_at = utc_now()
    if to_status in (TaskStatus.COMPLETED, TaskStatus.FAILED):
        task.completed_at = utc_now()
    if failure_kind is not None:
        task.failure_kind = failure_kind

    session.add(
        TaskStatusEvent(task_id=task.id, from_status=from_status, to_status=to_status.value)
    )
    await session.flush()
    return task
