# C3 — Memory Provider Interface

**Version:** 1.0.0 · **Status:** FROZEN (Phase 0, 2026-09-10) · **Owner:** Solution Architect
**Consumers:** Stream C (Mem0 + entities), core orchestrator (context loading, stage 3
`memory_retrieved`), Stream D (audit browser shows memory writes).
**Informed by:** M1 reference `main:apps/api/sunil/core/memory/short_term.py` (short-term = the
conversation's own messages; the auditable `memories` pointer row), ROADMAP §13, ADR-014 (capture
classes), ADR-030 (Mem0 behind the seam; entity schema stays custom).

Change policy: additive optional fields bump MINOR; changes to `recall`/`write` signatures, scope
kinds, or receipt semantics bump MAJOR with a new ADR.

---

## 1. Purpose

One seam through which every agent/orchestrator memory read and write passes, so that: retrieval is
scoped (no agent reads outside its scope), every write is classified (§26.9) and audited, and the
engine (Mem0 on Postgres/pgvector) is a replaceable vendor. **Short-term memory is not behind this
seam** — per the M1-proven shape, the current conversation's recent messages are read directly from
the `messages` table by the context loader; C3 governs long-term/semantic memory only.

## 2. Interface definition

Types live in `apps/api/sunil/core/memory/provider.py` (rebuilt).

```python
from typing import Literal, Protocol

from pydantic import BaseModel


class EntityRef(BaseModel):
    """Link into the CUSTOM entity schema (Stream C builds the tables; ids are opaque here)."""
    entity_type: Literal["client", "project", "person"]
    entity_id: str


class MemoryScope(BaseModel):
    """Every recall/write names its scope explicitly. There is no 'all memory' scope."""
    user_id: str                     # the owner in V1; multi-user later
    kind: Literal["conversation", "user", "entity", "project"]
    id: str | None = None            # conversation_id / entity_id / project key; None only for kind="user"


class MemoryItem(BaseModel):
    id: str | None = None            # None on write (assigned); set on recall results
    content: str                     # already-redacted text (ADR-006 scrub happens BEFORE the seam)
    memory_type: Literal["episodic", "fact", "preference", "decision"]
    privacy: Literal["public", "internal", "confidential", "local_only"]   # §26.9 — REQUIRED, no default
    entity_refs: list[EntityRef] = []
    source_request_id: str           # FR-144 lineage: which turn produced this
    created_at: str | None = None    # ISO-8601 UTC; assigned by the provider on write


class WriteRules(BaseModel):
    capture: Literal["none", "metadata_only", "redacted_full", "full_local_only"]  # ADR-014 kinds
    dedupe: bool = True              # provider may merge with a semantically-equal existing item
    ttl_days: int | None = None      # None = keep until superseded


class WriteReceipt(BaseModel):
    memory_id: str
    op: Literal["created", "merged", "skipped"]   # skipped iff rules.capture == "none"
    audit_event_id: str              # writes are audited OUTSIDE the provider; receipt proves linkage


class ScoredMemory(BaseModel):
    item: MemoryItem
    score: float                     # 0.0..1.0, higher = more relevant
    source: str                      # provider-internal provenance, e.g. "mem0:pgvector" / "fake"


class RecallResult(BaseModel):
    items: list[ScoredMemory]        # descending score; length <= limit


class MemoryProvider(Protocol):
    name: str

    async def recall(self, query: str, scope: MemoryScope, *, limit: int = 8) -> RecallResult: ...
    async def write(self, item: MemoryItem, rules: WriteRules) -> WriteReceipt: ...
```

Normative rules:

- **Scope is a filter the provider must enforce**, not a hint: a recall with
  `kind="entity", id="client_x"` returns only items carrying that `EntityRef` (or written in that
  scope); `kind="user"` returns cross-conversation items for that user. Tests probe leakage.
- **Privacy filtering is caller-side policy, provider-side data**: the provider stores and returns
  `privacy` verbatim; the context loader drops `local_only` items from any prompt routed to a
  non-local model (enforced next to the router, where `privacy_class` is computed — same
  structural-population rule as C2 §2).
- **Redaction before the seam**: `content` arrives already scrubbed (ADR-006) and capture-classified
  (ADR-014). The provider never sees raw secrets; it must not re-classify.
- **Audit outside the vendor**: the memory service (SUNIL code) writes the `audit_events` /
  `memories` lineage row and passes its id in; the provider only echoes it back in the receipt.
  A vendor library can therefore never skip auditing — the call order is
  `audit_intent → provider.write → audit_outcome(receipt)`.
- **Latency budget**: `recall` on the turn hot path must return in ≤ 800 ms or the context loader
  proceeds without long-term memory (recorded in the trace as `memory_retrieved` with
  `{"degraded": true}`). Memory being down degrades a turn; it never fails one.
- **Embeddings** (Mem0 backend) are obtained through the C2 gateway, so embedding calls inherit
  routing, budgets and audit like every other model call.

## 3. Entity linkage points

The entity schema (`clients`, `projects`, `people` + `entity_links`) is **custom Stream C code**,
not Mem0's. The seam touches it in exactly two places:

1. `MemoryItem.entity_refs` — persisted verbatim with the memory (Mem0 metadata), so recall can
   filter by entity without joining SUNIL tables.
2. Scope resolution — `MemoryScope(kind="project", id="pda")` is resolved by the memory *service*
   (SUNIL code) to the project's entity id before hitting the provider; the provider only ever sees
   resolved ids. Unknown ids raise `MemoryScopeError` before any vendor call.

## 4. Error semantics

```python
class MemoryScopeError(Exception): ...      # unresolvable scope id — caller bug, never retried
class MemoryUnavailableError(Exception): ...  # vendor down/timeout — context loader degrades (see §2)
class MemoryWriteRejected(Exception):
    reason: Literal["payload_too_large", "invalid_privacy_transition"]
    # payload cap: 32 KiB content; privacy may never be widened on merge
    # (a merge that would relabel confidential→internal is rejected, not averaged)
```

`recall` never raises `MemoryUnavailableError` through to the orchestrator — the memory service
catches it and returns the degraded empty result; `write` failures surface (a lost write must be
visible, ROADMAP §13 write rules).

## 5. FAKE specification — `FakeMemoryProvider` (QA-buildable, no questions)

Module: `apps/api/tests/fakes/fake_memory_provider.py`. `name="fake"`. In-memory
`list[tuple[MemoryScope, MemoryItem]]`, ids `mem-1`, `mem-2`, … in write order;
`created_at` = `"2026-01-01T00:00:00Z"` plus `write_index` seconds.

`write(item, rules)` — exact behaviour:
1. `rules.capture == "none"` → return `WriteReceipt(memory_id="", op="skipped", audit_event_id=<passed-through>)`; store nothing.
2. `len(item.content.encode()) > 32768` → raise `MemoryWriteRejected(reason="payload_too_large")`.
3. `rules.dedupe` and an existing item in the SAME scope has case-insensitively equal
   `content.strip()` → return that item's id with `op="merged"` (privacy: keep the STRICTER of the
   two, order `local_only > confidential > internal > public`; a widening merge raises
   `MemoryWriteRejected(reason="invalid_privacy_transition")` when the incoming item is stricter
   than the stored one and `dedupe=False` — with `dedupe=True` the stored row is upgraded).
4. else append, `op="created"`.

`recall(query, scope, limit=8)` — exact scoring, fully deterministic:
1. Candidates = items whose stored scope equals `scope` exactly, PLUS (when `scope.kind == "entity"`)
   items of any scope carrying an `EntityRef` with that `entity_id`.
2. Tokenise `query` on whitespace, lowercase. `score = (matching tokens found as substrings of
   lowercased content) / (total query tokens)`, rounded to 4 decimal places. Items scoring `0.0`
   are dropped.
3. Order: score descending, then `created_at` descending, then id ascending. Truncate to `limit`.
4. `source="fake"` on every result.

Constructor flags for failure injection: `FakeMemoryProvider(unavailable=False)`;
`unavailable=True` → every call raises `MemoryUnavailableError` (tests assert the SERVICE degrades
recall and surfaces write failure).

Contract tests (`apps/api/tests/contracts/test_c3_memory_provider.py`):
1. write then recall in-scope hits; recall from a sibling conversation scope misses (leak probe).
2. entity-scoped recall finds an item written in a conversation scope but ref'd to the entity.
3. dedupe merge keeps the stricter privacy label; widening is impossible.
4. `capture="none"` stores nothing and says so.
5. deterministic ordering: three seeded items, one query, exact expected id order asserted.
6. `unavailable=True`: recall degrades to empty via the service, write raises.
