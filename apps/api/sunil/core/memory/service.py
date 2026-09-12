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
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any, Protocol

from sunil.core.memory.provider import (
    MemoryItem,
    MemoryProvider,
    MemoryScope,
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
    ) -> None:
        self._provider = provider
        self._audit_sink = audit_sink
        self._budget_s = budget_s

    async def recall(
        self, query: str, scope: MemoryScope, *, limit: int = 8
    ) -> RecallOutcome:
        """Never raises for provider unavailability or slowness."""
        try:
            async with asyncio.timeout(self._budget_s):
                result: RecallResult = await self._provider.recall(query, scope, limit=limit)
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
        recorded_id = audit_event_id
        if recorded_id is None:
            if self._audit_sink is None:
                raise ValueError(
                    "a memory write needs an audit_event_id or an audit sink — the "
                    "audit row is written BEFORE the vendor call (C3 §2), never after"
                )
            recorded_id = await self._audit_sink.record_memory_write(scope=scope, item=item)

        # Deliberately unguarded: a lost write must be visible (C3 §4).
        return await self._provider.write(
            item, rules, scope=scope, audit_event_id=recorded_id
        )


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
