"""`TurnResult` / `TurnExecutor` — the seam between `api/routes/chat.py`'s
`handle_chat_turn()` and `core/orchestrator/turn.py`'s `LiveTurnExecutor`.

**Moved here from `sunil.api.routes.chat` (T11a's original home for both)
because `core/` may never import `sunil.api` (`ARCHITECTURE_V1.md` §3.1,
enforced by `tests/security/test_import_boundaries.py
::test_core_never_imports_the_api_layer`) — the orchestrator is called
from an HTTP route today and from M10's scheduler later, so it must not
be coupled to anything under `api/`.** `sunil.api.routes.chat` still
imports and re-exports both names unchanged (`from sunil.core.orchestrator
.contracts import TurnExecutor, TurnResult`), so every existing
`from sunil.api.routes.chat import TurnExecutor, TurnResult` import site
— tests included — keeps working without modification. This module is
the one place either type is *defined*; that file is one of several
places it may be *imported from*.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from sunil.core.trace.context import TraceContext


@dataclass(frozen=True)
class TurnResult:
    """What a `TurnExecutor` returns — the orchestration outcome the chat
    route maps onto the frozen §6 envelope's `outcome`/`failure`/`task`/
    `message` fields. Carries no trace or usage data itself: those come
    from `audit_events`/`llm_calls`, read back by the route after the
    executor returns (§8.1's own "reconstructable from logs alone").
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
    `run_agent()` call + `AgentResult -> TurnResult` mapping
    (`core.orchestrator.turn.LiveTurnExecutor`).

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
