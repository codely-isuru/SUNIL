# ADR-009 — CSRF strategy: per-session header token

_Status: Accepted (amended — see Amendment A2, `PHASE1_ARCHITECTURE.md` §19) · Owner:
Solution Architect · Phase: 1_

## Context

FR-028 requires every state-changing browser request to carry a CSRF token validated
server-side, with missing/incorrect tokens rejected 403 and audited. `SameSite=Lax` cookies
(FR-023) already block most cross-site vectors but not all (top-level navigations are Lax-
exempt for safe methods only, yet defence-in-depth is mandated). The portal is a same-origin
SPA-style Next app talking to the API with `fetch`.

## Decision

**Synchronizer token, delivered out-of-cookie, sent as a header.**

- Each session row carries a random 32-byte `csrfSecret` (rotated with the session token on
  MFA elevation).
- The client receives it in the login / MFA-verify response body and from `GET /api/auth/me`;
  it is held in client memory (not a cookie, not localStorage-persisted by the shell).
- Every POST/PUT/PATCH/DELETE must present it in `X-CSRF-Token`; a global guard
  constant-time-compares it against the session row before the permission check. Missing or
  wrong ⇒ 403, no state change, `csrf` denial audit record. Safe methods exempt (FR-028).
- Because the token is never in a cookie, a cross-site attacker gains nothing from the
  browser's automatic cookie attachment: they cannot read the token cross-origin, so they
  cannot forge a mutating request even where `SameSite=Lax` would let the cookie ride.

## Rejected alternatives

- **Double-submit cookie.** Standard, but its security reduces to cookie-write integrity
  (subdomain/cookie-tossing edge cases) and it still lands a secret in a cookie; the
  session-bound synchronizer is strictly stronger and we already own a session row to bind
  to.
- **`@fastify/csrf-protection` plugin.** Implements double-submit/signed variants; brings
  its own cookie/secret lifecycle that overlaps confusingly with our session model. Our
  guard is ~30 lines against a field we already store.
- **SameSite=Strict + Origin-header checking, no token.** Origin checks are a good ambient
  layer, but FR-028 explicitly requires a token, and header-stripping proxies/older-client
  edge cases make origin-only enforcement brittle as the sole control. **Amendment A2:** the
  belt-and-braces `Origin` validation is *not* implemented in Phase 1 — the token is the
  sole and sufficient FR-028 control; the same-origin topology (ADR-011) narrows the residual
  further, and the `Origin` check is deferred to the Phase 2 ingress/WebSocket ADR.
- **Per-request rotating tokens.** Marginal gain over per-session for an SPA, but breaks
  concurrent in-flight mutations and complicates retries; not warranted by the threat model.

## Consequences

- ET-1 1.9 is directly testable: valid cookie + missing/wrong header ⇒ 403 + audit record.
- Non-browser API clients (tests, future automation) follow the same rule — fetch
  `/api/auth/me`, echo the header; documented in the API README.
- The token lives in JS memory, so an XSS compromise could read it — XSS is separately
  controlled (CSP, no `innerHTML`, output encoding; THREAT_MODEL T-07); CSRF tokens are not
  a defence against XSS in any scheme.
