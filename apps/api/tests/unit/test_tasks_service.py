"""Task creation and transitions — including C6 §3's write-once `project_key`."""

from __future__ import annotations

import pytest
from sqlalchemy import select

from sunil.core.orchestrator.guards import InvalidPlanExecution
from sunil.core.orchestrator.plan_validator import ToolCatalogue, validate_plan
from sunil.core.tasks.service import create_task, transition
from sunil.db.base import new_uuid
from sunil.db.models import Conversation, Task, TaskStatus, TaskStatusEvent

AGENTS = {"project_manager": {"tools": {"fake_tool": ["write_item"]}}}
PROJECTS = {"sunil": {"display_name": "SUNIL"}}
CATALOGUE = ToolCatalogue(operations_by_tool={"fake_tool": frozenset({"write_item"})})


def _plan(project_key: str | None = "sunil"):
    return validate_plan(
        {
            "intent": "demo",
            "confidence": 0.9,
            "privacy_level": "internal",
            "objective": "write the demo item",
            "project_key": project_key,
            "agents": ["project_manager"],
            "tools": ["fake_tool"],
            "steps": [
                {
                    "id": "step_1",
                    "action": "tool_call",
                    "tool": "fake_tool",
                    "operation": "write_item",
                    "params": {"key": "demo", "value": "1"},
                }
            ],
        },
        agents=AGENTS,
        catalogue=CATALOGUE,
        projects=PROJECTS,
    )


async def _conversation(session) -> str:
    conversation = Conversation(id=new_uuid(), user_id=None, channel="web")
    session.add(conversation)
    await session.flush()
    return conversation.id


async def test_project_key_is_written_from_the_validated_plan(session_factory) -> None:
    """C6 §3 / ADR-036 Q2: the column is filled at creation from the plan, which
    is what makes `GET /api/v1/tasks?project_key=…` a query."""
    async with session_factory() as session:
        conversation_id = await _conversation(session)

        task = await create_task(
            session,
            plan=_plan("sunil"),
            conversation_id=conversation_id,
            request_id="req-1",
        )
        await session.commit()

    assert task.project_key == "sunil"
    assert task.assigned_agent == "project_manager"
    assert task.status == TaskStatus.PENDING.value


async def test_a_plan_naming_no_project_leaves_the_column_null(session_factory) -> None:
    """Nullable, deliberately: a plan that names no project must not be given a
    guessed one, or an inference becomes indistinguishable from a fact."""
    async with session_factory() as session:
        conversation_id = await _conversation(session)

        task = await create_task(
            session, plan=_plan(None), conversation_id=conversation_id, request_id="req-1"
        )
        await session.commit()

    assert task.project_key is None


async def test_transitions_never_touch_project_key(session_factory) -> None:
    """Write-once. Every later transition leaves the value alone — there is no
    setter, and this is the test that keeps one from being added."""
    async with session_factory() as session:
        conversation_id = await _conversation(session)
        task = await create_task(
            session, plan=_plan("sunil"), conversation_id=conversation_id, request_id="req-1"
        )

        await transition(session, task, to_status=TaskStatus.IN_PROGRESS)
        await transition(session, task, to_status=TaskStatus.PARKED)
        await transition(session, task, to_status=TaskStatus.COMPLETED)
        await session.commit()

        events = list(
            (
                await session.execute(
                    select(TaskStatusEvent).where(TaskStatusEvent.task_id == task.id)
                )
            ).scalars()
        )
        stored = await session.get(Task, task.id)

    assert stored.project_key == "sunil"
    # Creation + three transitions: a task's history is a record, not an inference.
    assert [event.to_status for event in events] == [
        "pending", "in_progress", "parked", "completed"
    ]
    assert stored.started_at is not None and stored.completed_at is not None


async def test_a_task_cannot_be_created_from_an_unvalidated_plan(session_factory) -> None:
    """Guard site: the task row is what every `tool_calls` row is written
    against, so a raw dict must not be able to mint one."""
    async with session_factory() as session:
        conversation_id = await _conversation(session)

        with pytest.raises(InvalidPlanExecution):
            await create_task(
                session,
                plan={"objective": "not a ValidatedPlan", "agents": ["project_manager"]},
                conversation_id=conversation_id,
                request_id="req-1",
            )
