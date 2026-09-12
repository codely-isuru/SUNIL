# S2-C — Memory for real (Stream C)

**Branch:** `task/S2-C-memory` (from `V2` @ `6280f48`) · **Owner:** backend_engineer
**Contract:** `docs/contracts/C3-memory-provider.md` **v1.1.0** (FROZEN) · **ADRs:** 030, 013, 014, 001
**Scope owned:** `apps/api/sunil/core/memory/**`, `apps/api/sunil/memory_providers/**`,
`apps/api/sunil/api/wiring.py`, migration `0005`, memory settings, tests under those modules.
`tests/contracts/**` untouched (the fake suite is QA's).

---

## 1. The library decision — direct pgvector, NOT Mem0-the-library

**Rationale (the one paragraph).** ADR-030's principle is "integrate open-source components
*behind our seams*", and C3 **is** that seam; the only question is which engine sits behind
it today. Mem0 loses on three counts that are about C3's own text, not about taste.
(1) **Its write path is an LLM**: `mem0.add()` sends content to a model that decides
ADD/UPDATE/DELETE and rewrites the stored fact — which C3 §2 forbids in as many words
("`content` arrives already scrubbed… the provider never sees raw secrets; it **must not
re-classify**") and which cannot satisfy §4a, a rule specified as exact arithmetic on a
four-value privacy lattice ("stricter survives the merge; a laxer-labelled append is
rejected"), let alone satisfy it repeatably in a contract test. (2) **It drags an LLM +
embedder dependency chain and its own schema**: no provider key exists on this machine, so
the parity proof would be unrunnable, and its schema has no `privacy` column — the field the
whole of §4a turns on. (3) **Audit posture**: C3 puts the audit row outside the vendor and has
the vendor echo `audit_event_id`, which behind Mem0 is adapter code anyway, so the vendor buys
nothing there. **Mem0 remains swappable, and deliberately still selectable**:
`SUNIL_MEMORY_PROVIDER=mem0` resolves to a loud `SeamUnavailable` naming
`memory_providers/mem0_provider.py` — never a silent fallback to pgvector, because an operator
who configured Mem0 must not quietly get different retrieval. Keeping the unselected vendor
live and loud *is* ADR-030's principle honoured.

Name: **`PgVectorMemoryProvider`** (`apps/api/sunil/memory_providers/pgvector_provider.py`).

## 2. What landed

| Piece | File |
| --- | --- |
| Provider (C3 §2 protocol, §4a verbatim, §5 order) | `sunil/memory_providers/pgvector_provider.py` |
| Schema: `memories`, `memory_entity_links`, `clients`, `projects`, `people` | `sunil/core/memory/tables.py` |
| Embedder seam: `Embedder`, `HashingEmbedder`, `GatewayEmbedder` | `sunil/core/memory/embedding.py` |
| §3 scope resolution + entity upsert | `sunil/core/memory/entities.py` |
| Migration (single head, `0004` → `0005`) | `sunil/db/alembic/versions/0005_memory_and_entities.py` |
| Autogenerate fence for the five tables | `sunil/db/autogenerate.py` |
| Seam wiring (`pgvector` real, `mem0` still unbuilt) | `sunil/api/wiring.py`, `sunil/main.py` |
| Settings + committed env shape | `sunil/settings.py`, `.env.example` |

**Unchanged, on purpose:** `core/memory/provider.py` (the frozen transcription),
`core/memory/service.py` (the orchestrator already consumes the seam through it),
`core/orchestrator/turn.py`, and every file under `tests/contracts/`.

### Design points a reviewer should check specifically

* **`privacy` has no server default** (C3 §2 "REQUIRED, no default"; the 2026-08-17
  central-memory lesson), pinned by `test_memories_privacy_has_no_server_default`.
* **`seq`, a monotonic insert sequence, is the recall tiebreaker** — C3 §5 step 3 says real
  providers use exactly this because `created_at` is not a total order.
* **§4a runs under `pg_advisory_xact_lock(scope, content_key)`.** Rules 1–2 are
  read-then-decide, and without serialisation two concurrent `dedupe=False` writes both see
  "no duplicate" and both insert — so the widening copy rule 2 exists to refuse lands anyway.
  A UNIQUE index cannot substitute: `dedupe=False` legitimately appends duplicates.
* **`memory_entity_links` has no FK into the entity tables.** C3 §3 makes entity ids opaque to
  the provider and puts resolution (and `MemoryScopeError`) in the service *before any vendor
  call*; a FK would turn a caller bug into a lost memory and would refuse to remember anything
  about an entity whose row does not exist yet.
* **No privacy predicate in the recall query.** C3 §2: privacy filtering is caller-side policy,
  provider-side data. Filtering here would look safer and would move the decision away from the
  only place that knows where the prompt is going.
* **Embedding width is schema, not config** (`vector(1536)`); the provider refuses an embedder
  of another width at construction, naming both numbers.

## 3. Parity evidence

`tests/unit/memory/test_pgvector_parity.py` twins C3 §5's numbered behaviours 1–7 against the
real provider on live Postgres, in the pattern `tests/unit/approvals/test_real_service_contract.py`
set. What is twinned is every behaviour the contract *binds both implementations to* — scope as
an enforced filter (incl. cross-user and `kind="user"`/NULL-id probes), the entity reach-across,
§4a(a)/(b)/(c) plus "the rejected widening left no row" and scope-locality, capture-none, the
32-KiB **byte** cap, relevance ordering with the newest-first tiebreak, limit truncation, empty
query, TTL, and the concurrency case. Never the fake's numerals (`mem-1`, `1.0/0.5/0.5`): §5
step 3 and §4a both say in as many words that a real provider's sequence and duplicate
detection are its own.

Behaviours 6 (unavailable) and 7 (signature pin) live in `test_pgvector_posture.py`, outside the
Postgres skip — they are the two properties that matter most on a machine with no Docker, and
they would otherwise be the two that never run there. The unavailable case uses a **real**
engine pointed at a dead port, not a mock that raises the expected error.

Mutation checks run to prove the tests bind, not just pass:

* `seq.desc()` → `seq.asc()` in the recall ORDER BY → 2 ordering tests FAIL, restored.
* `MemoryScopeError` raise → `return scope` in the resolver → the unknown-key test FAILS, restored.

## 4. Migration proof

```
$ alembic heads                      # before
0004 (head)
$ alembic heads                      # after
0005 (head)
$ alembic upgrade head               # against an EMPTY database
$ alembic current
0005 (head)
$ psql -tAc "SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY 1"
alembic_version approvals audit_events clients conversations llm_calls memories
memory_entity_links messages people plans projects task_status_events tasks tool_calls users
```

Single head before and after; fresh deploy from empty succeeds. `test_migration_matches_tables.py`
additionally drops and recreates `public`, runs `upgrade()` through Alembic's `Operations`,
and compares the result against `core/memory/tables.py` column-for-column, plus
`format_type()` = `vector(1536)` and the HNSW/`vector_cosine_ops` index definition.

## 5. Recall in the turn

`tests/integration/test_memory_in_the_turn.py` runs the governed turn from
`test_governed_turn.py` with one seam swapped (module-level `memory` fixture overrides the
conftest fake). Evidence is taken at two depths because only one of them is a fact about the
assistant: (1) the durable trace — stage 3 `memory_retrieved` with `items: 1, degraded: false`;
(2) the prompt — the recalled content actually present in the analysis call as
`[recalled memory] …`. A trace saying "1 item" with nothing in the prompt would be a turn that
*logged* remembering; (1) alone cannot tell the two apart. Plus a turn-level leak probe and a
turn-level degrade (real dead database → `degraded: true`, `outcome: "ok"`).

## 6. Counts

| Leg | Result |
| --- | --- |
| Baseline (`V2` @ 6280f48) | 955 passed, 4 skipped |
| No Postgres | **979 passed, 47 skipped** (43 of mine skip loudly, naming the variable) |
| With Postgres | **1071 passed, 4 skipped** |

Both legs run twice, green both times. No SQLite fallback for the memory suite, deliberately:
a vector search SQLite cannot run would be green against nothing.

## 7. Live-unproven, and other honest residuals

1. **`GatewayEmbedder` is config-complete but live-unproven.** No embedding credential exists on
   this machine. Request shape, width validation and failure translation are tested against a
   mock transport; an actual LiteLLM round-trip is not. The default is `hashing`.
2. **`hashing` recall is LEXICAL, not semantic** — bag of words into 1536 buckets, cosine-ranked.
   No synonyms, no paraphrase. Honest for a test double and a keyless deployment; it is not what
   "semantic memory" means, and the default should be flipped to `gateway` once a key exists.
3. **Embedding calls do not appear in SUNIL's `llm_calls`.** C3 §2's bullet says embeddings
   inherit "routing, budgets and audit" from the C2 gateway. Routing and budgets they do (they
   go through LiteLLM, which logs spend). Audit they do NOT, because the frozen C2 `LLMProvider`
   has no `embed` method and adding one is a MAJOR contract change owned by Stream B — not
   something a memory provider may do on its way past. Recorded as a real gap; closing it is a
   C2 change.
4. **`memories` has no reaper.** Expired rows (`expires_at`) are filtered out of recall, never
   deleted — a recall must not mutate the store. A sweep belongs next to the approvals sweeper.
5. **Name overlap to watch:** the new `projects` TABLE (entity schema) is distinct from
   `config/projects.yaml` (the ADR-016 registry). `MemoryScope(kind="project", id="pda")`
   resolves against the table. Worth an integration ruling if the two are ever meant to be one.
6. **Scope-resolution is built but not yet wired into `MemoryService`.** `EntityResolver` is
   tested standalone; hooking it into the service changes that class's constructor, and the
   brief pinned "the memory service unchanged in shape". A follow-up.
7. **Outside my stated file list, and why:** `sunil/db/autogenerate.py` (the five tables must be
   fenced or the next autogenerate DROPs them — the migration is not safe without it),
   `sunil/main.py` (one line, to pass the application engine to the seam) and `.env.example`
   (the committed value had to stop naming an unbuilt provider). Flagged for the DM.

## 8. Local verification recipe

Throwaway Postgres, loopback-published, password generated into the environment and never
written to the repo:

```
docker run -d --name sunil-mem-testpg -e POSTGRES_PASSWORD="$PW" -e POSTGRES_USER=sunil \
  -e POSTGRES_DB=sunil_mem -p 127.0.0.1:5435:5432 pgvector/pgvector:0.8.6-pg17
export SUNIL_TEST_DATABASE_URL='postgresql+psycopg://sunil:$PW@127.0.0.1:5435/sunil_mem'
python -m pytest -q            # from apps/api
```

Without the variable the memory suite skips and says exactly which variable to set.
