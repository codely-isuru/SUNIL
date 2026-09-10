"""C3 — Memory Provider interface (frozen contract transcription).

Source of truth: ``docs/contracts/C3-memory-provider.md`` v1.0.0 (FROZEN, Phase 0
2026-09-10) §2 "Interface definition" and §4 "Error semantics" (incl. §4a, the
single normative dedupe/privacy rule).

Zero business logic lives here: protocols, models and exceptions only. The memory
*service* (audit-outside-vendor, scope resolution, the latency-budget degrade) is
``core/memory/service.py`` and the vendor adapter is
``memory_providers/mem0_provider.py`` — both Stream C (ARCHITECTURE_V2 §2).

Short-term memory is deliberately NOT behind this seam: the current
conversation's recent messages are read directly from the ``messages`` table by
the context loader (C3 §1). C3 governs long-term/semantic memory only.
"""

from __future__ import annotations

from typing import Literal, Protocol

from pydantic import BaseModel


class EntityRef(BaseModel):
    """Link into the CUSTOM entity schema (Stream C builds the tables; ids are opaque here)."""

    entity_type: Literal["client", "project", "person"]
    entity_id: str


class MemoryScope(BaseModel):
    """Every recall/write names its scope explicitly. There is no 'all memory' scope."""

    user_id: str  # the owner in V1; multi-user later
    kind: Literal["conversation", "user", "entity", "project"]
    id: str | None = None  # conversation_id / entity_id / project key; None only for kind="user"


class MemoryItem(BaseModel):
    id: str | None = None  # None on write (assigned); set on recall results
    content: str  # already-redacted text (ADR-006 scrub happens BEFORE the seam)
    memory_type: Literal["episodic", "fact", "preference", "decision"]
    privacy: Literal["public", "internal", "confidential", "local_only"]  # §26.9 — REQUIRED, no default
    entity_refs: list[EntityRef] = []
    source_request_id: str  # FR-144 lineage: which turn produced this
    created_at: str | None = None  # ISO-8601 UTC; assigned by the provider on write


class WriteRules(BaseModel):
    capture: Literal["none", "metadata_only", "redacted_full", "full_local_only"]  # ADR-014 kinds
    dedupe: bool = True  # provider may merge with a semantically-equal existing item
    ttl_days: int | None = None  # None = keep until superseded


class WriteReceipt(BaseModel):
    memory_id: str
    op: Literal["created", "merged", "skipped"]  # skipped iff rules.capture == "none"
    audit_event_id: str  # echo of the write() parameter — writes are audited OUTSIDE
    # the provider; the echo proves linkage (see §2 signature)


class ScoredMemory(BaseModel):
    item: MemoryItem
    score: float  # 0.0..1.0, higher = more relevant
    source: str  # provider-internal provenance, e.g. "mem0:pgvector" / "fake"


class RecallResult(BaseModel):
    items: list[ScoredMemory]  # descending score; length <= limit


class MemoryProvider(Protocol):
    name: str

    async def recall(
        self, query: str, scope: MemoryScope, *, limit: int = 8
    ) -> RecallResult: ...

    async def write(
        self, item: MemoryItem, rules: WriteRules, *, audit_event_id: str
    ) -> WriteReceipt: ...


# --------------------------------------------------------------------------- #
# C3 §4 — error semantics
# --------------------------------------------------------------------------- #
class MemoryScopeError(Exception):
    """Unresolvable scope id — caller bug, never retried (C3 §3: raised before any
    vendor call)."""


class MemoryUnavailableError(Exception):
    """Vendor down/timeout — the context loader degrades (C3 §2's 800 ms budget:
    memory being down degrades a turn, it never fails one)."""


class MemoryWriteRejected(Exception):
    """C3 §4. ``payload_too_large``: content over 32 KiB (UTF-8 bytes).
    ``invalid_privacy_transition``: the write would make equal content available
    under a LAXER label than it already carries in that scope (the widening-copy
    rule, §4a rule 2).

    The contract declares ``reason`` and its Literal type; the keyword-friendly
    constructor is the transcription's only addition.
    """

    reason: Literal["payload_too_large", "invalid_privacy_transition"]

    def __init__(
        self, reason: Literal["payload_too_large", "invalid_privacy_transition"]
    ) -> None:
        super().__init__(reason)
        self.reason = reason


#: C3 §4a's strictness total order: ``local_only(4) > confidential(3) >
#: internal(2) > public(1)``. "Stricter" = higher = fewer readers; **widening** =
#: equal content becoming available under a lower label than it already carries in
#: that scope.
PRIVACY_STRICTNESS: dict[str, int] = {
    "public": 1,
    "internal": 2,
    "confidential": 3,
    "local_only": 4,
}
