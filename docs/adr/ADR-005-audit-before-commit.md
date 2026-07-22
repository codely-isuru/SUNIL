# ADR-005 — Audit-before-commit transaction strategy

_Status: Accepted (implements the Gate-1 decision on Q3) · Owner: Solution Architect ·
Phase: 1_

## Context

Gate 1 decided: **a failed audit write FAILS the request** for security-relevant mutations —
an unauditable mutation contradicts SECURITY_MODEL §9. FR-050/051 additionally require:
server-generated timestamps the caller cannot override, an audit record for every mutating
endpoint (machine-enforced coverage, ET-3), and audit records for *denied* requests. The open
design question was where the audit write sits relative to the domain write, and how coverage
is enforced structurally.

## Decision

1. **Same-transaction, last-write.** Every security-relevant mutation runs inside one Prisma
   interactive transaction via a `UnitOfWork.runAudited(auditSpec, fn)` helper. The helper
   executes the domain writes, then appends `AuditService.record(tx, …)` as the final write,
   then commits. Audit-insert failure ⇒ rollback of everything ⇒ 500 with a generic body.
   The mutation and its audit record are atomic — neither exists without the other.
2. **Denials are the deliberate asymmetry.** 401/403/CSRF/429/lockout responses carry no
   domain mutation; `AuditService.recordDenial` writes the single `FAILURE` record outside a
   transaction. If that write itself fails, the denial still stands (default deny is never
   weakened to preserve a log line) and a `fatal` log with the correlation id raises an
   operational alert. The Gate-1 rule protects mutations from being unaudited; it does not
   convert audit-storage failure into an authorisation bypass.
3. **Coverage enforced at two times.** Build time: a route-enumeration test asserts every
   POST/PUT/PATCH/DELETE handler carries `@Audited('<action>')`, failing with the offender's
   name (ET-3 3.2 negative control). Run time (dev/test): a request-scoped tally via
   `AsyncLocalStorage` asserts ≥1 audit record was written for the request's correlation id
   after each successful mutating response.
4. **Structural fences.** `prisma.auditLog.create` is callable only inside `AuditService`
   (dependency-cruiser path rule) so timestamps and redaction cannot be bypassed; append-only
   is enforced by both a Prisma client extension and a database trigger (belt and braces —
   FR-052).

## Rejected alternatives

- **Write-ahead audit (audit row committed in its own transaction before the mutation).**
  Guarantees a record exists even if the mutation fails — but produces audit records for
  mutations that never happened (misleading evidence) and needs a reconciliation state
  machine (`pending`/`confirmed`) that Phase 1's requirements do not ask for. Same-transaction
  atomicity gives strictly truer records with less machinery.
- **Post-commit async audit (queue/outbox).** Maximises throughput, but a crash between
  commit and audit write silently violates the Gate-1 rule — the exact behaviour the human
  rejected.
- **Fail-open with a fallback log file.** An unauditable security mutation succeeding
  contradicts SECURITY_MODEL §9 and the Gate-1 decision; a file outside Postgres escapes the
  append-only and query guarantees.
- **Database triggers generating audit rows automatically.** Captures row deltas but cannot
  know actor, correlation id, denial category or request context — the fields that make the
  log usable; and it hides the audit contract from code review.

## Consequences

- Every mutation costs one extra insert inside its transaction — negligible at Phase 1 scale
  and well inside NFR-006's 300 ms p95 budget.
- Engineers must use `UnitOfWork` for mutations (warning §18.2 in the architecture doc); the
  run-time tally makes forgetting it loud in dev, the enumeration test makes it a build
  failure.
- ET-3 is provable exactly as specified, including the negative control and the denial-path
  records.
