"""`POST /api/v1/chat` — the frozen §6 contract's turn endpoint (T11a).

**Deliberately partial on this branch.** The `TurnExecutor` Protocol, its
stub, and the response-shaping helpers below have no dependency on how
the app is wired (`ARCHITECTURE_V1.md` §2 T11a: "the turn executor is
behind a Protocol with a stub implementation ... so the endpoint is real,
testable and integrable before T11b exists"). The actual `@router.post`
handler — which needs a `Depends(get_session)`-shaped session and a
sessionmaker to build a `LiveTraceContext` — is being built against
BE-1's in-flight ADR-018 refactor (`create_app(settings)`,
`app.state.{settings,engine,sessionmaker}`, module-level `app` deleted).
Wiring it onto the pre-refactor shape now would mean rewriting it the
moment that lands; the Delivery Manager asked for this split explicitly.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from sunil.core.trace.context import TraceContext


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
    this with the real executor is T11b's entire job — nothing else in
    this file should need to change.
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
