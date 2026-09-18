"""The memory service — audit outside the vendor call, and a recall that degrades.

C3 §2's rule, in one sentence: **memory being down degrades a turn; it never
fails one.** `recall()` therefore converts `MemoryUnavailableError` and a budget
overrun into an EMPTY result carrying `degraded=True`, which the turn reports as
`memory_retrieved.detail.degraded` — the owner sees that the answer was composed
without long-term memory rather than getting no answer at all.

`write()` is the opposite posture, deliberately: a lost write must be VISIBLE
(C3 §4), so a provider failure propagates. Silently dropping a memory write is
how a system quietly stops remembering.

**The audit row is written BEFORE the vendor call**, never after. A provider that
hangs, crashes or never returns still leaves the row whose id the receipt echoes
(`WriteReceipt.audit_event_id`), which is what makes the linkage a fact rather
than a hope. That ordering is the whole reason C3 §2 put `audit_event_id` in the
signature instead of letting the provider mint one.

`MemoryScopeError` is NOT caught: an unresolvable scope is a caller bug raised
before any vendor call (C3 §3), and degrading it would hide a code defect behind
"memory was slow".

**Scope resolution (ruling R13).** The optional `resolver` turns a human key
(`MemoryScope(kind="project", id="pda")`) into the entity row id the provider
files under. It runs INSIDE recall's budget, not beside it: resolve + vendor is
two sequential database round-trips, and giving each its own 800 ms budget would
let a "budgeted" recall take 1.6 s. On the write path it runs BEFORE the audit
row is minted, so the row names the scope the memory is actually filed under —
lineage has to name the real filing — and a write that cannot resolve leaves no
audit row for a memory that never happened.

**R12 rule 3** lives here too, on the write path only: a `kind="project"` scope
whose key the entity table does not know but the PROJECT REGISTRY
(`config/projects.yaml`) does is materialised into the table and resolution
proceeds. Recall never materialises anything — a read must not mutate, the same
posture as the TTL filter — and a key in neither place stays `MemoryScopeError`.
"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Protocol

from sunil.core.memory.entities import EntityResolver, upsert_entity
from sunil.core.memory.provider import (
    MemoryItem,
    MemoryProvider,
    MemoryScope,
    MemoryScopeError,
    MemoryUnavailableError,
    RecallResult,
    ScoredMemory,
    WriteReceipt,
    WriteRules,
)

#: C3 §2's latency budget for recall, seconds. A recall that overruns it is
#: abandoned and the turn continues degraded — the budget is the point.
RECALL_BUDGET_S = 0.8


class MemoryAuditSink(Protocol):
    """Where the write's audit row is recorded. Injected rather than imported so
    this module does not reach into `core.audit` (and so a test can assert the
    row exists even when the provider never returns)."""

    async def record_memory_write(self, *, scope: MemoryScope, item: MemoryItem) -> str: ...


@dataclass(frozen=True)
class RecallOutcome:
    """What the context loader gets back. `degraded` is the field the
    `memory_retrieved` stage reports; `reason` names WHY, as an enum token so it
    is legal in a `trace[].detail` (enums and numbers only)."""

    items: list[ScoredMemory]
    degraded: bool
    reason: str | None = None


class MemoryService:
    """C3's service half: scope in, degrade on failure, audit outside the vendor."""

    def __init__(
        self,
        provider: MemoryProvider,
        *,
        audit_sink: MemoryAuditSink | None = None,
        budget_s: float = RECALL_BUDGET_S,
        resolver: EntityResolver | None = None,
        project_registry: Mapping[str, Any] | None = None,
    ) -> None:
        """`resolver` and `project_registry` are keyword-only and default to
        `None`, which preserves every existing call site and the fake-wired app:
        with no resolver the scope reaches the provider exactly as given, which
        is what the frozen C3 contract suite asserts."""
        self._provider = provider
        self._audit_sink = audit_sink
        self._budget_s = budget_s
        self._resolver = resolver
        self._project_registry = project_registry or {}

    @property
    def provider(self) -> MemoryProvider:
        """The wired store. Readable so the composition root can ask it for the
        storage-hygiene jobs that are NOT on C3's Protocol (the reaper's
        `delete_expired`) without reaching into a private attribute — and
        read-only, so nothing can swap the provider out from under a live
        service."""
        return self._provider

    async def recall(
        self, query: str, scope: MemoryScope, *, limit: int = 8
    ) -> RecallOutcome:
        """Never raises for provider unavailability or slowness.

        Resolution is inside the budget deliberately — see the module docstring.
        `MemoryScopeError` still escapes it: the budget bounds how long memory
        may take, not whether a caller bug is reported.
        """
        try:
            async with asyncio.timeout(self._budget_s):
                resolved = (
                    await self._resolver.resolve(scope)
                    if self._resolver is not None
                    else scope
                )
                result: RecallResult = await self._provider.recall(
                    query, resolved, limit=limit
                )
        except MemoryUnavailableError:
            return RecallOutcome(items=[], degraded=True, reason="unavailable")
        except TimeoutError:
            return RecallOutcome(items=[], degraded=True, reason="budget_exceeded")
        return RecallOutcome(items=list(result.items), degraded=False)

    async def write(
        self,
        item: MemoryItem,
        rules: WriteRules,
        *,
        scope: MemoryScope,
        audit_event_id: str | None = None,
    ) -> WriteReceipt:
        """Audit first, then the vendor call; failures surface.

        `audit_event_id` may be supplied by a caller that already recorded the
        row (a continuation re-using the original turn's audit); otherwise the
        injected sink writes it here, before anything leaves the process.
        """
        # BEFORE the audit row (R13 item 3). Both `MemoryScopeError` and
        # `MemoryUnavailableError` surface here — a lost write must be visible.
        resolved = await self._resolve_for_write(scope)

        recorded_id = audit_event_id
        if recorded_id is None:
            if self._audit_sink is None:
                raise ValueError(
                    "a memory write needs an audit_event_id or an audit sink — the "
                    "audit row is written BEFORE the vendor call (C3 §2), never after"
                )
            recorded_id = await self._audit_sink.record_memory_write(
                scope=resolved, item=item
            )

        # Deliberately unguarded: a lost write must be visible (C3 §4).
        return await self._provider.write(
            item, rules, scope=resolved, audit_event_id=recorded_id
        )

    async def _resolve_for_write(self, scope: MemoryScope) -> MemoryScope:
        """Resolution with R12 rule 3's lazy materialisation attached.

        The registry is consulted only after the table has already said "unknown"
        — so an entity that exists is never re-created — and only on this path.
        A key in neither place re-raises the resolver's own `MemoryScopeError`,
        because the write path must not become a way to invent entities.
        """
        if self._resolver is None:
            return scope
        try:
            return await self._resolver.resolve(scope)
        except MemoryScopeError:
            materialised = await self._materialise_from_registry(scope)
            if materialised is None:
                raise
            return materialised

    async def _materialise_from_registry(self, scope: MemoryScope) -> MemoryScope | None:
        """Registry → table, lazily (R12 rule 3). `None` means "not a registry
        key", which leaves the caller's `MemoryScopeError` standing.

        `upsert_entity` is idempotent on `key`, so a concurrent write that got
        there first returns the SAME row id rather than a second project entity —
        two rows for one project would be two memory scopes for one project, and
        the second would appear to have no history.
        """
        if scope.kind != "project" or scope.id is None:
            return None
        definition = self._project_registry.get(scope.id)
        if definition is None:
            return None
        row_id = await upsert_entity(
            self._resolver.engine,  # type: ignore[union-attr] - only called with a resolver
            "project",
            key=scope.id,
            name=getattr(definition, "display_name", scope.id),
        )
        return scope.model_copy(update={"id": row_id})


def memory_scope_for_turn(*, user_id: str | None, conversation_id: str) -> MemoryScope:
    """The scope a chat turn recalls against.

    `user_id` falls back to the literal `"owner"` on the service lane, which has
    no session subject: the system is single-owner (C5 §2.3), so a machine-lane
    turn recalls the owner's memory rather than an anonymous void — and the scope
    is still named explicitly, because C3 has no "all memory" scope.
    """
    return MemoryScope(
        user_id=user_id or "owner", kind="conversation", id=conversation_id
    )


def as_prompt_context(items: list[ScoredMemory]) -> list[dict[str, Any]]:
    """Recalled memories, flattened for the prompt builder. Content only —
    scores and provenance are audit facts, not prompt material."""
    return [{"content": scored.item.content, "type": scored.item.memory_type} for scored in items]
