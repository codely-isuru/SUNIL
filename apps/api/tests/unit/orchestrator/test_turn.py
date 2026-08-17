"""`sunil.core.orchestrator.turn` (T11b) — the real `TurnExecutor`.

Replaces `StubTurnExecutor` behind the T11a `TurnExecutor` Protocol.
Wraps T9's plan validation chain and T10's `run_agent()`, driven with
test doubles for `ModelRouter`/`ToolManager` (mirroring
`tests/unit/agent_framework/agent_framework_helpers.py`'s own pattern,
proven by BE-3's `test_chat_turn_executor_fits_t10.py`) so these tests
run with no network and no real database beyond the in-memory SQLite
`session`/`user` fixtures every other `api_routes`/`orchestrator` test
package already uses.

Every outcome path in `ARCHITECTURE_V1.md` §11.3 is exercised at least
once: `ok`, `plan_rejected` (registry-check exhaustion and
`StructuredOutputError`-exhaustion), `unknown_project`, `provider_error`
(turn-deadline breach, pure provider exhaustion, and an analysis-call
exhaustion), and `tool_failed` (an `AgentResult.error_kind` canonicalised
from the agent framework's open string).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sunil.api.routes.chat import TurnExecutor
from sunil.core.agent_framework.base import AgentResult
from sunil.core.orchestrator.turn import LiveTurnExecutor
from sunil.core.routing.retry import TurnDeadlineExceeded
from sunil.core.routing.router import ProviderExhaustedError
from sunil.core.trace.context import NullTraceContext
from sunil.core.trace.stages import TraceStage
from sunil.db.models import Plan, Task, User, Workflow
from sunil.providers.base import LLMResponse, ProviderTransientError, StructuredOutputError
from tests.unit.agent_framework.agent_framework_helpers import build_registries

_VALID_PLAN_DICT: dict[str, Any] = {
    "intent": "project_status_review",
    "confidence": 0.9,
    "privacy_level": "internal",
    "objective": "Check on EasyClean Workforce.",
    "project_key": "easy_clean_workforce",
    "agents": ["project_manager"],
    "tools": ["github"],
    "steps": [
        {"id": "s1", "action": "resolve_project", "tool": "none"},
        {"id": "s2", "action": "list_recent_activity", "tool": "github"},
        {"id": "s3", "action": "summarise_activity", "tool": "none"},
    ],
}


def _unregistered_agent_plan_dict() -> dict[str, Any]:
    d = dict(_VALID_PLAN_DICT)
    d["agents"] = ["not_a_real_agent"]
    return d


def _unknown_project_plan_dict() -> dict[str, Any]:
    d = dict(_VALID_PLAN_DICT)
    d["project_key"] = "__unknown__"
    d["steps"] = [{"id": "s1", "action": "resolve_project", "tool": "none"}]
    return d


def _plan_response(data: dict[str, Any], *, attempts: int = 1) -> LLMResponse:
    return LLMResponse(
        text=None,
        data=data,
        provider="anthropic",
        model="claude-sonnet-5",
        input_tokens=120,
        output_tokens=80,
        stop_reason="end_turn",
        provider_request_id="req_fake",
        latency_ms=250,
        attempts=attempts,
    )


@dataclass
class ScriptedModelRouter:
    """A queue of scripted outcomes for `ModelRouter.run()` — pops one per
    call, in order, regardless of `purpose`/`capability`. Each queued item
    is either an `LLMResponse` (returned) or an `Exception` instance
    (raised). Every call is recorded for assertions."""

    script: list[Any] = field(default_factory=list)
    calls: list[dict[str, Any]] = field(default_factory=list)

    async def run(self, **kwargs: Any) -> LLMResponse:
        self.calls.append(kwargs)
        if not self.script:
            raise AssertionError("ScriptedModelRouter.run() called more times than scripted")
        item = self.script.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


@dataclass
class RecordedToolCall:
    tool: str
    operation: str
    params: dict[str, Any]
    meta: object


class FakeToolManager:
    """Mirrors `agent_framework_helpers.FakeToolManager` — no database."""

    def __init__(self, *, result: Any = None) -> None:
        from sunil.core.tool_framework.base import ToolResult

        self.calls: list[RecordedToolCall] = []
        self._result = result or ToolResult(
            ok=True, data={"commits": [], "pull_requests": [], "issues": []}, error_kind=None,
            error_message=None,
        )

    async def execute(self, *, plan, tool, operation, params, meta, trace=None) -> Any:
        self.calls.append(
            RecordedToolCall(tool=tool, operation=operation, params=params, meta=meta)
        )
        return self._result


class _ScriptedAgent:
    """Stands in for `agents/project_manager/agent.py` — the real
    `ProjectManagerAgent` is exercised separately by
    `tests/unit/agents/test_project_manager_agent.py`; this test package
    only needs to prove `turn.py` wires `run_agent()` correctly, which
    means controlling what the agent returns without an LLM."""

    id = "project_manager"

    def __init__(
        self, *, result: AgentResult | None = None, raises: Exception | None = None
    ) -> None:
        self._result = result
        self._raises = raises
        self.called_with: tuple[Any, Any, Any] | None = None

    async def run(self, plan, task, ctx) -> AgentResult:
        self.called_with = (plan, task, ctx)
        if self._raises is not None:
            raise self._raises
        assert self._result is not None
        return self._result


def _executor(
    session: AsyncSession,
    *,
    model_router: ScriptedModelRouter,
    tool_manager: FakeToolManager | None = None,
    agent: _ScriptedAgent | None = None,
) -> LiveTurnExecutor:
    registries = build_registries()
    agents = {"project_manager": agent or _ScriptedAgent()}
    return LiveTurnExecutor(
        session=session,
        registries=registries,
        model_router=model_router,
        tool_manager=tool_manager or FakeToolManager(),
        agents=agents,
    )


async def test_live_turn_executor_satisfies_the_turn_executor_protocol(
    session: AsyncSession,
) -> None:
    executor = _executor(session, model_router=ScriptedModelRouter())
    assert isinstance(executor, TurnExecutor)


async def test_a_fully_successful_turn_returns_ok_and_the_agents_summary(
    session: AsyncSession, user: User
) -> None:
    router = ScriptedModelRouter(script=[_plan_response(_VALID_PLAN_DICT)])
    agent = _ScriptedAgent(
        result=AgentResult(
            summary="All quiet on EasyClean Workforce.",
            tool_calls=["list_recent_activity"],
            ok=True,
            error_kind=None,
        )
    )
    executor = _executor(session, model_router=router, agent=agent)
    trace = NullTraceContext(request_id="req-1")

    result = await executor.run_turn(
        request_id="req-1",
        user_id=user.id,
        conversation_id="conv-1",
        message="Check on EasyClean Workforce",
        trace=trace,
    )

    assert result.outcome == "ok"
    assert result.failure_kind is None
    assert result.assistant_content == "All quiet on EasyClean Workforce."
    assert result.task_id is not None

    task = await session.get(Task, result.task_id)
    assert task is not None
    assert task.status == "completed"
    assert task.assigned_agent == "project_manager"

    workflow_result = await session.execute(select(Workflow).where(Workflow.request_id == "req-1"))
    workflow = workflow_result.scalar_one()
    assert workflow.status in ("completed", "in_progress")

    plans_result = await session.execute(select(Plan).where(Plan.request_id == "req-1"))
    plans = list(plans_result.scalars().all())
    assert len(plans) == 1
    assert plans[0].validated is True
    assert plans[0].task_id == task.id
    raw = plans[0].raw_json
    stored = json.loads(raw) if isinstance(raw, str) else raw
    required_keys = (
        "intent",
        "confidence",
        "privacy_level",
        "objective",
        "project_key",
        "agents",
        "tools",
        "steps",
    )
    for key in required_keys:
        assert key in stored

    # The agent was actually invoked with the real, minted ValidatedPlan and Task.
    assert agent.called_with is not None
    called_plan, called_task, _ctx = agent.called_with
    assert called_plan.project_key == "easy_clean_workforce"
    assert called_task.id == task.id

    # `run_agent()` here is the real T10 implementation (only the model
    # router/tool manager/agent are fakes), so it emits its own real
    # `agent_started` (stage 7) -- the `_ScriptedAgent` double itself never
    # calls `ctx.trace.emit()`, unlike the real `ProjectManagerAgent`
    # (stage 11), so the trace stops at stage 7 in this unit test.
    stages = [stage for stage, _summary, _detail, _task_id in trace.emitted]
    assert stages == [
        TraceStage.MODEL_SELECTED,
        TraceStage.LLM_IO,
        TraceStage.PLAN_CREATED,
        TraceStage.AGENT_STARTED,
    ]
    model_selected_detail = trace.emitted[0][2]
    assert model_selected_detail == {
        "capability": "general_reasoning",
        "provider": "anthropic",
        "model": "claude-sonnet-5",
    }
    llm_io_detail = trace.emitted[1][2]
    assert llm_io_detail["purpose"] == "plan"
    assert llm_io_detail["provider_attempts"] == 1
    plan_created_detail = trace.emitted[2][2]
    assert plan_created_detail["project_key"] == "easy_clean_workforce"
    assert plan_created_detail["agent"] == "project_manager"
    assert plan_created_detail["plan_attempts"] == 1


async def test_an_unregistered_agent_plan_exhausts_retries_and_yields_plan_rejected(
    session: AsyncSession, user: User
) -> None:
    # The same invalid draft every attempt -- exercises exhaustion (ET-7's
    # own documented pattern), not a lucky first-attempt reject.
    router = ScriptedModelRouter(
        script=[_plan_response(_unregistered_agent_plan_dict()) for _ in range(3)]
    )
    executor = _executor(session, model_router=router)
    trace = NullTraceContext(request_id="req-2")

    result = await executor.run_turn(
        request_id="req-2",
        user_id=user.id,
        conversation_id="conv-2",
        message="Check on EasyClean Workforce",
        trace=trace,
    )

    assert result.outcome == "failed"
    assert result.failure_kind == "plan_rejected"
    assert result.assistant_content is None

    plans_result = await session.execute(select(Plan).where(Plan.request_id == "req-2"))
    plans = list(plans_result.scalars().all())
    assert len(plans) == 3
    assert all(p.validated is False for p in plans)

    task = await session.get(Task, result.task_id)
    assert task is not None
    assert task.status == "failed"
    assert task.failure_kind == "plan_rejected"

    # No tool call ever happened (FR-061/ET-7).
    assert len(router.calls) == 3


async def test_structured_output_failure_on_every_attempt_also_yields_plan_rejected(
    session: AsyncSession, user: User
) -> None:
    """Layer 2 ('the provider never guesses') failing is a plan-generation
    defect, not a provider outage -- it must exhaust the bounded plan-attempt
    budget and return `plan_rejected`, matching QA's
    `test_et7_non_json_plan_output_yields_zero_tool_calls`, never
    `provider_error`."""

    def _exhausted_from_structured_output_error() -> ProviderExhaustedError:
        cause = StructuredOutputError("not valid JSON")
        exc = ProviderExhaustedError("structured output failure")
        exc.__cause__ = cause
        return exc

    router = ScriptedModelRouter(
        script=[_exhausted_from_structured_output_error() for _ in range(3)]
    )
    executor = _executor(session, model_router=router)
    trace = NullTraceContext(request_id="req-3")

    result = await executor.run_turn(
        request_id="req-3",
        user_id=user.id,
        conversation_id="conv-3",
        message="Check on EasyClean Workforce",
        trace=trace,
    )

    assert result.outcome == "failed"
    assert result.failure_kind == "plan_rejected"

    plans_result = await session.execute(select(Plan).where(Plan.request_id == "req-3"))
    plans = list(plans_result.scalars().all())
    assert len(plans) == 3
    assert all(p.validated is False for p in plans)
    assert len(router.calls) == 3


async def test_a_pure_provider_exhaustion_during_plan_generation_yields_provider_error_immediately(
    session: AsyncSession, user: User
) -> None:
    """A genuine provider-boundary exhaustion (every attempt transient) is
    not a plan-generation defect -- it ends the turn immediately, with no
    whole-new-plan-attempt retry (ADR-000 Q6's bounded retry is about
    validation failures, not provider outages, which the Model Router
    already retried internally up to its own bound)."""
    cause = ProviderTransientError("503 from upstream")
    exc = ProviderExhaustedError("3 provider attempts exhausted")
    exc.__cause__ = cause
    router = ScriptedModelRouter(script=[exc])
    executor = _executor(session, model_router=router)
    trace = NullTraceContext(request_id="req-4")

    result = await executor.run_turn(
        request_id="req-4",
        user_id=user.id,
        conversation_id="conv-4",
        message="Check on EasyClean Workforce",
        trace=trace,
    )

    assert result.outcome == "failed"
    assert result.failure_kind == "provider_error"
    assert len(router.calls) == 1  # no whole-new-plan-attempt retry

    task = await session.get(Task, result.task_id)
    assert task is not None
    assert task.status == "failed"
    assert task.failure_kind == "provider_error"


async def test_a_turn_deadline_breach_during_plan_generation_yields_provider_error(
    session: AsyncSession, user: User
) -> None:
    router = ScriptedModelRouter(script=[TurnDeadlineExceeded(remaining_s=0.0, needed_s=20.0)])
    executor = _executor(session, model_router=router)
    trace = NullTraceContext(request_id="req-5")

    result = await executor.run_turn(
        request_id="req-5",
        user_id=user.id,
        conversation_id="conv-5",
        message="Check on EasyClean Workforce",
        trace=trace,
    )

    assert result.outcome == "failed"
    assert result.failure_kind == "provider_error"


async def test_an_unknown_project_plan_yields_unknown_project_with_known_projects_and_no_agent_call(
    session: AsyncSession, user: User
) -> None:
    router = ScriptedModelRouter(script=[_plan_response(_unknown_project_plan_dict())])
    agent = _ScriptedAgent()
    executor = _executor(session, model_router=router, agent=agent)
    trace = NullTraceContext(request_id="req-6")

    result = await executor.run_turn(
        request_id="req-6",
        user_id=user.id,
        conversation_id="conv-6",
        message="Check project some-unconfigured-project",
        trace=trace,
    )

    assert result.outcome == "failed"
    assert result.failure_kind == "unknown_project"
    assert result.known_projects
    keys = {p["key"] for p in result.known_projects}
    assert "easy_clean_workforce" in keys

    # The agent was never invoked (T11b intercepts unknown_project before
    # ever reaching run_agent(), per agents/project_manager/agent.py's own
    # docstring expectation).
    assert agent.called_with is None

    task = await session.get(Task, result.task_id)
    assert task is not None
    assert task.status == "failed"
    assert task.failure_kind == "unknown_project"


async def test_an_agent_side_tool_failure_is_canonicalised_to_tool_failed(
    session: AsyncSession, user: User
) -> None:
    router = ScriptedModelRouter(script=[_plan_response(_VALID_PLAN_DICT)])
    agent = _ScriptedAgent(
        result=AgentResult(summary="", tool_calls=[], ok=False, error_kind="agent_crashed")
    )
    executor = _executor(session, model_router=router, agent=agent)
    trace = NullTraceContext(request_id="req-7")

    result = await executor.run_turn(
        request_id="req-7",
        user_id=user.id,
        conversation_id="conv-7",
        message="Check on EasyClean Workforce",
        trace=trace,
    )

    assert result.outcome == "failed"
    assert result.failure_kind == "tool_failed"  # canonicalised, not "agent_crashed"
    assert result.assistant_content is None

    task = await session.get(Task, result.task_id)
    assert task is not None
    assert task.status == "failed"
    assert task.failure_kind == "tool_failed"


async def test_a_provider_exhaustion_during_the_analysis_call_yields_provider_error(
    session: AsyncSession, user: User
) -> None:
    """`run_agent()` re-raises `ProviderExhaustedError`/`TurnDeadlineExceeded`
    from the agent's own analysis call rather than flattening them (T10's
    own documented contract) -- the orchestrator must classify them."""
    router = ScriptedModelRouter(script=[_plan_response(_VALID_PLAN_DICT)])
    agent = _ScriptedAgent(raises=ProviderExhaustedError("exhausted during analysis"))
    executor = _executor(session, model_router=router, agent=agent)
    trace = NullTraceContext(request_id="req-8")

    result = await executor.run_turn(
        request_id="req-8",
        user_id=user.id,
        conversation_id="conv-8",
        message="Check on EasyClean Workforce",
        trace=trace,
    )

    assert result.outcome == "failed"
    assert result.failure_kind == "provider_error"

    task = await session.get(Task, result.task_id)
    assert task is not None
    assert task.status == "failed"


async def test_a_malformed_plan_never_produces_a_tool_call(
    session: AsyncSession, user: User
) -> None:
    router = ScriptedModelRouter(
        script=[_plan_response(_unregistered_agent_plan_dict()) for _ in range(3)]
    )
    tool_manager = FakeToolManager()
    executor = _executor(session, model_router=router, tool_manager=tool_manager)
    trace = NullTraceContext(request_id="req-9")

    await executor.run_turn(
        request_id="req-9",
        user_id=user.id,
        conversation_id="conv-9",
        message="Check on EasyClean Workforce",
        trace=trace,
    )

    assert tool_manager.calls == []
