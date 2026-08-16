"""The agent runner — guard site 2 of ADR-004 Amendment 1's chain, and
the one place `ExecutionMetadata` is minted (from a `ValidatedPlan` and a
`Task`; an agent cannot construct one itself — see
`core/agent_framework/base.py`'s module docstring for the full argument).

`run_agent()` is a **synchronous** function whose first statement is
`require_validated_plan()` — deliberately, so the guard fires the moment
it is *called*, before any `await`. That is what makes
`test_run_agent_rejects_a_non_validated_plan` (T19) able to assert
`pytest.raises(InvalidPlanExecution)` around a bare, un-awaited call. The
actual (async) orchestration work is a separate coroutine this function
returns; real callers `await run_agent(...)`.
"""

from __future__ import annotations

from collections.abc import Coroutine, Mapping
from typing import Any

from sunil.core.agent_framework.base import (
    Agent,
    AgentContext,
    AgentMemory,
    AgentResult,
    NullAgentMemory,
)
from sunil.core.orchestrator.guards import ExecutionMetadata, require_validated_plan
from sunil.core.registry.agents import AgentRegistry
from sunil.core.routing.retry import TurnDeadlineExceeded
from sunil.core.routing.router import ModelRouter, ProviderExhaustedError
from sunil.core.tool_framework.manager import ToolManager
from sunil.core.trace.context import NullTraceContext, TraceContext
from sunil.core.trace.stages import TraceStage
from sunil.db.models import Task
from sunil.logging import get_logger

_logger = get_logger("sunil.agent_framework.runner")


class UnknownAgentImplementationError(Exception):
    """`agent_id` names a real `config/agents.yaml` entry but no Python
    `Agent` implementation was registered for it — a wiring gap, not a
    plan problem."""

    def __init__(self, agent_id: str) -> None:
        self.agent_id = agent_id
        super().__init__(f"no Agent implementation registered for {agent_id!r}")


def run_agent(
    *,
    agent_id: str,
    plan: object,
    task: Task | None = None,
    agents: Mapping[str, Agent] | None = None,
    agent_registry: AgentRegistry | None = None,
    model_router: ModelRouter | None = None,
    tool_manager: ToolManager | None = None,
    memory: AgentMemory | None = None,
    trace: TraceContext | None = None,
) -> Coroutine[Any, Any, AgentResult]:
    """Guard site 2. Raises `InvalidPlanExecution` synchronously if `plan`
    is not a genuine `ValidatedPlan` — before `task`, `agents` or any
    other argument is even inspected. Otherwise returns a coroutine that
    runs the agent; the caller awaits it.
    """
    validated_plan = require_validated_plan(plan)
    return _run_agent(
        agent_id=agent_id,
        validated_plan=validated_plan,
        task=task,
        agents=agents,
        agent_registry=agent_registry,
        model_router=model_router,
        tool_manager=tool_manager,
        memory=memory,
        trace=trace,
    )


async def _run_agent(
    *,
    agent_id: str,
    validated_plan,  # noqa: ANN001 - ValidatedPlan, already guard-checked by the caller
    task: Task | None,
    agents: Mapping[str, Agent] | None,
    agent_registry: AgentRegistry | None,
    model_router: ModelRouter | None,
    tool_manager: ToolManager | None,
    memory: AgentMemory | None,
    trace: TraceContext | None,
) -> AgentResult:
    if (
        task is None
        or agents is None
        or agent_registry is None
        or model_router is None
        or tool_manager is None
    ):
        raise TypeError(
            "run_agent() needs task, agents, agent_registry, model_router and "
            "tool_manager to actually run an agent — only the ValidatedPlan guard "
            "runs without them"
        )

    agent_impl = agents.get(agent_id)
    if agent_impl is None:
        raise UnknownAgentImplementationError(agent_id)
    # Raises UnknownAgentError (T3) if agents.yaml and the agent implementation
    # registry have drifted apart — a wiring bug, surfaced loudly rather than
    # silently falling back to some default configuration.
    agent_definition = agent_registry.get(agent_id)

    active_trace = trace if trace is not None else NullTraceContext(request_id=task.request_id)
    active_memory = memory if memory is not None else NullAgentMemory()

    # The ExecutionMetadata an agent cannot mint itself (Amendment 1 point 3).
    metadata = ExecutionMetadata(
        validated_plan_id=validated_plan.plan_id,
        request_id=active_trace.request_id,
        task_id=task.id,
        agent_id=agent_id,
    )

    await active_trace.emit(
        TraceStage.AGENT_STARTED,
        summary=f"starting agent {agent_id}",
        detail={"objective": validated_plan.objective},
        task_id=task.id,
    )

    ctx = AgentContext(
        agent_definition=agent_definition,
        model_router=model_router,
        tool_manager=tool_manager,
        memory=active_memory,
        trace=active_trace,
        plan=validated_plan,
        metadata=metadata,
        request_id=active_trace.request_id,
        task_id=task.id,
        agent_id=agent_id,
    )

    try:
        return await agent_impl.run(validated_plan, task, ctx)
    except (ProviderExhaustedError, TurnDeadlineExceeded):
        # Genuine provider-boundary failures (§11.3's provider_error outcome)
        # are the orchestrator's (T11b) to classify precisely — turn_deadline_
        # exceeded vs retries_exhausted — so they propagate rather than being
        # flattened into a generic AgentResult here.
        raise
    except Exception:  # noqa: BLE001 - FR-104: an agent bug must not crash the turn
        _logger.exception("agent_run_failed", agent_id=agent_id, task_id=task.id)
        return AgentResult(summary="", tool_calls=[], ok=False, error_kind="agent_crashed")
