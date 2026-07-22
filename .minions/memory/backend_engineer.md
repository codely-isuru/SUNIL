# Memory — Backend / Integration Engineer (backend_engineer)

## Lessons

- [L-002 | 2026-07-21 | SUNIL Phase 1 T4] **LESSON:** Exit test ET-4 (queue survives restart)
  initially PASSED FOR THE WRONG REASON — it counted job-execution rows left over from an earlier
  run rather than the run under test. Self-caught and fixed by scoping every count to the run
  window. **ROOT CAUSE:** Assertions were written against table totals rather than against the
  window of the behaviour being tested, so pre-existing state looked like evidence.
  **RULE:** A durability or persistence test must scope every assertion to the run window.
  Pre-existing rows are never evidence. This is the exact false-proof the Solution Architect
  warned about — treat any restart/durability test that passes first time as suspect until you
  have shown it can fail.

## Conventions

Issued by the Solution Architect (Fable) at SUNIL Phase 1 Gate 2. These are
load-bearing: violating one is a review failure, not a style disagreement.

- **`@node-rs/argon2`, never node-gyp `argon2`.** The node-gyp variant breaks Windows
  builds (no prebuilt binaries). Introducing ANY node-gyp dependency requires a new ADR.
- **Every mutation goes through `UnitOfWork.runAudited`.** An ad-hoc `prisma.$transaction`
  bypasses audit-before-commit, and the runtime coverage tally will throw. Gate 1 decided a
  failed audit write FAILS the request — that guarantee is structural, not advisory.
- **BullMQ: `upsertJobScheduler` with stable ids only.** The legacy `repeat` option is
  BANNED — it silently creates duplicate schedule definitions across restarts, which is
  exactly what exit test 4 exists to catch.
- **Redis `noeviction` + the AOF flags are load-bearing, not tuning.** Do not "optimise"
  them. They are what makes the durability claim true.
- **Zod is imported only via the `packages/core` re-export.** A second Zod major anywhere in
  the tree splits schema types across workspaces.
- Default deny is structural: an undeclared route is 403 at runtime AND a named build
  failure. Do not add a route without declaring its permission.
- Secrets never leave `SecretStore` as raw strings — `SecretValue` serialises to
  `[REDACTED]`. APIs never return a stored secret.
- UUIDv7 primary keys; `externalId` unique-index convention is defined but dormant in Phase 1.
- `prototype/` is READ-ONLY. It is the design reference and origin of the product.

## Conventions established by T1 (the scaffold) — binding on every later task

- **Import Prisma from `@sunil/db`, never `@prisma/client`.** Enforced by an ESLint rule, a
  dependency-cruiser rule, AND pnpm strict linking — it will not even resolve.
- **`TransactionClient` deliberately has no `$transaction`**, so nesting is a type error, and
  `$transaction` outside `unit-of-work.ts` is a lint error. `runAudited(spec, fn)` accepts
  `(result, tx) => AuditEntry | AuditEntry[]` so you can reference rows created inside the
  transaction — that is how the privilege-reduction hook is implemented.
- **`auditLog` is unreachable outside `AuditService`.** New audit verbs go in `AUDIT_ACTIONS`
  in `@sunil/core`; `AuditEntrySchema` rejects an uncatalogued action at runtime.
- **`packages/ui` may import only `@sunil/core/types` and `@sunil/core/tokens`** — the fence
  that keeps Zod out of the client bundle. Importing the package root fails `lint:deps`.
- **Install nothing.** The lockfile belongs to T1 and already carries every Phase 1 dependency.
  A concurrent `pnpm add` corrupts `pnpm-lock.yaml`. Ask instead.
- **Never regenerate or squash the initial migration** — it carries hand-written SQL Prisma
  cannot express (vector extension, `one_owner_only` partial index, audit append-only trigger).
  Add a new migration.
- Do not redefine what `@sunil/core` already exports: `PERMISSIONS` (21), `SEED_ROLES`,
  `ROLE_IDS`, `AUDIT_ACTIONS`, the nine envelope schemas, `AgentConfigSchema`, the LLM schemas,
  `estimateCostUsd`, `redact`/`PINO_REDACT_PATHS`, `QUEUE_NAMES`/`SCHEDULER_IDS`, `parseEnv`,
  `SecretValue`, the `SecretStore` interface, the error taxonomy.
- **Prove fences, don't trust them.** T1 wrote deliberate violating imports, confirmed each was
  rejected, then removed them. Do the same for any new structural guarantee.

## Preferences

- Phase discipline is enforced at review: anything resembling chat, model routing, tasks or
  memory retrieval is Phase 2 and will be rejected regardless of quality.
- Claims are backed by real command output. "Tests pass" without counts, or a durability claim
  without a real restart, is treated as unverified at review.
