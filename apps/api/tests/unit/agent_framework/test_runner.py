"""`sunil.core.agent_framework.runner.run_agent` — guard site 2 (ADR-004
Amendment 1) and the one place `ExecutionMetadata` is minted.
"""

from __future__ import annotations

import inspect

import pytest
from sunil.core.agent_framework.base import AgentContext, AgentResult
from sunil.core.agent_framework.runner import UnknownAgentImplementationError, run_agent
from sunil.core.orchestrator.guards import InvalidPlanExecution
from sunil.core.routing.retry import TurnDeadlineExceeded
from sunil.core.routing.router import ProviderExhaustedError

from .agent_framework_helpers import (
    FakeModelRouter,
    FakeToolManager,
    FakeTraceContext,
    build_registries,
    build_task,
    build_validated_plan,
)


class _RecordingAgent:
    """A fake `Agent` that records the arguments it was invoked with, and
    returns (or raises) whatever the test configured."""

    id = "project_manager"

    def __init__(self, *, result: AgentResult | None = None, to_raise: Exception | None = None):
        self.calls: list[tuple[object, object, AgentContext]] = []
        self._result = result or AgentResult(summary="ok", tool_calls=[], ok=True, error_kind=None)
        self._to_raise = to_raise

    async def run(self, plan, task, ctx: AgentContext) -> AgentResult:
        self.calls.append((plan, task, ctx))
        if self._to_raise is not None:
            raise self._to_raise
        return self._result


def test_run_agent_rejects_a_non_validated_plan_synchronously() -> None:
    """Guard site 2. The guard must fire on the bare *call*, before any
    `await` — this is what T19's own
    `test_run_agent_rejects_a_non_validated_plan` exercises, calling this
    function with no other arguments at all."""
    with pytest.raises(InvalidPlanExecution):
        run_agent(agent_id="project_manager", plan={"not": "a ValidatedPlan"})


def test_run_agent_returns_a_coroutine_when_the_plan_is_valid() -> None:
    """The guard passes synchronously; the actual work is a coroutine the
    caller must await — proven by never awaiting it here."""
    plan = build_validated_plan()

    result = run_agent(agent_id="project_manager", plan=plan)

    assert inspect.iscoroutine(result)
    result.close()  # never awaited — silence the "never awaited" warning


async def test_run_agent_raises_typeerror_when_required_dependencies_are_missing() -> None:
    plan = build_validated_plan()

    with pytest.raises(TypeError):
        await run_agent(agent_id="project_manager", plan=plan)


async def test_run_agent_mints_execution_metadata_from_the_plan_and_task() -> None:
    plan = build_validated_plan()
    task = build_task()
    agent = _RecordingAgent()
    registries = build_registries()

    await run_agent(
        agent_id="project_manager",
        plan=plan,
        task=task,
        agents={"project_manager": agent},
        agent_registry=registries.agents,
        model_router=FakeModelRouter(),
        tool_manager=FakeToolManager(),
        trace=FakeTraceContext(request_id=task.request_id),
    )

    assert len(agent.calls) == 1
    _plan_arg, task_arg, ctx = agent.calls[0]
    assert task_arg is task
    # The metadata itself is not exposed by AgentContext (by design) — the
    # only way to observe it is through what call_tool() actually sends,
    # covered by test_agent_context.py. Here we only prove the agent
    # actually ran with the real task/plan.
    assert isinstance(ctx, AgentContext)


async def test_run_agent_emits_the_agent_started_stage() -> None:
    from sunil.core.trace.stages import TraceStage

    plan = build_validated_plan()
    task = build_task()
    trace = FakeTraceContext(request_id=task.request_id)
    registries = build_registries()

    await run_agent(
        agent_id="project_manager",
        plan=plan,
        task=task,
        agents={"project_manager": _RecordingAgent()},
        agent_registry=registries.agents,
        model_router=FakeModelRouter(),
        tool_manager=FakeToolManager(),
        trace=trace,
    )

    stages = [e[0] for e in trace.emitted]
    assert TraceStage.AGENT_STARTED in stages


async def test_run_agent_raises_for_an_unregistered_agent_implementation() -> None:
    plan = build_validated_plan()
    task = build_task()
    registries = build_registries()

    with pytest.raises(UnknownAgentImplementationError):
        await run_agent(
            agent_id="project_manager",
            plan=plan,
            task=task,
            agents={},  # nothing registered
            agent_registry=registries.agents,
            model_router=FakeModelRouter(),
            tool_manager=FakeToolManager(),
        )


async def test_run_agent_converts_an_agent_crash_into_a_failed_agent_result() -> None:
    """FR-104: an agent bug must not crash the turn."""
    plan = build_validated_plan()
    task = build_task()
    registries = build_registries()
    agent = _RecordingAgent(to_raise=ValueError("boom"))

    result = await run_agent(
        agent_id="project_manager",
        plan=plan,
        task=task,
        agents={"project_manager": agent},
        agent_registry=registries.agents,
        model_router=FakeModelRouter(),
        tool_manager=FakeToolManager(),
    )

    assert result.ok is False
    assert result.error_kind == "agent_crashed"


@pytest.mark.parametrize(
    "exc", [ProviderExhaustedError("boom"), TurnDeadlineExceeded(remaining_s=1, needed_s=5)]
)
async def test_run_agent_lets_provider_boundary_exceptions_propagate(exc: Exception) -> None:
    """These map to the precise `provider_error` outcome/`error_kind` at
    T11b — flattening them into a generic AgentResult here would lose that
    precision."""
    plan = build_validated_plan()
    task = build_task()
    registries = build_registries()
    agent = _RecordingAgent(to_raise=exc)

    with pytest.raises(type(exc)):
        await run_agent(
            agent_id="project_manager",
            plan=plan,
            task=task,
            agents={"project_manager": agent},
            agent_registry=registries.agents,
            model_router=FakeModelRouter(),
            tool_manager=FakeToolManager(),
        )
