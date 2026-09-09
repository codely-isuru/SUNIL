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
    audit_event_id: str              # echo of the write() parameter — writes are audited OUTSIDE
                                     # the provider; the echo proves linkage (see §2 signature)


class ScoredMemory(BaseModel):
    item: MemoryItem
    score: float                     # 0.0..1.0, higher = more relevant
    source: str                      # provider-internal provenance, e.g. "mem0:pgvector" / "fake"


class RecallResult(BaseModel):
    items: list[ScoredMemory]        # descending score; length <= limit


class MemoryProvider(Protocol):
    name: str

    async def recall(self, query: str, scope: MemoryScope, *, limit: int = 8) -> RecallResult: ...
    async def write(self, item: MemoryItem, rules: WriteRules,
                    *, audit_event_id: str) -> WriteReceipt: ...
```

**Why `audit_event_id` is a keyword-only parameter (fix round 2026-09-10, QA B4 — it was a required
receipt field with no input carrying it):** the memory *service* (SUNIL code) mints the id when it
writes the `audit_intent` row, then passes it in; the provider echoes it back in the receipt. A
parameter — rather than a field on `MemoryItem` — because it is lineage of the *call*, not content
of the item: putting it on the item would let a vendor persist it as memory metadata and would
conflate what is remembered with how the remembering was audited. Keyword-only so a vendor adapter
cannot positionally confuse it with anything else. The type-level effect stands: a provider
implementation cannot be called without receiving the linkage id, so "vendor library skipped
auditing" remains inexpressible.

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
  `memories` lineage row and passes its id in as the `audit_event_id` parameter; the provider only
  echoes it back in the receipt. A vendor library can therefore never skip auditing — the call
  order is `audit_intent → provider.write(…, audit_event_id=…) → audit_outcome(receipt)`.
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
    # payload_too_large: content over 32 KiB (UTF-8 bytes)
    # invalid_privacy_transition: the write would make equal content available under a
    #   LAXER label than it already carries in that scope (the widening-copy rule, §4a)
```

### 4a. Duplicate content and privacy — the ONE rule (normative; fix round 2026-09-10, QA B5)

Strictness is the total order `local_only(4) > confidential(3) > internal(2) > public(1)`
("stricter" = higher = fewer readers; **widening** = equal content becoming available under a
lower label than it already carries in that scope). Two items are **duplicates** when they are in
the SAME scope and their `content.strip()` compare equal case-insensitively — that definition is
exact for the fake and the contract suite; a real provider may detect duplicates semantically, but
rules 1–3 below bind whatever it detects identically.

Given an incoming write whose content duplicates a stored item:

1. **`rules.dedupe=True` (merge):** exactly one row survives — the stored one, whose `privacy`
   becomes `max(stored, incoming)` in the order above. Incoming stricter → the stored row is
   upgraded (narrowing: always safe). Incoming laxer or equal → the stored label is retained.
   Receipt: `op="merged"`, `memory_id=<stored id>`. A merge NEVER raises over privacy and NEVER
   lowers a label — "keep the stricter" and "never widen" are the same statement here.
2. **`rules.dedupe=False` (append):** the caller wants a distinct row.
   - incoming `privacy` stricter than or equal to the stored duplicate's → append normally
     (`op="created"`, two rows co-exist).
   - incoming `privacy` LAXER than the stored duplicate's → raise
     `MemoryWriteRejected(reason="invalid_privacy_transition")`. This is the **genuine widening**
     case the rule exists for: the append would mint a copy of confidential content under (say)
     `internal`, and the caller-side prompt filter (§2) would then happily ship the lax copy to a
     non-local model. Rejected, never averaged, never silently relabelled.
3. **Non-duplicate content:** append regardless of labels; no cross-item privacy interaction.

(The previous §5 text stated a `dedupe=False` condition inside the dedupe branch, described the
stricter label as "widening", and had one condition both raising and upgrading — all three
replaced by this section; §5's fake now cites it instead of restating it.)

`recall` never raises `MemoryUnavailableError` through to the orchestrator — the memory service
catches it and returns the degraded empty result; `write` failures surface (a lost write must be
visible, ROADMAP §13 write rules).

## 5. FAKE specification — `FakeMemoryProvider` (QA-buildable, no questions)

Module: `apps/api/tests/fakes/fake_memory_provider.py`. `name="fake"`. In-memory
`list[tuple[MemoryScope, MemoryItem]]`, ids `mem-1`, `mem-2`, … in write order;
`created_at` = `"2026-01-01T00:00:00Z"` plus `write_index` seconds.

`write(item, rules, audit_event_id=...)` — exact behaviour, in this order:
1. `rules.capture == "none"` → return `WriteReceipt(memory_id="", op="skipped",
   audit_event_id=<the parameter, echoed>)`; store nothing.
2. `len(item.content.encode()) > 32768` → raise `MemoryWriteRejected(reason="payload_too_large")`.
3. Duplicate detection + privacy resolution: apply **§4a verbatim** (duplicate = same scope +
   case-insensitive `content.strip()` equality; `dedupe=True` → merge into the stored row with
   `privacy = the stricter label`, `op="merged"`, stored id returned; `dedupe=False` + laxer
   incoming label → raise `MemoryWriteRejected(reason="invalid_privacy_transition")`;
   `dedupe=False` + stricter-or-equal label → append).
4. else append, `op="created"`. Every receipt echoes the `audit_event_id` parameter.

`recall(query, scope, limit=8)` — exact scoring, fully deterministic:
1. Candidates = items whose stored scope equals `scope` exactly, PLUS (when `scope.kind == "entity"`)
   items of any scope carrying an `EntityRef` with that `entity_id`.
2. Tokenise `query` on whitespace, lowercase. `score = (matching tokens found as substrings of
   lowercased content) / (total query tokens)`, rounded to 4 decimal places. Items scoring `0.0`
   are dropped.
3. Order: score descending, then **write order descending** (newest first — the fake's key is the
   integer suffix of its `mem-N` id, numerically; real providers use their monotonic insert
   sequence, because `created_at` alone is not a total order and lexicographic id comparison would
   put `mem-10` before `mem-2` — fix round 2026-09-10, QA should-fix: the old third tiebreaker was
   unreachable and wrong if reached). Truncate to `limit`.
4. `source="fake"` on every result.

Constructor flags for failure injection: `FakeMemoryProvider(unavailable=False)`;
`unavailable=True` → every call raises `MemoryUnavailableError` (tests assert the SERVICE degrades
recall and surfaces write failure).

Contract tests (`apps/api/tests/contracts/test_c3_memory_provider.py`):
1. write then recall in-scope hits; recall from a sibling conversation scope misses (leak probe).
2. entity-scoped recall finds an item written in a conversation scope but ref'd to the entity.
3. §4a disambiguated, three sub-cases in one scope (fix round 2026-09-10, QA B5):
   (a) write `"Fact X"` `internal`, then `"fact x "` `confidential` with `dedupe=True` →
   `op="merged"`, same id, recall shows `privacy="confidential"` (stored row upgraded — stricter
   wins); (b) write `"Fact Y"` `confidential`, then `"fact y"` `internal` with `dedupe=True` →
   `op="merged"`, recall still shows `"confidential"` (stored stricter retained, no exception);
   (c) write `"Fact Z"` `confidential`, then `"fact z"` `internal` with `dedupe=False` → raises
   `MemoryWriteRejected(reason="invalid_privacy_transition")`, while the same append with
   `privacy="confidential"` → `op="created"`, two rows.
4. `capture="none"` stores nothing and says so; the receipt echoes the passed `audit_event_id`.
5. deterministic ordering: three seeded items, one query, exact expected id order asserted —
   including two items with EQUAL scores, asserting newest-write-first between them.
6. `unavailable=True`: recall degrades to empty via the service, write raises.

## Changelog

- **v1.0.0 — 2026-09-10 fix round** (pre-merge; version unchanged because the freeze was never
  merged). `write` gains keyword-only `audit_event_id: str`, echoed in the receipt — the receipt
  field was previously unobtainable (QA B4; parameter-not-item-field argued in §2). Dedupe/privacy
  rewritten as one rule, §4a: merge = stricter label survives, never raises; genuine widening =
  the laxer-labelled duplicate APPEND, rejected as `invalid_privacy_transition` (QA B5 — replaces
  five mutually incompatible statements); contract test 3 now disambiguates all three sub-cases.
  Recall tiebreaker fixed to write-order-descending (old third key unreachable and lexicographic;
  QA should-fix).
