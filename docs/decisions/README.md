# Architecture Decision Records

One decision per file. **Every ADR names its rejected alternatives — an ADR without a rejected
alternative is not an ADR.** A decision that changes an earlier decision is recorded as a *new* ADR
that supersedes it, never by editing the original.

| ADR | Decision | Status |
|---|---|---|
| [000](ADR-000-gate-1-scope-decisions.md) | The seven Gate 1 scope decisions (owner) — settled, not reopened | Accepted 2026-08-14 |
| [001](ADR-001-database.md) | PostgreSQL is the V1 target; **SQLite is the M1 default**; one portable schema | Proposed |
| [002](ADR-002-orm-and-migrations.md) | SQLAlchemy 2.0 async + Alembic | Proposed |
| [003](ADR-003-provider-abstraction.md) | SUNIL owns the provider abstraction: `LLMProvider` protocol + capability-keyed Model Router | Proposed |
| [004](ADR-004-plan-validation.md) | Plan validation: constrained decoding → Pydantic → registry re-check → unforgeable `ValidatedPlan` | Proposed |
| [005](ADR-005-m1-execution-model.md) | M1 runs the turn in-request: **no queue, no worker, no Redis** | Proposed |
| [006](ADR-006-secret-storage.md) | Secrets: env/`.env` as `SecretStr` + a value-registry redaction mechanism | Proposed |
| [007](ADR-007-authentication.md) | Single-owner auth: signed-cookie session + stdlib `scrypt` | Proposed |
| [008](ADR-008-frontend-api-topology.md) | Browser → FastAPI direct, cross-origin, strict CORS + mandatory client header | Proposed |
| [009](ADR-009-progress-events-channel.md) | M1 ships a real one-way **SSE stage-event channel**; it is the designated descope lever | Proposed |
| [010](ADR-010-cancel-semantics.md) | Cancel is **client-side only** in M1; the abort seam exists, unwired | Proposed |
| [011](ADR-011-repository-structure.md) | One installable `sunil` package under `apps/api`, preserving roadmap §20's decomposition | Proposed |
| [012](ADR-012-frontend-stack.md) | Next.js 16 + React 19 + Tailwind **pinned to 3.4.19**, pure client app | Proposed |
| [013](ADR-013-pgvector-deferred-to-m7.md) | No vector column and no pgvector in M1 | Proposed |

ADR-001 … ADR-013 are the Solution Architect's and land at **Gate 2**. ADR-001, ADR-005 and ADR-013
are the three that together take the stopped Docker daemon off M1's critical path.
