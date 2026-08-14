# ADR-007 — Single-owner authentication: signed-cookie session + stdlib `scrypt`

**Status:** Proposed (Gate 2) · **Date:** 2026-08-14 · **Decider:** Solution Architect
**Context refs:** ADR-000 Q3 (settled: single-user local session), SRS §3, FR-007,
`docs/ARCHITECTURE_V1.md` §9.6, ADR-008.

## Context

ADR-000 Q3 settled the *policy*: one human user, no signup, no RBAC, no tenancy, `user_id` still
threaded through the schema. It explicitly left the *mechanism* to this ADR (SRS Q3: "the session
mechanism itself … is a technical choice").

FR-007: the chat endpoint must reject an unauthenticated request and accept an authenticated one.
That is the whole requirement.

## Decision

- **Login:** `POST /api/v1/auth/login {username, password}`. Also `POST /auth/logout`,
  `GET /auth/session`.
- **Password hashing: stdlib `hashlib.scrypt`** — `n=2**14, r=8, p=1, dklen=32`, 16-byte random salt,
  stored as `scrypt$n$r$p$salt_b64$hash_b64`, compared with `hmac.compare_digest`. Verified working
  on this machine's Python 3.13.14.
- **Session:** Starlette `SessionMiddleware` — a signed (not encrypted) cookie via `itsdangerous`.
  `HttpOnly`, `SameSite=Lax`, `Path=/`, `max_age=86400`, name from `SESSION_COOKIE_NAME`, key from
  `SESSION_SECRET`. The cookie carries only `{"user_id": …}` — no secrets, no PII.
- **Throttle:** 5 consecutive failures → 60 s lockout, in memory, keyed by username.
- **Seeding:** `scripts/seed-owner.py` reads `OWNER_USERNAME`/`OWNER_PASSWORD` from the environment.
  **No signup endpoint exists** — an endpoint that can create a second owner is a bigger risk than
  the convenience is worth.

## Rejected alternatives

| Rejected | Why |
|---|---|
| **JWT in `localStorage`** | Readable by any XSS, and unrevocable before expiry. For a system that can call tools on the owner's behalf, a token an injected script can read is the wrong default. |
| **JWT in an HttpOnly cookie** | Removes the XSS read, but keeps unrevocability and adds signing/refresh machinery to solve a problem (statelessness across many servers) that a single-user localhost app does not have. |
| **Server-side session table with an opaque token** | Strictly better on revocation and would be the right call for V1-hosted. Rejected for M1 only: ~40 more lines plus a table plus expiry sweeping, for a revocation capability with exactly one user and no remote exposure. Recorded as **debt D-3**, owed at M5. |
| **HTTP Basic auth** | No logout, browser-controlled credential UI, credentials replayed on every request. Also incompatible with the Designer's login-screen-shaped UX. |
| **OAuth / GitHub SSO** | Introduces an external IdP dependency and a redirect flow to authenticate a single person to their own laptop. |
| **`passlib[bcrypt]` or `argon2-cffi` for hashing** | Both are fine libraries. Rejected because `hashlib.scrypt` is in the standard library, needs no wheel, and `passlib` 1.7.4 in particular has a known incompatibility with bcrypt 4.x that produces confusing warnings. One fewer dependency on a three-day build. |
| **No auth at all in M1** | Violates FR-007, and would leave a tool-calling endpoint open to anything running on the machine. |

## Consequences

- **Debt D-3:** no server-side session revocation until M5. Changing the password does not invalidate
  an existing cookie; rotating `SESSION_SECRET` does (a one-line operational remedy, documented in
  the runbook).
- The cookie is *signed*, not encrypted — never put anything confidential in the session dict.
- The cookie's reach across `localhost` ports is a known, accepted risk analysed in
  `docs/THREAT_MODEL.md` (T-07); it is a property of how browsers scope cookies, not of this choice.
- ADR-008 depends on this: the session cookie must survive a cross-origin, same-site request, which
  is why `SameSite=Lax` (not `Strict`) and why both services must be addressed as `localhost`.
