"""The seam table — where every frozen contract's implementation is plugged in.

`create_app()` resolves four seams (C1 Tool Manager, C2 provider, C3 memory, C4
approvals) plus the conversation resolver and the turn executor, choosing each
from `Settings` (§3's plug order). Two rules make this a boundary rather than a
convenience:

1. **Production code never imports a test double.** A `fake` selection resolves
   to the object the caller INJECTED via `Seams`; nothing here imports
   `tests.fakes`. An uninjected `fake` raises `SeamUnavailable` at boot, so an
   app cannot come up half-wired and discover it on the first request.
2. **An unbuilt `real` implementation is a loud boot failure**, naming the stream
   that owns it. Streams A/B/D land their implementations behind these same
   names; until then "real" is a `SeamUnavailable`, never a silent fallback to a
   fake — a fallback is how a fake reaches production.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from sunil.core.conversations.resolver import ResolvedConversation


class SeamUnavailable(Exception):
    """A contract's implementation was selected but is not wired.

    Raised at application construction, never on the request path: the whole
    point of ADR-018's factory is that a misconfigured app does not boot.
    """


class ConversationResolver(Protocol):
    """Resolution happens in the ROUTE, before any turn machinery runs, because
    a 404 for an unknown or out-of-lane conversation is an authorisation answer
    and must not depend on the orchestrator having started."""

    async def resolve(
        self, *, lane: str, conversation_id: str | None, user_id: str | None,
        channel_label: str | None = None,
    ) -> ResolvedConversation: ...


class TurnExecutor(Protocol):
    """One governed turn. The real one is
    `core.orchestrator.turn.GovernedTurnExecutor`; C5 §4's `StubTurnExecutor`
    satisfies the same shape, which is what lets the C5 suite exercise the REAL
    route (auth deps + validation + envelope builder) before the orchestrator is
    involved."""

    async def run(
        self,
        *,
        message: str,
        conversation: ResolvedConversation,
        request_id: str,
        lane: str,
        user_id: str | None,
        channel_label: str | None,
    ) -> Any: ...  # a `schemas.ChatResponse`; typed `Any` to keep core/api decoupled


@dataclass(frozen=True)
class Seams:
    """Injected implementations. Every field defaults to `None`, meaning "resolve
    from settings"; a test (or a stream building ahead of its neighbours) passes
    the ones it owns."""

    sessionmaker: async_sessionmaker[AsyncSession] | None = None
    provider: Any | None = None  # C2 LLMProvider
    memory_provider: Any | None = None  # C3 MemoryProvider
    approvals: Any | None = None  # C4 ApprovalsService
    tool_manager: Any | None = None  # C1 ToolManagerProtocol
    tool_adapters: tuple[Any, ...] = ()  # C1 ToolAdapters, for the plan catalogue
    conversation_resolver: ConversationResolver | None = None
    turn_executor: TurnExecutor | None = None


def _require(injected: Any, *, setting: str, value: str) -> Any:
    if injected is None:
        raise SeamUnavailable(
            f"{setting}={value!r} selects an injected implementation, but none was "
            "passed to create_app(seams=…). Production code never imports a test "
            "double, so this is a boot failure rather than a fallback."
        )
    return injected


def _unbuilt(*, setting: str, stream: str, module: str) -> SeamUnavailable:
    return SeamUnavailable(
        f"{setting}='real' selects {module}, which Stream {stream} has not landed "
        "yet. Refusing to boot rather than falling back to a fake."
    )


def resolve_provider(settings: Any, seams: Seams) -> Any:
    """C2 — the model provider lane (transport wiring only; router policy is
    upstream of it and invisible here)."""
    lane = settings.sunil_llm_provider_lane
    if lane == "fake":
        return _require(seams.provider, setting="SUNIL_LLM_PROVIDER_LANE", value=lane)
    if seams.provider is not None:
        return seams.provider
    raise _unbuilt(
        setting="SUNIL_LLM_PROVIDER_LANE", stream="B", module="providers/gateway.py"
    )


def resolve_memory_provider(settings: Any, seams: Seams) -> Any:
    """C3 — the long-term memory provider behind `core/memory/service.py`."""
    selected = settings.sunil_memory_provider
    if selected == "fake":
        return _require(seams.memory_provider, setting="SUNIL_MEMORY_PROVIDER", value=selected)
    if seams.memory_provider is not None:
        return seams.memory_provider
    raise _unbuilt(
        setting="SUNIL_MEMORY_PROVIDER", stream="C", module="memory_providers/mem0_provider.py"
    )


def resolve_approvals(settings: Any, seams: Seams) -> Any:
    """C4 — park/consume. The Tool Manager is its only caller (C4 §1)."""
    selected = settings.sunil_approvals_service
    if selected == "fake":
        return _require(seams.approvals, setting="SUNIL_APPROVALS_SERVICE", value=selected)
    if seams.approvals is not None:
        return seams.approvals
    raise _unbuilt(
        setting="SUNIL_APPROVALS_SERVICE", stream="D", module="core/approvals/service.py"
    )


def resolve_tool_manager(settings: Any, seams: Seams) -> Any:
    """C1 — the single execution chokepoint. The spine never constructs one: it
    is `core/tool_framework/manager.py`, Stream A's file, and a second
    implementation of the chokepoint is a second path to a privileged call."""
    selected = settings.sunil_tool_manager
    if selected == "fake":
        return _require(seams.tool_manager, setting="SUNIL_TOOL_MANAGER", value=selected)
    if seams.tool_manager is not None:
        return seams.tool_manager
    raise _unbuilt(
        setting="SUNIL_TOOL_MANAGER", stream="A", module="core/tool_framework/manager.py"
    )
