# ADR-001 — PostgreSQL is the V1 target; SQLite is the M1 default

**Status:** Proposed (Gate 2) · **Date:** 2026-08-14 · **Decider:** Solution Architect
**Context refs:** `docs/ENVIRONMENT.md` §3–§5, `docs/ARCHITECTURE_V1.md` §7, `ROADMAP.md` §4/§13,
SRS Q8 (explicitly deferred to the Architect), FR-002.

## Context

`ROADMAP.md` §4 names PostgreSQL + pgvector as the V1 data layer. The environment survey found that
this machine has **no native PostgreSQL, no Redis, and a Docker daemon that is not running**. M1 is
due **2026-08-17**. Starting Docker is a two-second human action, but it has not happened, and the
build lane cannot be gated on it.

M1's data requirements are modest and known: ten tables, no similarity search, no concurrency beyond
one user, no partitioning, no extensions. FR-143 (vector embeddings) is COULD/M7.

## Decision

**One schema, two engines, selected by `DATABASE_URL`.**

- **PostgreSQL 17 + pgvector is the V1 target** and the engine the system will be verified on before
  Gate 3. `infra/docker/docker-compose.yml` is authored in M1 with `pgvector/pgvector:pg17`.
- **SQLite (`sqlite+aiosqlite`) is the M1 default** for development, the test suite and the exit-test
  run. `DATABASE_URL=sqlite+aiosqlite:///./var/sunil.db`.
- Portability is protected by hard column rules (`ARCHITECTURE_V1.md` §7.2): text UUIDs, no native
  enums, no server-side defaults, `sa.JSON().with_variant(postgresql.JSONB, "postgresql")`, UTC
  datetimes, and **money as `BigInteger` micro-USD** rather than `Numeric` (which is lossy and warns
  on SQLite).

## Rejected alternatives

| Rejected | Why |
|---|---|
| **PostgreSQL only, wait for Docker** | Puts a human action nobody has taken on the critical path of a three-day milestone. The correct answer to "a service is down" is not "the team idles". |
| **SQLite only for all of V1** | M7's pgvector, M10's scheduler concurrency and any future multi-process deployment all need Postgres. Committing to SQLite would buy three days and cost a migration later. |
| **Two divergent schemas (SQLite dev, Postgres prod)** | Guarantees drift and a class of bug that only appears in the environment you cannot debug. One schema or none. |
| **An embedded Postgres wheel (`pg-embedded`-style)** | Adds an unverified dependency with a native build step on Windows, to solve a problem SQLite already solves. |
| **Document store (Mongo) / JSON files** | The data is intrinsically relational (six tables join on `request_id`), and ET-2/ET-4/ET-6/ET-9 are all written as queries. |

## Consequences

- Docker leaves M1's critical path entirely (with ADR-005 and ADR-013).
- **Debt D-2:** the Alembic migration is verified on SQLite only until someone runs it once against
  real PostgreSQL. That must happen before Gate 3, and it is the accepted risk of this decision.
- **Debt D-7:** the SQLite file holds conversation content and prompts, unencrypted, in `var/`.
  `var/` is gitignored; encryption at rest is M11.
- Any future column must obey §7.2's portability rules or it silently breaks one engine.
