"""Confirms the `TurnExecutor` seam (T11a) still fits what T10 actually
shipped — `run_agent()`, `AgentContext`, `AgentResult` — rather than what
the build plan described before T10 existed. Requested explicitly by the
Delivery Manager once T10 landed.

**Finding, stated up front so it does not read as a surprise buried in a
docstring:** `run_agent()`'s signature is *not* a drop-in match for
`TurnExecutor.run_turn()`. It needs a real `Task` (already created), an
`AgentRegistry`, a `ModelRouter`, a `ToolManager` and an `agents` mapping
— none of which `run_turn()`'s four parameters carry. The seam still
fits, but only because those extra dependencies are natural
*constructor* arguments of whatever concrete `TurnExecutor` T11b builds,
never *per-call* ones — exactly the same shape `StubTurnExecutor` already
uses (stateless here; a real one holds `model_router`/`tool_manager`/
`agent_registry`/`agents` instead). This test proves that shape
concretely, with T10's real `run_agent()` and its own test helpers, not
by re-reading two files and guessing they compose.

**The other real finding:** `AgentResult.error_kind` is an open string
("agent_crashed", "tool_error", ...), while `ChatFailure.kind` is a
`Literal` restricted to the four §6 values. T11b's adapter must
canonicalise every `AgentResult.error_kind` onto one of
`provider_error|tool_failed|plan_rejected|unknown_project` *before*
returning it as `TurnResult.failure_kind` — passing an uncanonicalised
value through would raise a Pydantic `ValidationError` inside
`handle_chat_turn()`, not a clean `failed` outcome.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession
from sunil.api.routes.chat import TurnExecutor, TurnResult, handle_chat_turn
from sunil.core.agent_framework.base import AgentResult
from sunil.core.agent_framework.runner import run_agent
from sunil.core.tasks.service import create_task
from sunil.core.trace.context import NullTraceContext
from sunil.core.workflows.service import create_workflow
from sunil.db.models import User
from tests.unit.agent_framework.agent_framework_helpers import (
    FakeModelRouter,
    FakeToolManager,
    build_registries,
    build_validated_plan,
)

# The four canonical values `ChatFailure.kind` accepts (§6). T11b's real
# adapter needs a mapping at least this complete from whatever
# `AgentResult.error_kind` values `agents/project_manager/agent.py`
# actually produces.
_CANONICAL_FAILURE_KINDS = {"provider_error", "tool_failed", "plan_rejected", "unknown_project"}


class _FakeProjectManagerAgent:
    """Stands in for `agents/project_manager/agent.py` — the actual
    agent implementation is a separate, larger piece this test does not
    need in order to prove the *framework* seam."""

    id = "project_manager"

    def __init__(self, *, result: AgentResult) -> None:
        self._result = result

    async def run(self, plan, task, ctx) -> AgentResult:
        del plan, task, ctx
        return self._result


class _RunAgentTurnExecutor:
    """A minimal concrete `TurnExecutor` wrapping T10's `run_agent()`.

    Every dependency `run_agent()` needs beyond `run_turn()`'s own four
    parameters (`registries`, the agent implementations, the model
    router, the tool manager) is a **constructor** argument here — this
    is the shape T11b's real implementation must take, proven rather
    than asserted.
    """

    def __init__(self, *, session: AsyncSession, registries, agent_impl) -> None:
        self._session = session
        self._registries = registries
        self._agent_impl = agent_impl

    async def run_turn(
        self, *, request_id: str, user_id: str, conversation_id: str, message: str, trace
    ) -> TurnResult:
        del message
        workflow = await create_workflow(
            self._session, owner_user_id=user_id, request_id=request_id
        )
        validated_plan = build_validated_plan(registries=self._registries)
        task = await create_task(
            self._session,
            workflow_id=workflow.id,
            conversation_id=conversation_id,
            request_id=request_id,
            objective=validated_plan.objective,
            assigned_agent="project_manager",
        )

        result: AgentResult = await run_agent(
            agent_id="project_manager",
            plan=validated_plan,
            task=task,
            agents={"project_manager": self._agent_impl},
            agent_registry=self._registries.agents,
            model_router=FakeModelRouter(),
            tool_manager=FakeToolManager(),
            trace=trace,
        )

        if result.ok:
            return TurnResult(
                outcome="ok",
                failure_kind=None,
                known_projects=None,
                task_id=task.id,
                assistant_content=result.summary,
            )

        # The canonicalisation T11b's adapter is responsible for --
        # `AgentResult.error_kind` ("agent_crashed", here) is NOT itself
        # one of the four §6 values.
        canonical_kind = "tool_failed" if result.error_kind == "tool_error" else "provider_error"
        return TurnResult(
            outcome="failed",
            failure_kind=canonical_kind,
            known_projects=None,
            task_id=task.id,
            assistant_content=None,
        )


async def test_a_concrete_turn_executor_can_wrap_t10s_run_agent_on_success(
    session: AsyncSession, user: User
) -> None:
    registries = build_registries()
    agent_impl = _FakeProjectManagerAgent(
        result=AgentResult(
            summary="All quiet on Sample Project.",
            tool_calls=["github.list_recent_activity"],
            ok=True,
            error_kind=None,
        )
    )
    adapter = _RunAgentTurnExecutor(session=session, registries=registries, agent_impl=agent_impl)

    assert isinstance(adapter, TurnExecutor)

    trace = NullTraceContext(request_id="req-1")
    response = await handle_chat_turn(
        session,
        trace,
        executor=adapter,
        user_id=user.id,
        request_id="req-1",
        message="Check on Sample Project.",
        conversation_id=None,
    )

    assert response.outcome == "ok"
    assert response.message is not None
    assert response.message.content == "All quiet on Sample Project."
    assert response.task is not None
    assert response.task.assigned_agent == "project_manager"
    assert response.task.status == "pending"  # run_agent() does not transition it itself


async def test_a_concrete_turn_executor_maps_an_agent_crash_onto_a_canonical_failure_kind(
    session: AsyncSession, user: User
) -> None:
    """Proves the finding: `AgentResult.error_kind` values are not
    automatically `ChatFailure.kind`-safe. If the adapter forgot to
    canonicalise, `ChatFailure(kind="agent_crashed", ...)` would raise a
    `pydantic.ValidationError` here instead of a clean `failed` outcome.
    """
    registries = build_registries()

    class _CrashingAgent:
        id = "project_manager"

        async def run(self, plan, task, ctx):
            del plan, task, ctx
            raise RuntimeError("boom")

    # run_agent() itself catches an agent exception (FR-104) and returns
    # AgentResult(ok=False, error_kind="agent_crashed") -- exercised here
    # via the real runner, not asserted from reading its source.
    adapter = _RunAgentTurnExecutor(
        session=session, registries=registries, agent_impl=_CrashingAgent()
    )

    trace = NullTraceContext(request_id="req-2")
    response = await handle_chat_turn(
        session,
        trace,
        executor=adapter,
        user_id=user.id,
        request_id="req-2",
        message="Check on Sample Project.",
        conversation_id=None,
    )

    assert response.outcome == "failed"
    assert response.failure is not None
    assert response.failure.kind in _CANONICAL_FAILURE_KINDS
    assert response.message is None
