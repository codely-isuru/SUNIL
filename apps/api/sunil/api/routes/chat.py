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

**`TurnResult`/`TurnExecutor` are defined in
`sunil.core.orchestrator.contracts`, not here** (moved there by T11b):
`core/orchestrator/turn.py`'s `LiveTurnExecutor` needs both types, and
`core/` may never import `sunil.api`
(`tests/security/test_import_boundaries.py
::test_core_never_imports_the_api_layer`, ARCHITECTURE_V1.md §3.1). Both
are re-exported here unchanged so every existing
`from sunil.api.routes.chat import TurnExecutor, TurnResult` import
keeps working.
"""

from __future__ import annotations

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
from sunil.core.orchestrator.contracts import TurnExecutor, TurnResult
from sunil.core.trace.context import LiveTraceContext, TraceContext
from sunil.core.trace.stages import TraceStage
from sunil.db.models import AuditEvent, LLMCall, Task
from sunil.db.session import get_session

__all__ = [
    "StubTurnExecutor",
    "TurnExecutor",
    "TurnResult",
    "chat",
    "handle_chat_turn",
    "read_trace_entries",
    "read_usage",
    "router",
]


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
# T11b's real executor (`core.orchestrator.turn.LiveTurnExecutor`) needs a
# per-request `session` plus per-app collaborators
# (`registries`/`model_router`/`tool_manager`/`agents`) that only a real
# `create_app()` lifespan populates on `app.state` — see `_build_executor()`
# below. This stub stays the fallback for any test fixture (like this
# module's own `test_chat_route.py`) that builds a bare `FastAPI` app with
# `chat.router` mounted directly, without wiring those, exactly as T11a's
# own docstring promised: "T11b wires in the real one without this file
# changing".
_TURN_EXECUTOR = StubTurnExecutor()


def _build_executor(request: Request, session: AsyncSession) -> TurnExecutor:
    """The real `LiveTurnExecutor` when `request.app.state.registries` is
    present (i.e. built via `sunil.main.create_app()`'s lifespan, which
    also sets `model_router`/`tool_manager`/`agents`) — the module-level
    `StubTurnExecutor` otherwise, so a bare-`FastAPI` test fixture that
    never wires those keeps working unmodified."""
    if getattr(request.app.state, "registries", None) is None:
        return _TURN_EXECUTOR

    from sunil.core.orchestrator.turn import LiveTurnExecutor

    return LiveTurnExecutor(
        session=session,
        registries=request.app.state.registries,
        model_router=request.app.state.model_router,
        tool_manager=request.app.state.tool_manager,
        agents=request.app.state.agents,
    )


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
            executor=_build_executor(request, session),
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
