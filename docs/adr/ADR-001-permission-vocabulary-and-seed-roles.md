# ADR-001 — Permission vocabulary and seed roles (routed question Q4)

_Status: Accepted · Owner: Solution Architect · Phase: 1_

## Context

RBAC requires permissions as data rows, routes declaring them, default deny (FR-025/026,
NFR-001). The BA deferred the permission-string scheme, the seed role set and the
single-owner question to the Solution Architect (requirements §8 Q4; risk R-08 warns that an
ad-hoc vocabulary forces a painful Phase 2 renaming pass). The BA's straw man: roles `owner`,
`admin`, `viewer`, `agent`. The requirements say the owner "carries every permission
including `*:admin`-class grants" — which could be read as requiring wildcard grammar.

## Decision

1. **Vocabulary:** flat, lowercase **`resource:action`** strings (`user:invite`,
   `secret:rotate`). Dot-namespacing inside a segment is reserved for future sub-resources
   (`email.account:read`) but unused in Phase 1. The Phase 1 catalogue is exactly the 21
   strings in `PHASE1_ARCHITECTURE.md` §7.1, defined once as constants in `packages/core`.
2. **No wildcard grammar at runtime.** Permissions are concrete rows; the guard is a set
   membership test. The owner's "every permission" is delivered by the idempotent seed
   re-granting **all known permissions** to the `owner` role on every run — so new
   permissions added in later phases flow to owner via the seed, not via a matcher.
3. **Seed roles:** `owner` (all 21), `admin` (all except `role:assign`; service invariant:
   may never target the owner account), `viewer` (`dashboard:read`, `audit:read`), `agent`
   (none; non-human audit principal, no login path). System roles get fixed deterministic
   UUIDs (`00000000-0000-7000-8000-00000000000{1..4}`) so migrations and indexes can
   reference them.
4. **Exactly one `owner` in Phase 1 — confirmed**, enforced at three layers: (a) bootstrap
   is the only creation path and is idempotent; (b) `RoleAssignmentService` refuses to grant
   `owner` (and invitations exclude it); (c) a partial unique index
   `ON user_roles (role_id) WHERE role_id = '<owner-uuid>'` rejects a second assignment at
   the database even if application checks are bypassed.

## Rejected alternatives

- **Runtime wildcard matching (`*:*`, `user:*`).** More elegant on paper, but it introduces a
  matching engine whose bugs are privilege-escalation bugs, makes "default deny" harder to
  reason about, and complicates ET-2 2.5 (grant-by-DB-row proof). A set test cannot be wrong.
- **Hierarchical/inherited roles (admin ⊂ owner structurally).** Inheritance chains hide
  effective permissions; the requirements only need *set* superset relationships, which the
  seed data provides explicitly and ET-2 verifies.
- **Per-route scopes minted ad hoc by engineers.** Exactly the R-08 failure mode; forbidden —
  new permission strings require an architect-reviewed addition to the `core` catalogue.
- **Multiple owners / owner as a flag on User.** Contradicts the single-principal security
  model (SECURITY_MODEL §1) and the BA's persona model; role-based single-owner keeps one
  RBAC mechanism for everything.

## Consequences

- The guard is trivially auditable; ET-2's data-driven proof works unmodified.
- The seed must be re-run whenever the permission catalogue grows (documented in the seed
  script header); forgetting it leaves owner without a new permission — fail-closed, visible.
- Phase 2's much larger surface extends the catalogue without renaming anything.
- The partial unique index depends on the fixed owner-role UUID — renaming/re-keying system
  roles is a migration-level change, deliberately expensive.
