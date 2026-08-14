# Architecture Decision Records

One decision per file. **Every ADR names its rejected alternatives — an ADR without a rejected
alternative is not an ADR.** A decision that changes an earlier decision is recorded as a *new* ADR
that supersedes it, or — where the decision survives and only part of it moves — as a dated
**amendment appended to the original**, never as a silent edit.

| ADR | Decision | Status |
|---|---|---|
| [000](ADR-000-gate-1-scope-decisions.md) | The seven Gate 1 scope decisions (owner) — settled, not reopened | Accepted 2026-08-14 |
| [001](ADR-001-database.md) | PostgreSQL is the V1 target; **SQLite is the M1 default**; one portable schema | **Accepted** (owner review 2026-08-14) |
| [002](ADR-002-orm-and-migrations.md) | SQLAlchemy 2.0 async + Alembic | **Accepted** (owner review 2026-08-14) |
| [003](ADR-003-provider-abstraction.md) | SUNIL owns the provider abstraction: `LLMProvider` protocol + capability-keyed Model Router | **Accepted** (owner review 2026-08-14) |
| [004](ADR-004-plan-validation.md) | Plan validation: constrained decoding → Pydantic → registry re-check → `ValidatedPlan` + **runtime guard** | **Accepted, amended once** (Amendment 1, 2026-08-14) |
| [005](ADR-005-m1-execution-model.md) | M1 runs the turn in-request: **no queue, no worker, no Redis** | **Accepted** (owner review 2026-08-14) |
| [006](ADR-006-secret-storage.md) | Secrets: env/`.env` as `SecretStr` + a value-registry redaction mechanism | **Accepted** (owner review 2026-08-14) |
| [007](ADR-007-authentication.md) | Single-owner auth: signed-cookie session + stdlib `scrypt` | **Accepted** (owner review 2026-08-14) |
| [008](ADR-008-frontend-api-topology.md) | Browser → FastAPI direct, cross-origin, strict CORS + mandatory client header | **Accepted** (owner review 2026-08-14) |
| [009](ADR-009-progress-events-channel.md) | M1 ships a real one-way **SSE stage-event channel** | **Accepted, amended** — T12 pre-classified **OPTIONAL / post-M1** |
| [010](ADR-010-cancel-semantics.md) | Cancel is **client-side only** in M1; the abort seam exists, unwired | **Accepted** (owner review 2026-08-14) |
| [011](ADR-011-repository-structure.md) | One installable `sunil` package under `apps/api`; `core/routing`, `core/agent_framework`, `core/tool_framework` | **Accepted** (owner review 2026-08-14, §2.2 renames explicitly approved) |
| [012](ADR-012-frontend-stack.md) | Next.js 16 + React 19 + Tailwind **pinned to 3.4.19**, pure client app | **Accepted** (owner review 2026-08-14) |
| [013](ADR-013-pgvector-deferred-to-m7.md) | No vector column and no pgvector in M1 | **Accepted** (owner review 2026-08-14) |
| [014](ADR-014-training-data-capture-policy.md) | **Training-data capture policy** — classify at capture time; `none / metadata_only / redacted_full / full_local_only` | **Accepted** (owner correction §10) |
| [015](ADR-015-m1-two-logical-llm-stages.md) | **M1 has two logical LLM stages**; the PM agent's analysis is the user-facing response | **Accepted** (owner correction §11) |
| [016](ADR-016-config-deployment-policy.md) | `config/*.yaml` is **mounted, never baked**; a change takes effect on restart | Proposed |

ADR-001 … ADR-016 are the Solution Architect's. **ADR-001 … ADR-013 were approved by the owner's
architecture review on 2026-08-14** ("approve the architecture direction after targeted
corrections"); the corrections are recorded as ADR-004 Amendment 1, the ADR-009 amendment, and the
new ADR-014/015/016. ADR-001, ADR-005 and ADR-013 are the three that together keep Docker off M1's
critical path — still true now that the daemon is running, which makes the no-Docker path a
contingency rather than a constraint.

**Amendment index** — where a decision moved after it was first written:

| Record | Amendment | Date |
|---|---|---|
| ADR-004 | Amendment 1 — "unforgeable"/"no expressible code path" withdrawn; runtime guard + `ExecutionMetadata` added; stored-plan check deferred to M5 as DC-14 | 2026-08-14 |
| ADR-005 | Context line re-stated: two logical LLM stages, 7.5–17.5 s nominal | 2026-08-14 |
| ADR-009 | T12 pre-classified OPTIONAL / post-M1; `SUNIL_PROGRESS_EVENTS` defaults `false` | 2026-08-14 |
| `ARCHITECTURE_V1.md` | Amendment log A-1 … A-9 at the head of the document | 2026-08-14 |
