# ADR-004 — ORM: Prisma 6 confirmed

_Status: Accepted (confirmation of an existing architecture decision) · Owner: Solution
Architect · Phase: 1_

## Context

`SUNIL_ARCHITECTURE.md` §1 already selects PostgreSQL 16 + Prisma. This ADR confirms the
choice against Phase 1's specific demands rather than re-litigating it: interactive
transactions for audit-before-commit (ADR-005), migration discipline (FR-015), an
append-only guard on `audit_logs` (FR-052), pgvector coexistence (FR-010), and Windows 11
developer experience (NFR-017).

## Decision

**Prisma 6.x**, with these Phase 1 usage rules:

- `packages/db` owns the schema, migrations, and the **exported client**, which is wrapped in
  client extensions (audit append-only guard; future guards). Apps never import
  `@prisma/client` directly (dependency-cruiser fence).
- Interactive transactions (`$transaction(async tx => …)`) are the audit-before-commit
  vehicle; services accept a `TransactionClient`.
- Raw SQL is allowed **only inside migration files** (partial unique index, append-only
  trigger, `CREATE EXTENSION vector`) and never in application code without architect review
  (SECURITY_MODEL §8).
- `@default(uuid(7))` for PKs (requires Prisma ≥5.19 — satisfied).
- pgvector: the extension is enabled by migration; **no Prisma model carries a vector column
  in Phase 1** (A-05) — Phase 2 will use `Unsupported("vector")` or raw queries as its own
  decision.

## Rejected alternatives

- **Drizzle ORM.** Excellent SQL-first control and lighter runtime, but its migration story
  (drizzle-kit) is less mature for the strict "a migration for every change, no drift"
  regime FR-015 demands, and it lacks Prisma's client-extension seam we use for the
  append-only guard. Re-deciding the architecture doc's choice needs a stronger reason than
  taste.
- **TypeORM.** Long-standing decorator/entity model with a history of subtle
  transaction/relation bugs and drifting maintenance; weakest option for schema-drift
  guarantees.
- **Kysely (query builder only).** Type-safe SQL but no migration/schema management or model
  layer — we would rebuild half of Prisma around it.
- **Raw `pg` + hand-written SQL.** Maximum control, maximum review surface; contradicts
  SECURITY_MODEL §8's "parameterised queries via Prisma (no raw SQL without review)".

## Consequences

- Engine binaries download at install: `prisma`/`@prisma/engines` are entries in the pnpm
  `allowBuilds` allowlist (formerly `onlyBuiltDependencies`; supply-chain control,
  THREAT_MODEL T-16).
- `prisma migrate deploy` is the container entry step for `api` (idempotent, NFR-009);
  `migrate dev` is host-side only.
- The append-only trigger and partial unique index live as raw SQL appended to the initial
  migration — engineers must not regenerate/squash that migration without preserving them
  (called out in `packages/db` README header).
