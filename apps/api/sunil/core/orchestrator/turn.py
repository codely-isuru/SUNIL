"""`LiveTurnExecutor` (T11b) — the real `TurnExecutor`, replacing T11a's
`StubTurnExecutor` behind the same Protocol (`sunil.api.routes.chat`).

Owns stages 4 (`model_selected`), 5 (`llm_io`) and 6 (`plan_created`) of
`ARCHITECTURE_V1.md` §3.4, plus the plan-generation retry loop (ADR-000
Q6, §6.2) and the `AgentResult -> TurnResult` mapping. Stages 1-3 and 12
are `handle_chat_turn()`'s (T11a); stages 7-11 are T10's
(`core/agent_framework/runner.py`, `base.py`, and the Project Manager
agent's own `agent_result` emission) — this module calls `run_agent()`
once and lets that machinery own its own trace emissions, per
`ARCHITECTURE_V1.md`'s explicit stage-ownership table (§4.5 A-17).

**Two findings BE-3 proved concretely against T10's real `run_agent()`**
(`tests/unit/api_routes/test_chat_turn_executor_fits_t10.py`), both acted
on here:

1. `run_agent()` needs a `Task` (already created), an `AgentRegistry`, a
   `ModelRouter`, a `ToolManager` and an `agents` mapping — none of which
   `TurnExecutor.run_turn()`'s four call-time parameters carry. They are
   **constructor** dependencies of this class, never per-call arguments —
   the same shape `StubTurnExecutor` already used (stateless there; this
   one holds real collaborators instead).
2. `AgentResult.error_kind` is an open string; `ChatFailure.kind` is a
   four-value `Literal`. `_canonicalise_agent_error_kind()` below is the
   one place that translation happens, so an uncanonicalised value never
   reaches `handle_chat_turn()` and raises a `pydantic.ValidationError`
   there instead of a clean `failed` outcome.

**Task/Workflow are created once, at the very start of a turn — before
plan generation, not after it validates.** `ARCHITECTURE_V1.md`'s stage-6
table reads as though `tasks`/`workflows` are stage 6's own writes, but
QA's exit harness (`test_et8_exhausted_retries_fail_cleanly_with_terminal_
failed_state`) requires a `tasks` row with `status=failed` even when the
turn never gets a validated plan at all (a pure provider exhaustion during
plan generation). FR-065 also cannot describe a `pending -> failed`
transition for a task that was never created. Both are satisfied by
creating the pair up front, with a provisional `objective` (the raw
message) — `assigned_agent` is hard-coded to `"project_manager"` because
M1 has exactly one agent and every plan this turn could produce still
resolves to it (ADR-000 Q2).

**A `StructuredOutputError`-caused `ProviderExhaustedError` during plan
generation is a plan-generation-layer failure (§6.1 Layer 2 — "the
provider never guesses"), not a provider outage**, and is folded into the
bounded plan-attempt retry (`plan_rejected` on exhaustion) rather than
mapped straight to `provider_error` — this is what QA's
`test_et7_non_json_plan_output_yields_zero_tool_calls` actually asserts.
Every *other* `ProviderExhaustedError`/`TurnDeadlineExceeded` raised while
generating a plan ends the turn immediately as `provider_error`: the
Model Router already retried transient failures up to its own bound
(§4.5), so a whole new logical plan-generation attempt would not help and
would only spend more of the §5.3 turn deadline.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from sunil.core.agent_framework.base import Agent
from sunil.core.agent_framework.runner import run_agent
from sunil.core.orchestrator.contracts import TurnResult
from sunil.core.orchestrator.plan_schema import build_plan_schema
from sunil.core.orchestrator.plan_validator import (
    PlanRejected,
    plan_attempts_exhausted,
    validate_plan,
)
from sunil.core.registry.loader import Registries
from sunil.core.registry.projects import UNKNOWN_PROJECT_KEY
from sunil.core.routing.retry import TurnDeadlineExceeded
from sunil.core.routing.router import (
    LLMCallRecorder,
    ModelRouter,
    ProviderAttemptRecord,
    ProviderExhaustedError,
)
from sunil.core.tasks.service import create_task, transition_task_status
from sunil.core.tool_framework.manager import ToolManager
from sunil.core.trace.context import TraceContext
from sunil.core.trace.stages import TraceStage
from sunil.core.workflows.service import create_workflow, transition_workflow_status
from sunil.db.capture import CaptureKind, ContentSource, apply_capture_to_content, resolve_capture
from sunil.db.models import LLMCall, Plan, Task, TaskStatus, Workflow, WorkflowStatus
from sunil.providers.base import ChatTurn, LLMPurpose, LLMRequest, StructuredOutputError
from sunil.redaction import scrub

# The one M1 agent (ADR-000 Q2) -- every validated plan this turn could
# produce resolves to it, so it is safe to fix here rather than read from
# the plan (which does carry an `agents` list, but M1's schema only ever
# admits `["project_manager"]`, checked at layer 4).
_AGENT_ID = "project_manager"

# ARCHITECTURE_V1.md §4.4/§5.1: "the orchestrator's own plan-generation
# call" resolves against the same capability the PM agent's analysis call
# uses. Naming a *capability* here (not a vendor or model) is exactly what
# ADR-003/§33 rule 1 permits.
_PLAN_CAPABILITY = "general_reasoning"

_PLAN_SCHEMA_VERSION = "1"

_PLAN_SYSTEM_PROMPT = (
    "You are SUNIL's orchestrator. Given the owner's message, produce a plan "
    "that identifies which configured project (if any) the owner means, and "
    "what should be done. If no configured project matches, set project_key "
    'to "__unknown__" rather than inventing an identifier. Respond only with '
    "the plan; you do not answer the owner directly."
)

# `ChatFailure.kind`'s four canonical values (§6). `unknown_project` is the
# only `AgentResult.error_kind` that already is one of these (the PM
# agent's own belt-and-suspenders check, `agents/project_manager/agent.py`)
# -- passed through unchanged. Every other `AgentResult.error_kind` reaching
# this point is a tool/agent execution failure by construction: a genuine
# provider-boundary failure propagates as `ProviderExhaustedError`/
# `TurnDeadlineExceeded` instead (caught separately, mapped to
# `provider_error`), never returned as part of an `AgentResult` (FR-104).
_PASSTHROUGH_ERROR_KINDS = frozenset(
    {"provider_error", "tool_failed", "plan_rejected", "unknown_project"}
)


def _canonicalise_agent_error_kind(error_kind: str | None) -> str:
    """`AgentResult.error_kind` (open string, e.g. `"agent_crashed"`,
    `"tool_error"`, `"timeout"`) -> `ChatFailure.kind`'s four-value
    `Literal`. Must run before `TurnResult.failure_kind` is ever handed to
    `handle_chat_turn()` — an uncanonicalised value raises a Pydantic
    `ValidationError` there instead of a clean `failed` outcome (proven by
    `tests/unit/api_routes/test_chat_turn_executor_fits_t10.py`)."""
    if error_kind in _PASSTHROUGH_ERROR_KINDS:
        return error_kind  # type: ignore[return-value]
    return "tool_failed"


class LiveTurnExecutor:
    """The real `TurnExecutor` (satisfies the Protocol structurally, per
    `runtime_checkable`). Constructor-injected collaborators, per-call
    `run_turn()` parameters only as wide as the Protocol demands — see the
    module docstring's first BE-3 finding for why."""

    def __init__(
        self,
        *,
        session: AsyncSession,
        registries: Registries,
        model_router: ModelRouter,
        tool_manager: ToolManager,
        agents: Mapping[str, Agent],
    ) -> None:
        self._session = session
        self._registries = registries
        self._model_router = model_router
        self._tool_manager = tool_manager
        self._agents = agents

    async def run_turn(
        self,
        *,
        request_id: str,
        user_id: str,
        conversation_id: str,
        message: str,
        trace: TraceContext,
    ) -> TurnResult:
        workflow = await create_workflow(
            self._session, owner_user_id=user_id, request_id=request_id
        )
        task = await create_task(
            self._session,
            workflow_id=workflow.id,
            conversation_id=conversation_id,
            request_id=request_id,
            objective=message,
            assigned_agent=_AGENT_ID,
        )

        capability_def = self._registries.models.get_capability(_PLAN_CAPABILITY)
        schema = build_plan_schema(self._registries)

        messages: list[ChatTurn] = [ChatTurn(role="user", content=message)]
        validated_plan = None
        final_response = None
        attempt = 0

        while True:
            attempt += 1
            request = LLMRequest(
                system=_PLAN_SYSTEM_PROMPT,
                messages=messages,
                max_tokens=capability_def.max_tokens,
                json_schema=schema,
            )
            try:
                response = await self._model_router.run(
                    capability=_PLAN_CAPABILITY,
                    request=request,
                    purpose=LLMPurpose.PLAN,
                    ctx=trace,
                    request_id=request_id,
                    task_id=task.id,
                )
            except TurnDeadlineExceeded:
                return await self._fail(
                    task=task, workflow=workflow, failure_kind="provider_error"
                )
            except ProviderExhaustedError as exc:
                if not isinstance(exc.__cause__, StructuredOutputError):
                    # A genuine provider-boundary exhaustion -- not a
                    # plan-generation defect. The Model Router already
                    # retried internally; a whole new logical plan attempt
                    # would not help (module docstring).
                    return await self._fail(
                        task=task, workflow=workflow, failure_kind="provider_error"
                    )
                await self._persist_plan_attempt(
                    request_id=request_id,
                    task_id=task.id,
                    attempt=attempt,
                    raw_json=None,
                    validated=False,
                    errors=[str(exc)],
                )
                if plan_attempts_exhausted(attempt):
                    return await self._fail(
                        task=task, workflow=workflow, failure_kind="plan_rejected"
                    )
                messages = [*messages, _corrective_context_message([str(exc)])]
                continue

            final_response = response
            try:
                validated_plan = validate_plan(response.data or {}, self._registries)
            except PlanRejected as exc:
                await self._persist_plan_attempt(
                    request_id=request_id,
                    task_id=task.id,
                    attempt=attempt,
                    raw_json=response.data,
                    validated=False,
                    errors=list(exc.errors),
                )
                if plan_attempts_exhausted(attempt):
                    await self._emit_plan_generation_stages(
                        trace, response=final_response, task_id=task.id
                    )
                    return await self._fail(
                        task=task, workflow=workflow, failure_kind="plan_rejected"
                    )
                messages = [*messages, _corrective_context_message(list(exc.errors))]
                continue

            await self._persist_plan_attempt(
                request_id=request_id,
                task_id=task.id,
                attempt=attempt,
                raw_json=validated_plan.raw,
                validated=True,
                errors=None,
            )
            break

        await self._emit_plan_generation_stages(trace, response=final_response, task_id=task.id)
        await self._emit_plan_created(
            trace, validated_plan=validated_plan, task_id=task.id, plan_attempts=attempt
        )

        if validated_plan.project_key == UNKNOWN_PROJECT_KEY:
            return await self._fail(
                task=task,
                workflow=workflow,
                failure_kind="unknown_project",
                known_projects=self._registries.projects.known_projects(),
            )

        await transition_task_status(self._session, task, to_status=TaskStatus.IN_PROGRESS.value)
        await transition_workflow_status(
            self._session, workflow, to_status=WorkflowStatus.IN_PROGRESS.value
        )

        try:
            agent_result = await run_agent(
                agent_id=_AGENT_ID,
                plan=validated_plan,
                task=task,
                agents=self._agents,
                agent_registry=self._registries.agents,
                model_router=self._model_router,
                tool_manager=self._tool_manager,
                trace=trace,
            )
        except (ProviderExhaustedError, TurnDeadlineExceeded):
            return await self._fail(
                task=task, workflow=workflow, failure_kind="provider_error"
            )

        if agent_result.ok:
            await transition_task_status(self._session, task, to_status=TaskStatus.COMPLETED.value)
            await transition_workflow_status(
                self._session, workflow, to_status=WorkflowStatus.COMPLETED.value
            )
            return TurnResult(
                outcome="ok",
                failure_kind=None,
                known_projects=None,
                task_id=task.id,
                assistant_content=agent_result.summary,
            )

        canonical_kind = _canonicalise_agent_error_kind(agent_result.error_kind)
        return await self._fail(task=task, workflow=workflow, failure_kind=canonical_kind)

    async def _fail(
        self,
        *,
        task: Task,
        workflow: Workflow,
        failure_kind: str,
        known_projects: list[dict[str, str]] | None = None,
    ) -> TurnResult:
        await transition_task_status(
            self._session, task, to_status=TaskStatus.FAILED.value, failure_kind=failure_kind
        )
        await transition_workflow_status(
            self._session, workflow, to_status=WorkflowStatus.FAILED.value
        )
        return TurnResult(
            outcome="failed",
            failure_kind=failure_kind,
            known_projects=known_projects,
            task_id=task.id,
            assistant_content=None,
        )

    async def _persist_plan_attempt(
        self,
        *,
        request_id: str,
        task_id: str,
        attempt: int,
        raw_json: dict[str, Any] | None,
        validated: bool,
        errors: list[str] | None,
    ) -> Plan:
        decision = resolve_capture(kind=CaptureKind.PLAN, source=ContentSource.SUNIL_GENERATED)
        stored_raw = (
            apply_capture_to_content(decision, scrub(raw_json)) if raw_json is not None else None
        )
        plan = Plan(
            request_id=request_id,
            task_id=task_id,
            attempt=attempt,
            schema_version=_PLAN_SCHEMA_VERSION,
            raw_json=stored_raw,
            validated=validated,
            validation_errors=scrub({"errors": errors}) if errors else None,
            capture_policy=decision.capture_policy.value,
            sensitivity=decision.sensitivity.value,
            retention_class=decision.retention_class.value,
            training_eligible=decision.training_eligible,
        )
        self._session.add(plan)
        await self._session.commit()
        return plan

    async def _emit_plan_generation_stages(
        self, trace: TraceContext, *, response: Any, task_id: str
    ) -> None:
        """Stages 4 (`model_selected`) and 5 (`llm_io`) — emitted exactly
        once per turn (§3.4), tied to whichever provider attempt produced
        the deciding response (the one that either validated or triggered
        final plan-attempt exhaustion)."""
        await trace.emit(
            TraceStage.MODEL_SELECTED,
            summary=(
                f"selected {response.provider}/{response.model} "
                f"for capability {_PLAN_CAPABILITY!r}"
            ),
            detail={
                "capability": _PLAN_CAPABILITY,
                "provider": response.provider,
                "model": response.model,
            },
            task_id=task_id,
        )
        await trace.emit(
            TraceStage.LLM_IO,
            summary="plan-generation call completed",
            detail={
                "purpose": "plan",
                "provider_attempts": response.attempts,
                "input_tokens": response.input_tokens,
                "output_tokens": response.output_tokens,
            },
            task_id=task_id,
        )

    async def _emit_plan_created(
        self, trace: TraceContext, *, validated_plan: Any, task_id: str, plan_attempts: int
    ) -> None:
        project_display_name = (
            self._registries.projects.get(validated_plan.project_key).display_name
            if validated_plan.project_key != UNKNOWN_PROJECT_KEY
            else "an unrecognised project"
        )
        await trace.emit(
            TraceStage.PLAN_CREATED,
            summary=f"plan validated on attempt {plan_attempts}",
            detail={
                "project_key": validated_plan.project_key,
                "project_display_name": project_display_name,
                "agent": _AGENT_ID,
                "plan_attempts": plan_attempts,
            },
            task_id=task_id,
        )


class DatabaseLLMCallRecorder(LLMCallRecorder):
    """The real, DB-writing `LLMCallRecorder` (`core.routing.router`'s own
    injectable seam) — "most naturally T11b, which already persists the
    turn" per that module's docstring.

    Uses its **own** `sessionmaker`, mirroring `ToolManager`'s pattern
    (`core/tool_framework/manager.py`), not the per-request `session`
    `LiveTurnExecutor` holds: the `ModelRouter` this recorder is attached
    to is a per-app singleton (constructed once in `sunil.main`'s
    lifespan, before any request's session exists), so its recorder must
    be constructible then too.
    """

    def __init__(self, *, sessionmaker: async_sessionmaker[AsyncSession]) -> None:
        self._sessionmaker = sessionmaker

    async def record(self, attempt: ProviderAttemptRecord) -> None:
        decision = resolve_capture(
            kind=CaptureKind.LLM_CALL,
            agent_id=attempt.agent_id,
            source=ContentSource.SUNIL_GENERATED,
        )
        request_messages = [
            {"role": turn.role, "content": turn.content} for turn in attempt.request_messages
        ]
        row = LLMCall(
            request_id=attempt.request_id,
            task_id=attempt.task_id,
            agent_id=attempt.agent_id,
            purpose=attempt.purpose.value,
            capability=attempt.capability,
            provider=attempt.provider,
            model=attempt.model,
            attempt=attempt.attempt,
            request_system=apply_capture_to_content(decision, scrub(attempt.request_system)),
            request_messages=apply_capture_to_content(decision, scrub(request_messages)),
            request_schema=attempt.request_schema,
            response_text=apply_capture_to_content(decision, scrub(attempt.response_text)),
            response_json=apply_capture_to_content(decision, scrub(attempt.response_json)),
            stop_reason=attempt.stop_reason,
            input_tokens=attempt.input_tokens,
            output_tokens=attempt.output_tokens,
            cost_micro_usd=attempt.cost_micro_usd,
            pricing_version=attempt.pricing_version,
            latency_ms=attempt.latency_ms,
            error_kind=attempt.error_kind,
            provider_request_id=attempt.provider_request_id,
            capture_policy=decision.capture_policy.value,
            sensitivity=decision.sensitivity.value,
            retention_class=decision.retention_class.value,
            training_eligible=decision.training_eligible,
        )
        async with self._sessionmaker() as session:
            session.add(row)
            await session.commit()


def _corrective_context_message(errors: list[str]) -> ChatTurn:
    """§6.2: "attempts 2 and 3 append the previous validation errors to
    the prompt as corrective context." A plain `user`-role turn — not
    `system` — since it is SUNIL's own generated correction, not new
    input from the owner, but it still belongs in the conversation the
    model sees, exactly where the rejected attempt was."""
    return ChatTurn(
        role="user",
        content=(
            "Your previous plan attempt was rejected for the following reason(s): "
            f"{'; '.join(errors)}. Produce a corrected plan."
        ),
    )
