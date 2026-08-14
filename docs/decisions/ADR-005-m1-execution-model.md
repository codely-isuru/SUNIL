# ADR-005 — M1 executes the turn in-request on the event loop: no queue, no worker, no Redis

**Status:** Proposed (Gate 2) · **Date:** 2026-08-14 · **Decider:** Solution Architect
**Context refs:** `ROADMAP.md` §4 (Redis, background workers), §14 Epic 1, §23 Step 1,
`docs/ARCHITECTURE_V1.md` §3.2/§14, FR-020, NFR-060/072, `docs/ENVIRONMENT.md` §5.

## Context

FR-020 requires the chat endpoint to return SUNIL's full answer **in the same request/response
cycle**. `ROADMAP.md` §4 and §23 Step 1 list Redis and a background job queue as V1 foundation
technology. There is no Redis on this machine and the Docker daemon is down.

A turn is **two logical LLM stages** (ADR-015) — planning and analysis, each of which may take up to
three provider attempts — plus one tool call: **7.5–17.5 s nominal**, bounded by the 40 s turn
deadline, against a ≤30 s p95 target (ADR-000 Q5, `ARCHITECTURE_V1.md` §5).
*Amended 2026-08-14: this line originally read "three LLM calls … 11–24 s expected". Both figures
changed with ADR-015 and A-2; the decision below is unaffected — a long synchronous turn is still a
synchronous turn.*

## Decision

**M1 runs the whole turn inside the HTTP request handler**, on the asyncio event loop, in a single
uvicorn worker. No Celery, no ARQ/RQ, no Redis, no separate worker process.

Redis is declared in `infra/docker/docker-compose.yml` behind a **non-default `queue` profile**, so it
exists for M10's scheduler without being started or depended on now.

## Rejected alternatives

| Rejected | Why |
|---|---|
| **Celery/ARQ + Redis, POST returns 202 and the client polls** | Directly contradicts FR-020 (answer in the same response), requires Redis (absent, Docker down), adds a second process to run and debug, and would force QA to rewrite the exit tests they are writing now. Real cost, no M1 benefit. |
| **`BackgroundTasks` / `asyncio.create_task` with the POST returning immediately** | Same FR-020 contradiction, plus an orphaned task whose failure nobody observes. |
| **A thread pool per turn** | The work is entirely I/O-bound; threads add nothing but a place for a blocking call to hide. |
| **In-process queue (`asyncio.Queue`) with a background consumer** | All the indirection of a queue with none of the durability, and it breaks the synchronous response contract anyway. |
| **Starting Redis anyway "because the roadmap says so"** | §4 is explicitly "recommended starting technologies, not permanent restrictions". Standing up infrastructure nothing uses is cost without capability — and here it would also put a stopped Docker daemon back on the critical path. |

## Consequences

- Together with ADR-001 and ADR-013, **M1 needs no containers at all.** The Docker blocker in
  `docs/STATUS.md` §4 stops being a schedule risk.
- **Debt D-1:** the in-process `TraceBus` (SSE, ADR-009) requires `--workers 1`. If the API is ever
  run multi-worker, progress events break silently. The fix is Redis pub/sub, owed at M10 when Redis
  arrives for the scheduler anyway.
- NFR-072 (crash mid-workflow leaves a queryable task) is only partially satisfied: a crash mid-turn
  leaves the task in `in_progress` forever. NFR-072 is tagged **M4** in the SRS, so this is in scope
  as written; M4 adds a startup sweep that fails orphaned tasks.
- A 20–30 s HTTP request is unusual but correct here: single user, localhost, no proxy in the path.
  Uvicorn applies no request timeout by default; `--timeout-keep-alive` governs idle keep-alive only.
