# ADR-035 — Machine callers authenticate with a route-scoped bearer token on the chat endpoint only

**Status:** Proposed (Architect, V2 Phase 0) · **Date:** 2026-09-10 · **Decider:** Solution Architect
**Fixes an open point in:** `V2_DEVELOPMENT_PLAN.md` Stream E ("trigger workflows calling C5") —
n8n cannot hold a signed browser session cookie, and no machine authentication existed anywhere in
the plan or in M1 (ADR-007 is single-owner browser auth).
**Context refs:** ADR-007 (owner session), ADR-008 (cookie + `X-SUNIL-Client` CSRF pair), contract
C5 §2.3, ADR-032 (n8n at `127.0.0.1:5680` *[was `:5678`; ADR-032 Amendment 1, 2026-09-10]*).

## Context

Phase V2-E has n8n starting governed turns ("morning brief" etc.) via `POST /api/v1/chat`. The only
existing credential is the owner's session cookie — obtainable only by scripting a login flow and
storing the owner's password in n8n, which violates the credential rule (agents/workflows hold
nothing of SUNIL's).

## Decision

A second authentication lane, deliberately minimal:

- `SUNIL_SERVICE_TOKEN` (SecretStr, ≥ 32 random bytes, no default — unset means the lane is OFF and
  only the cookie lane exists). Callers send `Authorization: Bearer <token>`; comparison is
  constant-time (`secrets.compare_digest`).
- **Structurally scoped to one route:** the bearer dependency is registered on
  `POST /api/v1/chat` and nowhere else. Approvals, memory, conversations, auth — every other route
  keeps the cookie+header pair exclusively. No token value can reach them, because no other route
  has code that reads the header (the same "not an input to the excluded population" shape as
  ADR-033's lane flag).
- Turns started on this lane run as the owner's principal for permissions (V1 is single-owner) but
  are recorded distinctly: audit rows carry `channel="service"` and the request's `channel_label`
  (e.g. `n8n:morning-brief`), so "which automation did this" is a database fact.
- The CSRF pair is not required on this lane (no browser, no cookie, nothing for CSRF to ride);
  Origin checks do not apply. 401 on bad/missing token; the lane never returns 403.
- n8n stores the token in its own credential vault (ADR-030 rule) and reaches the API at
  `http://localhost:8000` (host n8n→host API via the published loopback port; `http://api:8000`
  in the full profile).

## Rejected alternatives

| Rejected | Why |
|---|---|
| **Script the owner login from n8n (reuse ADR-007)** | Puts the owner's password in n8n's vault, ties automations to password rotation, and makes n8n indistinguishable from the owner in audit. |
| **Full OAuth2 client-credentials / JWT service identities** | One machine caller exists (n8n), single-owner system, all loopback. A token-issuer, expiry/refresh plumbing and key rotation ceremonies serve a multi-tenant future that ADR-000's scope explicitly defers. The seam (a FastAPI dependency) is where JWTs would slot in later without contract change. |
| **mTLS between n8n and the API** | Certificate lifecycle for two processes on one machine's loopback; disproportionate, and n8n's HTTP-request node makes custom CA handling a per-workflow footgun. |
| **IP allow-listing (accept loopback callers unauthenticated)** | Every process on the dev machine becomes an authorised turn-starter; indistinguishable callers in audit; breaks the moment n8n moves off-host. |
| **Scope the token by config list of allowed routes** | A config edit could widen it silently. Route registration in code is the scope — widening it is a reviewed code change (the ADR-033 argument, reapplied). |

## Consequences

- C5 documents the lane (securityScheme `serviceToken`); contract test 5 probes the structural
  scope (same token against `GET /api/v1/approvals` must 401).
- Rotation is an env change + restart of two things (API, n8n credential entry).
- When multi-user or off-host automation arrives, this ADR is superseded by a real service-identity
  decision; the audit `channel`/`channel_label` fields are forward-compatible with that.
