"""`POST /api/v1/chat` — the frozen §6 contract's turn endpoint (T11a).

The `TurnExecutor` Protocol, its stub, and the response-shaping helpers
have no dependency on how the app is wired
(`ARCHITECTURE_V1.md` §2 T11a: "the turn executor is behind a Protocol
with a stub implementation ... so the endpoint is real, testable and
integrable before T11b exists") — `handle_chat_turn()` takes an
already-constructed `session`/`trace` and knows nothing about FastAPI.
The `@router.post` handler below is the thin wrapper wired onto BE-1's
ADR-018 shape: `Depends(get_session)` (which itself reads
`request.app.state.sessionmaker`) for the session, and
`request.app.state.{sessionmaker,settings}` directly for the
`LiveTraceContext` `handle_chat_turn()` needs a sessionmaker (not a
session) to construct — the same per-application state ADR-018
established, never a module-level cache.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from sunil.api.deps import require_client_header, require_owner_session
from sunil.api.schemas import (
    ChatFailure,
    ChatRequest,
    ChatResponse,
    ChatTaskOut,
    ChatUsage,
    MessageOut,
    ProjectSummary,
    TraceEntryOut,
)
from sunil.core.conversations.gateway import (
    UnknownConversationError,
    get_or_create_conversation,
    persist_message,
)
from sunil.core.memory.short_term import read_recent_messages, record_short_term_memory_retrieval
from sunil.core.trace.context import LiveTraceContext, TraceContext
from sunil.core.trace.stages import TraceStage
from sunil.db.models import AuditEvent, LLMCall, Task
from sunil.db.session import get_session


@dataclass(frozen=True)
class TurnResult:
    """What a `TurnExecutor` returns — the orchestration outcome the
    chat route maps onto the frozen §6 envelope's `outcome`/`failure`/
    `task`/`message` fields. Carries no trace or usage data itself: those
    come from `audit_events`/`llm_calls`, read back by the route after
    the executor returns (§8.1's own "reconstructable from logs alone").
    """

    outcome: str  # "ok" | "failed" -- §6's own two values
    failure_kind: str | None
    known_projects: list[dict[str, str]] | None
    task_id: str | None
    assistant_content: str | None


@runtime_checkable
class TurnExecutor(Protocol):
    """Stages 4-11 of `ARCHITECTURE_V1.md` §3.4, behind one seam.

    `@runtime_checkable` here is not a security boundary the way it would
    be on `ValidatedPlan` or `ExecutionMetadata` — nothing ever chooses an
    executor by `isinstance()`-checking untrusted input; the concrete
    executor is wired once, by trusted code, at construction time. Unlike
    those two, making this Protocol duck-typeable costs nothing, so it is
    left on for testability.

    **Verified against what T10 actually shipped** (`core/agent_framework
    /runner.run_agent()`), not against the build plan's description of it,
    per `tests/unit/api_routes/test_chat_turn_executor_fits_t10.py`:
    `run_agent()` needs a real `Task` (already created), an
    `AgentRegistry`, a `ModelRouter`, a `ToolManager` and an `agents`
    mapping — none of which `run_turn()`'s four parameters carry. The
    seam still fits, proven concretely with T10's real runner, but only
    because a concrete `TurnExecutor` holds those as **constructor**
    dependencies (this Protocol's four call-time parameters are enough to
    drive it) and internally does the planning + Task/Workflow creation +
    `run_agent()` call + `AgentResult -> TurnResult` mapping.

    **The one place that mapping needs care:** `AgentResult.error_kind`
    is an open string (e.g. `"agent_crashed"`); `ChatFailure.kind` is a
    `Literal` of exactly the four §6 values. Whatever builds the real
    `TurnResult` must canonicalise every `AgentResult.error_kind` onto
    `provider_error|tool_failed|plan_rejected|unknown_project` before
    returning it — an uncanonicalised value fails as a Pydantic
    `ValidationError` inside `handle_chat_turn()`, not as a clean `failed`
    outcome.
    """

    async def run_turn(
        self,
        *,
        request_id: str,
        user_id: str,
        conversation_id: str,
        message: str,
        trace: TraceContext,
    ) -> TurnResult: ...


class StubTurnExecutor:
    """The T11a stub: every turn is `plan_rejected`, unconditionally.

    This is what lets `POST /api/v1/chat` exist, be routed, be
    authenticated and be integration-tested *before* T9's validator and
    T10's agent runner are wired into a real pipeline (T11b). Replacing
    `_TURN_EXECUTOR` below with a real, constructor-injected
    `TurnExecutor` is what T11b needs to do in *this* file; the adapter
    class itself — wrapping `run_agent()` plus planning and Task/Workflow
    creation — is new code T11b writes, not a one-line swap (see
    `TurnExecutor`'s own docstring for the verified shape it needs).
    """

    async def run_turn(
        self,
        *,
        request_id: str,
        user_id: str,
        conversation_id: str,
        message: str,
        trace: TraceContext,
    ) -> TurnResult:
        del request_id, user_id, conversation_id, message, trace
        return TurnResult(
            outcome="failed",
            failure_kind="plan_rejected",
            known_projects=None,
            task_id=None,
            assistant_content=None,
        )


# ---------------------------------------------------------------------------
# Readback helpers -- §8.1's own canonical query, run at the end of a turn
# to build the response's `trace[]`/`usage`. These read `audit_events` and
# `llm_calls` directly rather than trusting an in-memory `TraceContext`,
# because "reconstructable from logs alone" (§8.1) is the actual claim ET-6
# is graded on, and the database is what a debugging session and
# `GET /api/v1/trace/{request_id}` (T13, optional) would both read too.
# ---------------------------------------------------------------------------


async def read_trace_entries(session: AsyncSession, *, request_id: str) -> list[TraceEntryOut]:
    """`trace[]` — every `audit_events` row for `request_id`, in `seq`
    order, with `offset_ms` computed relative to the first row's own
    timestamp (there is no separate "turn start" record; the first stage,
    `message_received`, is the turn's own start)."""
    result = await session.execute(
        select(AuditEvent).where(AuditEvent.request_id == request_id).order_by(AuditEvent.seq)
    )
    rows = list(result.scalars().all())
    if not rows:
        return []

    start_at = rows[0].at
    return [
        TraceEntryOut(
            stage=row.stage,
            offset_ms=int((row.at - start_at).total_seconds() * 1000),
            detail=row.detail,
        )
        for row in rows
    ]


async def read_usage(session: AsyncSession, *, request_id: str) -> ChatUsage:
    """`usage` — summed across **every provider attempt** in the turn
    (§6; A-2), including failed ones that consumed input tokens. Zero
    for a turn with no `llm_calls` rows at all (the stub's `plan_
    rejected` path never reaches the Model Router)."""
    result = await session.execute(select(LLMCall).where(LLMCall.request_id == request_id))
    rows = list(result.scalars().all())

    total_input = sum(row.input_tokens for row in rows)
    total_output = sum(row.output_tokens for row in rows)
    total_cost_micro_usd = sum(row.cost_micro_usd for row in rows)

    return ChatUsage(
        input_tokens=total_input,
        output_tokens=total_output,
        cost_usd=total_cost_micro_usd / 1_000_000,
    )


# ---------------------------------------------------------------------------
# The turn orchestration itself -- stages 1, 2, 3 and 12
# (`ARCHITECTURE_V1.md` §3.4), independent of how `session`/`trace` were
# built. The `@router.post` handler this feeds is a thin FastAPI wrapper
# around this one function, added once BE-1's ADR-018 refactor lands
# (see the module docstring).
# ---------------------------------------------------------------------------


async def handle_chat_turn(
    session: AsyncSession,
    trace: TraceContext,
    *,
    executor: TurnExecutor,
    user_id: str,
    request_id: str,
    message: str,
    conversation_id: str | None,
) -> ChatResponse:
    """The whole turn, end to end, against an already-constructed
    `session` and `trace`. Raises `UnknownConversationError` (from
    `core.conversations.gateway`) unchanged for a stale client-supplied
    `conversation_id` — the route maps that to a 422, per the frozen §6
    contract's own failure modes; this function does not know about
    HTTP status codes.
    """
    conversation = await get_or_create_conversation(
        session, user_id=user_id, conversation_id=conversation_id
    )

    # --- stage 1: message_received ---
    await persist_message(
        session,
        conversation_id=conversation.id,
        role="user",
        content=message,
        request_id=request_id,
    )
    await trace.emit(TraceStage.MESSAGE_RECEIVED, summary="user message persisted", task_id=None)

    # --- stage 2: context_loaded ---
    recent_messages = await read_recent_messages(session, conversation_id=conversation.id)
    await trace.emit(
        TraceStage.CONTEXT_LOADED,
        summary=f"loaded {len(recent_messages)} prior message(s)",
        task_id=None,
    )

    # --- stage 3: memory_retrieved ---
    await record_short_term_memory_retrieval(
        session,
        user_id=user_id,
        source_request_id=request_id,
        conversation_id=conversation.id,
        message_count=len(recent_messages),
    )
    await trace.emit(
        TraceStage.MEMORY_RETRIEVED,
        summary="short-term memory retrieval recorded",
        task_id=None,
    )

    # --- stages 4-11: the turn executor (stub here; T11b's real pipeline
    # elsewhere) ---
    result = await executor.run_turn(
        request_id=request_id,
        user_id=user_id,
        conversation_id=conversation.id,
        message=message,
        trace=trace,
    )

    message_out: MessageOut | None = None
    failure_out: ChatFailure | None = None

    if result.outcome == "ok":
        # ADR-015: the agent's own analysis IS the user-facing message --
        # no separate final-response LLM call in M1.
        assistant_message = await persist_message(
            session,
            conversation_id=conversation.id,
            role="assistant",
            content=result.assistant_content or "",
            request_id=request_id,
        )
        message_out = MessageOut(
            id=assistant_message.id,
            role="assistant",
            content=assistant_message.content or "",
            created_at=assistant_message.created_at.isoformat(),
        )
    else:
        known_projects = (
            [ProjectSummary(**project) for project in result.known_projects]
            if result.known_projects
            else None
        )
        failure_out = ChatFailure(kind=result.failure_kind, known_projects=known_projects)

    task_out: ChatTaskOut | None = None
    if result.task_id is not None:
        task_row = await session.get(Task, result.task_id)
        if task_row is not None:
            task_out = ChatTaskOut(
                id=task_row.id, status=task_row.status, assigned_agent=task_row.assigned_agent
            )

    # --- stage 12: final_response, always -- even on failure (ET-8) ---
    await trace.emit(
        TraceStage.FINAL_RESPONSE,
        summary=f"turn {result.outcome}",
        detail={"outcome": result.outcome, "failure_kind": result.failure_kind},
        task_id=result.task_id,
    )

    trace_entries = await read_trace_entries(session, request_id=request_id)
    usage = await read_usage(session, request_id=request_id)

    return ChatResponse(
        request_id=request_id,
        conversation_id=conversation.id,
        outcome=result.outcome,
        message=message_out,
        task=task_out,
        failure=failure_out,
        trace=trace_entries,
        usage=usage,
    )


# ---------------------------------------------------------------------------
# The route itself.
# ---------------------------------------------------------------------------

router = APIRouter(prefix="/api/v1", tags=["chat"])

# Stateless, so a single shared instance is harmless — unlike
# `engine`/`sessionmaker`, nothing about this stub varies per `Settings`,
# so this is not the module-level-cache pattern ADR-018 exists to remove.
# T11b replaces this with a constructor call building the real executor
# from `app.state.registries`, at which point this becomes a per-app value
# too.
_TURN_EXECUTOR = StubTurnExecutor()


@router.post("/chat", response_model=ChatResponse)
async def chat(
    payload: ChatRequest,
    request: Request,
    session: AsyncSession = Depends(get_session),
    user_id: str = Depends(require_owner_session),
) -> ChatResponse:
    """`POST /api/v1/chat` — the frozen §6 contract. 401 (no session) and
    422 (malformed body / bad `X-Request-Id`) are both handled before
    this function runs — the first by `Depends(require_owner_session)`,
    the second by `ChatRequest`'s own validation and
    `RequestContextMiddleware` respectively. `require_client_header` is
    called explicitly, matching `auth.py`'s own pattern, because ADR-008's
    CSRF control applies to every mutating request, not only this one.
    """
    require_client_header(request)

    request_id: str = request.state.request_id
    trace = LiveTraceContext(
        request_id=request_id,
        user_id=user_id,
        conversation_id=payload.conversation_id,
        sessionmaker=request.app.state.sessionmaker,
        turn_deadline_s=request.app.state.settings.sunil_turn_deadline_s,
    )

    try:
        return await handle_chat_turn(
            session,
            trace,
            executor=_TURN_EXECUTOR,
            user_id=user_id,
            request_id=request_id,
            message=payload.message,
            conversation_id=payload.conversation_id,
        )
    except UnknownConversationError as exc:
        # Not one of the four named failure.kind values (§11.3) -- this is
        # a malformed reference in the request body, the same category
        # §6 already reserves 422 for, not a turn outcome to trace.
        raise HTTPException(status_code=422, detail=str(exc)) from exc
