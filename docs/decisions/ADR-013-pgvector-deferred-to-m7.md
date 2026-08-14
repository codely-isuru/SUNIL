# ADR-013 — No vector column and no pgvector in M1; memory embeddings arrive with M7

**Status:** Proposed (Gate 2) · **Date:** 2026-08-14 · **Decider:** Solution Architect
**Context refs:** `ROADMAP.md` §4, §13, §14 Epic 9, `docs/ARCHITECTURE_V1.md` §7.5,
FR-140/143/144, NFR-009, ADR-001.

## Context

`ROADMAP.md` §4 and §13 name PostgreSQL + pgvector as the memory substrate, and §14 Epic 9 lists
vector embeddings and RAG retrieval. The SRS grades that: **FR-143 (vector embeddings / RAG) is
COULD, milestone M7.** M1's memory requirement is FR-140 (current conversation as short-term memory)
and FR-144 (every memory write records its source).

M1 therefore writes exactly one memory type, `short_term`, and performs **zero** similarity searches.

## Decision

- The `memories` table ships in `0001_initial` with `type`, `content`, `source_request_id`,
  `source_task_id`, `relevance` (nullable, unused) and a **non-null `sensitivity`** (NFR-009).
- **There is no `embedding` column in M1**, and the pgvector extension is not created.
- `infra/docker/docker-compose.yml` uses the `pgvector/pgvector:pg17` image, so when Docker comes up
  the extension is available and M7 is `CREATE EXTENSION vector;` plus one additive migration — not
  an image swap.

## Rejected alternatives

| Rejected | Why |
|---|---|
| **Add a nullable `embedding vector(1536)` column now** | Makes the schema Postgres-only, which contradicts ADR-001's SQLite-for-M1 decision and puts the stopped Docker daemon straight back on M1's critical path — to store nothing. |
| **Store embeddings as a JSON array of floats, portable across both engines** | Works for storage and is useless for search (no index, no distance operator), so it would have to be migrated to a real vector type anyway. Two migrations instead of one. |
| **A separate vector store (Chroma / Qdrant / FAISS)** | A second datastore, a second consistency problem and a second thing to run, for a capability M1 does not have. Reconsider at M7 only if pgvector proves inadequate — the roadmap's own §13 recommends PostgreSQL + pgvector. |
| **Choose the embedding model and dimension now, so the column can be sized** | Choosing it now means choosing it without the M7 retrieval requirements that should drive it. Deciding late is cheap here precisely because M1 stores nothing. |
| **Skip the `memories` table entirely in M1** | FR-140 and FR-144 are MUST/M1 — short-term memory must be written with its source. The table is required; only the vector column is not. |

## Consequences

- Together with ADR-001 and ADR-005, M1 needs **no containers at all**, which is what removes the
  Docker blocker from the milestone.
- M7's migration is purely additive: add the column, create the extension, backfill nothing (there is
  nothing to backfill, because M1 stores no long-term memory).
- `memories.relevance` and `memories.type`'s four unused enum values are schema-ready and inert. The
  threat model records that an empty table is not evidence of a working control.
- NFR-009 is satisfied at the level the SRS asks for in M1: the `sensitivity` field is present and
  non-null on every write. Routing enforcement based on it is V2 and is not claimed anywhere.
