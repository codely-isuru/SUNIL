"""`run_turn` — one governed turn, and the only place the twelve stages are
emitted for a chat request.

The shape is ARCHITECTURE_V2 §6's L-001 trace with the fakes standing in for the
vendors: owner session → context → memory → model → plan (structured output,
re-validated) → task → agent → tool through the C1 chokepoint → analysis →
envelope, with `audit_events` carrying the whole spine so the turn is
reconstructable from stored records alone (ROADMAP §28).

**Nothing executes without a `ValidatedPlan`.** The provider's constrained decode
is layer 1; `Plan` is layer 3; the registry re-check is layer 4; and
`require_validated_plan` at the execution door is layer 5's enforcement. A turn
whose plan never validates ends with `outcome="failed"`,
`failure.kind="plan_rejected"` and **zero** `tool_calls` rows — a rejected plan
must never execute partially.

**Retries are `detail`, not stages.** Up to three plan attempts and the
provider's retry policy all fold into `llm_io.detail.provider_attempts` /
`plan_created.detail.plan_attempts`, because each of the twelve is emitted at
most once per turn (ADR-023) and `LiveTraceContext` enforces that structurally.

**Model selection is a placeholder for Stream B's router.** `_select_model`
resolves the agent's `preferred_capability` to a gateway alias; when
`core/routing/router.py` lands it replaces the body of that one function, behind
the same `model_selected` stage.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from sunil.core.agent_framework.base import AgentContext, AgentResult, UsageTally
from sunil.core.audit.hooks import DbToolAuditHook
from sunil.core.conversations.gateway import (
    persist_message,
    read_recent_messages,
    touch_conversation,
)
from sunil.core.conversations.resolver import ResolvedConversation
from sunil.core.memory.service import MemoryService, as_prompt_context, memory_scope_for_turn
from sunil.core.orchestrator.plan_schema import build_plan_schema
from sunil.core.orchestrator.plan_validator import (
    MAX_PLAN_ATTEMPTS,
    PlanRejected,
    ToolCatalogue,
    validate_plan,
)
from sunil.core.orchestrator.result import (
    TurnApproval,
    TurnFailure as TurnFailureOut,
    TurnMessage,
    TurnResult,
    TurnTask,
    TurnTraceEntry,
    TurnUsage,
)
from sunil.core.tasks.service import create_task, transition
from sunil.core.trace.context import LiveTraceContext
from sunil.core.trace.stages import TraceStage
from sunil.db.base import new_uuid
from sunil.db.models import LLMCall, LLMPurpose, Plan as PlanRow, TaskStatus
from sunil.providers.base import (
    ChatMessage,
    CompletionRequest,
    PrivacyClass,
    ProviderError,
)
from sunil.redaction import scrub

#: The plan call's schema version, recorded on every `plans` row so a later
#: reader knows which grammar the draft was decoded against.
PLAN_SCHEMA_VERSION = "1.0.0"

#: What the plan call is allowed to spend. Deliberately modest: a plan is a small
#: JSON object, and a large budget here only buys a larger injection surface.
PLAN_MAX_TOKENS = 1024
ANALYSIS_MAX_TOKENS = 2048

#: Capability → gateway alias, until Stream B's router owns this (C2's alias
#: namespace is frozen; see `providers.base.GATEWAY_MODEL_ALIASES`).
_CAPABILITY_MODELS = {
    "general_reasoning": "claude-sonnet",
    "deep_reasoning": "claude-opus",
    "fast": "claude-haiku",
}


class TurnFailed(Exception):
    """A terminal turn outcome that still returns HTTP 200 with
    `outcome="failed"` — the machinery ran and failed visibly (C5 §3)."""

    def __init__(self, kind: str) -> None:
        super().__init__(kind)
        self.kind = kind


@dataclass
class _TurnState:
    request_id: str
    conversation: ResolvedConversation
    lane: str
    user_id: str | None
    channel_label: str | None
    message: str
    usage: UsageTally
    trace: LiveTraceContext
    task: Any = None
    plan: Any = None
    plan_attempts: int = 0
    provider_attempts: int = 0


class GovernedTurnExecutor:
    """The `TurnExecutor` seam's production implementation."""

    def __init__(
        self,
        *,
        sessionmaker: async_sessionmaker[AsyncSession],
        provider: Any,
        memory: MemoryService,
        tool_manager_factory: Any,
        registries: Any,
        catalogue: ToolCatalogue,
        agent: Any,
        turn_deadline_s: float,
    ) -> None:
        self._sessionmaker = sessionmaker
        self._provider = provider
        self._memory = memory
        self._tool_manager_factory = tool_manager_factory
        self._registries = registries
        self._catalogue = catalogue
        self._agent = agent
        self._turn_deadline_s = turn_deadline_s

    async def run(
        self,
        *,
        message: str,
        conversation: ResolvedConversation,
        request_id: str,
        lane: str,
        user_id: str | None,
        channel_label: str | None,
    ) -> TurnResult:
        state = _TurnState(
            request_id=request_id,
            conversation=conversation,
            lane=lane,
            user_id=user_id,
            channel_label=channel_label,
            message=message,
            usage=UsageTally(),
            trace=LiveTraceContext(
                request_id=request_id,
                user_id=user_id,
                conversation_id=conversation.id,
                sessionmaker=self._sessionmaker,
                turn_deadline_s=self._turn_deadline_s,
                # Who advanced the stage — "service" is ADR-035's machine lane,
                # which is exactly the distinction an audit reader needs.
                actor="api" if lane == "cookie" else "service",
            ),
        )

        try:
            return await self._run(state)
        except TurnFailed as failure:
            return await self._fail(state, failure)

    # -- the turn ------------------------------------------------------------ #
    async def _run(self, state: _TurnState) -> TurnResult:
        await state.trace.emit(
            TraceStage.REQUEST_RECEIVED,
            summary="chat turn accepted",
            detail={"lane": state.lane, "channel": state.conversation.channel},
        )

        history = await self._load_context(state)
        await state.trace.emit(
            TraceStage.CONTEXT_LOADED,
            summary="short-term context loaded from messages",
            detail={"messages": len(history)},
        )

        recalled = await self._memory.recall(
            state.message,
            memory_scope_for_turn(
                user_id=state.user_id, conversation_id=state.conversation.id
            ),
        )
        await state.trace.emit(
            TraceStage.MEMORY_RETRIEVED,
            summary="long-term memory recalled",
            detail={
                "items": len(recalled.items),
                "degraded": recalled.degraded,
                "reason": recalled.reason or "none",
            },
        )

        agent_id = self._plan_agent_id()
        model = self._select_model(agent_id)
        privacy = PrivacyClass.INTERNAL
        await state.trace.emit(
            TraceStage.MODEL_SELECTED,
            summary="model resolved for the plan call",
            detail={"model": model, "privacy_class": privacy.value, "agent": agent_id},
        )

        plan = await self._plan(state, agent_id=agent_id, model=model, privacy=privacy)
        state.plan = plan

        async with self._sessionmaker() as session:
            task = await create_task(
                session,
                plan=plan,
                conversation_id=state.conversation.id,
                request_id=state.request_id,
                privacy_level=privacy.value,
            )
            await transition(session, task, to_status=TaskStatus.IN_PROGRESS)
            await session.commit()
            state.task = _TaskView(
                id=task.id, status=task.status, assigned_agent=task.assigned_agent
            )

        await state.trace.emit(
            TraceStage.AGENT_STARTED,
            summary="agent started on the validated plan",
            detail={"agent": state.task.assigned_agent, "steps": len(plan.steps)},
            task_id=state.task.id,
        )

        audit_hook = DbToolAuditHook(self._sessionmaker, validated_plan_id=plan.plan_id)
        result = await self._agent.run(
            plan,
            AgentContext(
                agent_id=state.task.assigned_agent,
                request_id=state.request_id,
                task_id=state.task.id,
                conversation_id=state.conversation.id,
                model=model,
                privacy_class=privacy.value,
                system_prompt=self._system_prompt(state.task.assigned_agent),
                user_message=state.message,
                history=history,
                memory_items=as_prompt_context(recalled.items),
                trace=state.trace,
                tool_manager=self._tool_manager_factory(audit_hook),
                audit_hook=audit_hook,
                provider=self._provider,
                usage=state.usage,
                record_llm_call=self._llm_call_recorder(state, agent_id=state.task.assigned_agent),
                max_tokens=ANALYSIS_MAX_TOKENS,
            ),
        )

        await state.trace.emit(
            TraceStage.AGENT_RESULT,
            summary="agent finished",
            detail={
                "outcome": result.kind,
                "tool_calls": result.tool_calls,
                "executed": result.steps_executed,
            },
            task_id=state.task.id,
        )

        if result.kind == "parked":
            return await self._parked(state, result)
        if result.kind == "tool_failed":
            raise TurnFailed("tool_failed")
        if result.kind == "provider_error":
            raise TurnFailed("provider_error")
        return await self._completed(state, result)

    # -- legs ---------------------------------------------------------------- #
    async def _load_context(self, state: _TurnState) -> list[tuple[str, str]]:
        """Persist the owner's message and read the conversation's recent history.

        The user's own message is persisted and NEVER echoed back in the envelope
        (C5 §1) — the client already has it, and echoing it is how a rendered
        transcript ends up double-printing what the owner typed.
        """
        async with self._sessionmaker() as session:
            await persist_message(
                session,
                conversation_id=state.conversation.id,
                role="user",
                content=state.message,
                request_id=state.request_id,
            )
            await touch_conversation(session, conversation_id=state.conversation.id)
            rows = await read_recent_messages(
                session, conversation_id=state.conversation.id
            )
            history = [(row.role, row.content or "") for row in rows]
            await session.commit()
        return history

    async def _plan(
        self, state: _TurnState, *, agent_id: str, model: str, privacy: PrivacyClass
    ) -> Any:
        """Up to `MAX_PLAN_ATTEMPTS` logical attempts, each a structured-output
        call whose result is re-validated against the registries."""
        schema = build_plan_schema(
            agents=self._registries.agents,
            catalogue=self._catalogue,
            projects=self._registries.projects,
        )
        errors: tuple[str, ...] = ()
        last_error_kind: str | None = None

        for attempt in range(1, MAX_PLAN_ATTEMPTS + 1):
            state.plan_attempts = attempt
            messages = self._plan_messages(state, agent_id=agent_id, errors=errors)
            request = CompletionRequest(
                model=model,
                messages=messages,
                max_tokens=PLAN_MAX_TOKENS,
                agent_id=agent_id,
                request_id=state.request_id,
                privacy_class=privacy,
                # §25: the plan is structured output or it is not a plan.
                json_schema=schema,
            )
            try:
                completion = await self._provider.complete(request)
            except ProviderError as exc:
                state.provider_attempts += 1
                state.usage.add(exc.usage)
                await self._record_llm_call(
                    state,
                    purpose=LLMPurpose.PLAN,
                    agent_id=agent_id,
                    model=model,
                    attempt=attempt,
                    error_kind=exc.kind,
                    result=None,
                )
                last_error_kind = exc.kind
                if not exc.retryable or attempt == MAX_PLAN_ATTEMPTS:
                    await self._emit_llm_io(state, error_kind=exc.kind)
                    raise TurnFailed("provider_error") from exc
                continue

            state.provider_attempts += 1
            state.usage.add(completion.usage)
            await self._record_llm_call(
                state,
                purpose=LLMPurpose.PLAN,
                agent_id=agent_id,
                model=model,
                attempt=attempt,
                error_kind=None,
                result=completion,
            )

            draft = completion.parsed if completion.parsed is not None else _try_json(
                completion.text
            )
            try:
                if draft is None:
                    raise PlanRejected(["the plan call did not return parseable JSON"])
                plan = validate_plan(
                    draft,
                    agents=self._registries.agents,
                    catalogue=self._catalogue,
                    projects=self._registries.projects,
                )
            except PlanRejected as rejected:
                await self._record_plan(state, attempt, draft, rejected.errors)
                errors = rejected.errors
                if attempt == MAX_PLAN_ATTEMPTS:
                    await self._emit_llm_io(state, error_kind=last_error_kind)
                    raise TurnFailed(self._plan_failure_kind(rejected)) from rejected
                continue

            await self._record_plan(state, attempt, draft, ())
            await self._emit_llm_io(state, error_kind=last_error_kind)
            await state.trace.emit(
                TraceStage.PLAN_CREATED,
                summary="plan validated against the registries",
                detail={
                    "plan_attempts": attempt,
                    "steps": len(plan.steps),
                    "project_key": plan.project_key or "none",
                    "intent": plan.intent,
                },
            )
            return plan

        raise TurnFailed("plan_rejected")  # pragma: no cover - loop always returns/raises

    def _plan_failure_kind(self, rejected: PlanRejected) -> str:
        """An unknown project is its own C5 failure kind, because the owner can
        act on it (`known_projects` tells them what IS configured)."""
        if any(error.startswith("unknown project_key") for error in rejected.errors):
            return "unknown_project"
        return "plan_rejected"

    async def _parked(self, state: _TurnState, result: AgentResult) -> TurnResult:
        """ADR-031: the turn ends honestly rather than blocking on a human."""
        async with self._sessionmaker() as session:
            task = await session.get(_task_model(), state.task.id)
            await transition(session, task, to_status=TaskStatus.PARKED)
            await session.commit()
        state.task = _TaskView(
            id=state.task.id,
            status=TaskStatus.PARKED.value,
            assigned_agent=state.task.assigned_agent,
        )
        await state.trace.emit(
            TraceStage.FINAL_RESPONSE,
            summary="turn parked awaiting owner approval",
            detail={"outcome": "parked", "approval": result.approval_id or "none"},
            task_id=state.task.id,
        )
        return TurnResult(
            request_id=state.request_id,
            conversation_id=state.conversation.id,
            outcome="parked",
            approval=TurnApproval(
                approval_id=result.approval_id or "",
                expires_at=result.approval_expires_at or "",
                summary=result.approval_summary or "",
            ),
            task=TurnTask(**vars(state.task)),
            trace=self._trace_entries(state),
            usage=self._usage(state),
        )

    async def _completed(self, state: _TurnState, result: AgentResult) -> TurnResult:
        content = result.content or ""
        async with self._sessionmaker() as session:
            message = await persist_message(
                session,
                conversation_id=state.conversation.id,
                role="assistant",
                content=content,
                request_id=state.request_id,
            )
            task = await session.get(_task_model(), state.task.id)
            await transition(session, task, to_status=TaskStatus.COMPLETED)
            message_out = TurnMessage(
                id=message.id, content=content, created_at=message.created_at.isoformat()
            )
            await session.commit()
        state.task = _TaskView(
            id=state.task.id,
            status=TaskStatus.COMPLETED.value,
            assigned_agent=state.task.assigned_agent,
        )
        await state.trace.emit(
            TraceStage.FINAL_RESPONSE,
            summary="turn completed",
            detail={"outcome": "ok", "tool_calls": result.tool_calls},
            task_id=state.task.id,
        )
        return TurnResult(
            request_id=state.request_id,
            conversation_id=state.conversation.id,
            outcome="ok",
            message=message_out,
            task=TurnTask(**vars(state.task)),
            trace=self._trace_entries(state),
            usage=self._usage(state),
        )

    async def _fail(self, state: _TurnState, failure: TurnFailed) -> TurnResult:
        if state.task is not None:
            async with self._sessionmaker() as session:
                task = await session.get(_task_model(), state.task.id)
                await transition(
                    session, task, to_status=TaskStatus.FAILED, failure_kind=failure.kind
                )
                await session.commit()
            state.task = _TaskView(
                id=state.task.id,
                status=TaskStatus.FAILED.value,
                assigned_agent=state.task.assigned_agent,
            )

        known: tuple[tuple[str, str], ...] | None = None
        if failure.kind == "unknown_project":
            # The owner is told what IS configured, not only that they were wrong.
            known = tuple(
                (key, project.display_name)
                for key, project in self._registries.projects.items()
            )

        await state.trace.emit(
            TraceStage.FINAL_RESPONSE,
            summary="turn failed",
            detail={"outcome": "failed", "failure_kind": failure.kind},
            task_id=state.task.id if state.task is not None else None,
        )
        return TurnResult(
            request_id=state.request_id,
            conversation_id=state.conversation.id,
            outcome="failed",
            failure=TurnFailureOut(kind=failure.kind, known_projects=known),
            task=TurnTask(**vars(state.task)) if state.task is not None else None,
            trace=self._trace_entries(state),
            usage=self._usage(state),
        )

    # -- helpers -------------------------------------------------------------- #
    async def _emit_llm_io(self, state: _TurnState, *, error_kind: str | None) -> None:
        """Stage 5, once per turn. The analysis call that happens later is
        recorded as an `llm_calls` row rather than a second `llm_io` event —
        retries and extra calls belong in `detail` and in sibling records, never
        as a repeated stage (ADR-023)."""
        await state.trace.emit(
            TraceStage.LLM_IO,
            summary="plan call completed",
            detail={
                "provider_attempts": state.provider_attempts,
                "error_kind": error_kind or "none",
                "purpose": "plan",
            },
        )

    def _plan_messages(
        self, state: _TurnState, *, agent_id: str, errors: tuple[str, ...]
    ) -> list[ChatMessage]:
        messages = [
            ChatMessage(role="system", content=self._system_prompt(agent_id)),
            ChatMessage(role="user", content=state.message),
        ]
        if errors:
            # Corrective context for the next bounded attempt: every error at
            # once, because one at a time burns the attempt budget rediscovering
            # the same faults.
            messages.append(
                ChatMessage(
                    role="system",
                    content="the previous plan was rejected: " + "; ".join(errors),
                )
            )
        return messages

    def _system_prompt(self, agent_id: str) -> str:
        agent = self._registries.agents.get(agent_id)
        return getattr(agent, "system_prompt", "") or "You are SUNIL."

    def _plan_agent_id(self) -> str:
        """Which agent's prompt and grants the PLAN call runs under. Single-agent
        for this milestone; the plan itself names the agent that executes it."""
        return "project_manager"

    def _select_model(self, agent_id: str) -> str:
        agent = self._registries.agents.get(agent_id)
        capability = getattr(agent, "preferred_capability", "general_reasoning")
        return _CAPABILITY_MODELS.get(capability, "claude-sonnet")

    def _trace_entries(self, state: _TurnState) -> tuple[TurnTraceEntry, ...]:
        return tuple(
            TurnTraceEntry(stage=stage.value, offset_ms=offset, detail=detail)
            for stage, offset, detail in state.trace.entries
        )

    def _usage(self, state: _TurnState) -> TurnUsage:
        return TurnUsage(
            input_tokens=state.usage.input_tokens,
            output_tokens=state.usage.output_tokens,
            cost_usd=round(state.usage.cost_usd, 6),
        )

    def _llm_call_recorder(self, state: _TurnState, *, agent_id: str) -> Any:
        async def record(
            *, purpose: str, attempt: int, model: str, error_kind: str | None, result: Any
        ) -> None:
            await self._record_llm_call(
                state,
                purpose=LLMPurpose(purpose),
                agent_id=agent_id,
                model=model,
                attempt=attempt,
                error_kind=error_kind,
                result=result,
            )

        return record

    async def _record_llm_call(
        self,
        state: _TurnState,
        *,
        purpose: LLMPurpose,
        agent_id: str,
        model: str,
        attempt: int,
        error_kind: str | None,
        result: Any,
    ) -> None:
        """One row per ATTEMPT, including failures — what makes C5's `usage` a
        query rather than an in-memory tally a failure path can drop."""
        usage = getattr(result, "usage", None)
        async with self._sessionmaker() as session:
            session.add(
                LLMCall(
                    id=new_uuid(),
                    request_id=state.request_id,
                    task_id=state.task.id if state.task is not None else None,
                    agent_id=agent_id,
                    purpose=purpose.value,
                    privacy_class=PrivacyClass.INTERNAL.value,
                    model=model,
                    provider=getattr(self._provider, "name", "unknown"),
                    provider_model=getattr(result, "provider_model", None),
                    attempt=attempt,
                    # Prompts and completions are model I/O: scrubbed before they
                    # are persisted, unconditionally.
                    request_messages=None,
                    request_schema=None,
                    response_text=scrub(result.text) if result is not None else None,
                    response_json=None,
                    finish_reason=getattr(result, "finish_reason", None),
                    input_tokens=usage.input_tokens if usage is not None else 0,
                    output_tokens=usage.output_tokens if usage is not None else 0,
                    cost_micro_usd=int(round(usage.cost_usd * 1_000_000)) if usage else 0,
                    latency_ms=0,
                    error_kind=error_kind,
                )
            )
            await session.commit()

    async def _record_plan(
        self, state: _TurnState, attempt: int, draft: Any, errors: tuple[str, ...]
    ) -> None:
        """Every plan attempt — accepted or rejected — is evidence. The draft is
        model output, so it is scrubbed before it is stored."""
        async with self._sessionmaker() as session:
            session.add(
                PlanRow(
                    id=new_uuid(),
                    request_id=state.request_id,
                    task_id=None,
                    attempt=attempt,
                    schema_version=PLAN_SCHEMA_VERSION,
                    raw_json=scrub(draft) if isinstance(draft, dict) else None,
                    validated=not errors,
                    validation_errors={"errors": list(errors)} if errors else None,
                )
            )
            await session.commit()


@dataclass
class _TaskView:
    """The task fields the envelope reports, detached from the ORM object so no
    lazy load can fire after its session closed."""

    id: str
    status: str
    assigned_agent: str


def _task_model() -> Any:
    from sunil.db.models import Task  # noqa: PLC0415 - local to keep the import graph flat

    return Task


def _try_json(text: str) -> dict[str, Any] | None:
    try:
        loaded = json.loads(text)
    except (ValueError, TypeError):
        return None
    return loaded if isinstance(loaded, dict) else None
