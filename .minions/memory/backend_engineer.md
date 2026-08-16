# Memory — Backend / Integration Engineer (backend_engineer)

> **Stack reset, 2026-08-13.** SUNIL was re-planned onto `docs/ROADMAP.md` (Python/FastAPI).
> The TypeScript/NestJS build these conventions were written for is retired and archived at
> tag `archive/v0-typescript-foundation`. The **Lessons** and **Principles** below are
> stack-independent and still binding. The TypeScript conventions are kept at the bottom under
> *Archived* — they apply ONLY if someone works on that tag, never to V1.

## Lessons

- [L-002 | 2026-07-21 | SUNIL Phase 1 T4] **LESSON:** Exit test ET-4 (queue survives restart)
  initially PASSED FOR THE WRONG REASON — it counted job-execution rows left over from an earlier
  run rather than the run under test. Self-caught and fixed by scoping every count to the run
  window. **ROOT CAUSE:** Assertions were written against table totals rather than against the
  window of the behaviour being tested, so pre-existing state looked like evidence.
  **RULE:** A durability or persistence test must scope every assertion to the run window.
  Pre-existing rows are never evidence. Treat any restart/durability test that passes first time
  as suspect until you have shown it can fail.

- [L-003 | 2026-08-14 | SUNIL M1 T4, review bounce] **LESSON:** `sunil.redaction.scrub()`'s
  original `isinstance` chain (`str`/`dict`/`list`/`tuple`, else `return obj` unchanged) let an
  exception instance, a SQLAlchemy `URL` `NamedTuple`, or any custom object pass through a
  logged/persisted field **completely unredacted**. QA demonstrated it live against the real wired
  `shared_processors` chain — `log.error("call failed", error=exc)` is ordinary structlog usage, not
  a contrived case, and the secret inside `exc`'s message reached the rendered JSON line and would
  have reached the persisted `audit_events.detail` the same way.
  **ROOT CAUSE:** A redaction/sanitisation function that dispatches on a fixed list of types treated
  the unmatched case as a passthrough default rather than as unsafe. An `isinstance` allowlist with
  a silent `else: return obj` is not a mechanism; it is a convention with extra steps, and the gap is
  exactly where a real secret survives, not an edge case.
  **RULE:** Any function whose job is "make sure X never appears in Y" must fail *closed* on a type
  it doesn't recognise — coerce the unknown shape through a safe, guaranteed-not-to-raise string
  representation and run the same scrubbing pass over that, never return it unchanged. Structural
  types that carry their own privacy-aware `__repr__` (a `NamedTuple` like `sqlalchemy.engine.URL`)
  are a second trap inside the first: recursing into them positionally (because `isinstance(x,
  tuple)` is true) bypasses that masking `__repr__` entirely by serialising the raw fields instead of
  calling it. Detect that shape (`hasattr(x, "_fields")`) and route it through the same fail-safe
  string path rather than through generic container recursion. Prove the fix the same way the
  original claim was proved: through the real configured chain and the real persistence write path,
  with an exception, a nested object, and a secret-bearing `__repr__` — not a mocked `scrub()` call.

## Principles — stack-independent, carried into V1

- **Prove fences, don't trust them.** When you build a structural guarantee (a default-deny
  route table, a permission check, an import boundary), write the deliberate violation, confirm
  it is rejected, then remove it. An unproven guarantee is a claim, not a control.
- **Claims are backed by real command output.** "Tests pass" without counts, or a durability
  claim without a real restart, is treated as unverified at review.
- **Default deny is structural, not advisory.** An undeclared route/tool/permission must fail
  closed at runtime *and* be a named build/lint failure — not a code-review convention.
- **Secrets never leave the secret store as raw strings**, never appear in logs, prompts, error
  messages or API responses. Redaction is a type-level guarantee where the language allows one.
- **Every mutation is audited before it commits**, and a failed audit write fails the request.
  This was a Gate 1 decision on Phase 1 and the roadmap restates it (§26.6) — carry it forward.
- **Install nothing unilaterally when a lockfile is shared.** A concurrent dependency add
  corrupts the lockfile for a parallel lane. Ask the Delivery Manager.
- **Never regenerate or squash an existing migration** — add a new one. Hand-written SQL
  (extensions, partial indexes, triggers) does not survive a regeneration.
- **Phase discipline is enforced at review.** Building something that belongs to a later
  milestone is rejected regardless of quality.
- `prototype/` is READ-ONLY. It is the design reference and origin of the product.

## Archived — TypeScript/NestJS conventions (tag `archive/v0-typescript-foundation` only)

Not applicable to V1. Retained because the archived branch is still buildable.

- `@node-rs/argon2`, never node-gyp `argon2` (no Windows prebuilts; any node-gyp dep needed an ADR).
- Every mutation through `UnitOfWork.runAudited`; ad-hoc `prisma.$transaction` bypasses audit.
- BullMQ `upsertJobScheduler` with stable ids only; the legacy `repeat` option was banned.
- Redis `noeviction` + AOF flags were load-bearing for the durability claim, not tuning.
- Zod imported only via the `packages/core` re-export; Prisma only via `@sunil/db`.
- `TransactionClient` deliberately had no `$transaction`; `auditLog` unreachable outside `AuditService`.
- `packages/ui` could import only `@sunil/core/types` and `@sunil/core/tokens`.
- UUIDv7 primary keys; `externalId` unique-index convention defined but dormant.
