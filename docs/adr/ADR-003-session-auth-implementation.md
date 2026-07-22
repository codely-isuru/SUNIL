# ADR-003 — Session-auth implementation (routed question Q8)

_Status: Accepted · Owner: Solution Architect · Phase: 1_

## Context

`SUNIL_ARCHITECTURE.md` §1 specifies "Session-based (Lucia-style)" — a style, not a
dependency. FR-022–FR-024 are behavioural and library-agnostic: server-side session rows,
revocation markers, idle (8 h) + absolute (24 h) expiry, secure cookies, and — per Gate 1 —
privilege reduction must revoke sessions inside the same transaction as the role change.
Materially: **Lucia v3 was deprecated by its author (2025) and converted into a learning
resource** ("The Copenhagen Book" pattern documentation). The API is NestJS on the Fastify
adapter; the session table is part of our Prisma schema and feeds the audit layer.

## Decision

**Hand-roll the session state machine; never hand-roll the primitives.**

- A `SessionService` in `apps/api` implements the documented Lucia/Copenhagen-Book pattern:
  opaque 256-bit random token in the cookie; server stores only its SHA-256 hash; states
  `PENDING_MFA → ACTIVE → REVOKED`; sliding idle expiry + fixed absolute expiry; token
  rotation on MFA elevation (anti-fixation). Full mechanics in `PHASE1_ARCHITECTURE.md` §6.
- Vetted libraries for every primitive: **`@node-rs/argon2`** (argon2id, OWASP parameters,
  prebuilt N-API binaries — no node-gyp on Windows) for password hashing; **`otpauth`**
  (pure JS, RFC 6238) for TOTP; Node `crypto` for randomness and hashing. No bespoke
  cryptography exists anywhere in the design.

## Rejected alternatives

- **Lucia (the library).** Deprecated/unmaintained; pinning the security core of a
  multi-phase platform to it is indefensible. Its *pattern* is exactly what we implement.
- **Auth.js / NextAuth.** JWT-centric with session-DB support bolted on; oriented to Next.js,
  while our auth authority is the NestJS API. Server-side immediate revocation, PENDING_MFA
  states, and audit-before-commit hooks all fight the framework. Registration/OAuth surface
  we must disable is attack surface we'd carry.
- **better-auth.** Capable and current, but it wants to own the auth tables, routes and
  flows; bending invitation-only registration, our Prisma schema ownership, the Gate-1
  transactional revocation rule and audit-before-commit through its plugin system is more
  integration risk than a few hundred lines of well-specified, crypto-free state-machine
  code — and its release velocity makes it a moving dependency under our security core.
- **Passport + fastify session plugins.** Passport's strategy abstraction adds nothing for a
  single credential type; the session store, revocation semantics and MFA states would still
  be hand-managed — all cost, no coverage.
- **The classic `argon2` (node-gyp) package.** Build-toolchain requirement on Windows 11
  hosts violates NFR-017 and risk R-03; `@node-rs/argon2` ships prebuilt win32-x64 and
  linux-x64-musl binaries.

## Consequences

- Full control over every ET-1 behaviour; no framework seams to work around; the session
  table participates in audited transactions natively (Gate-1 revocation hook, §6.6).
- We own the correctness of the state machine — mitigated by: the pattern being publicly
  documented and reviewed (Copenhagen Book), ET-1's eleven-step behavioural suite, and the
  independent security review (BL-901) explicitly covering session mechanics.
- No OAuth/social login exists; when Phase 3 needs Microsoft Graph OAuth it is an
  *integration* credential flow through `SecretStore`, not a user-login concern — this ADR
  does not constrain it.
