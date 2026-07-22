# ADR-011 — Browser↔API is same-origin via Next rewrite proxy; no CORS in Phase 1

_Status: Accepted (post-Gate-2 ruling on a T3 escalation; Amendment A1 in
`PHASE1_ARCHITECTURE.md` §19) · Owner: Solution Architect · Phase: 1_

## Context

`apps/web` runs on :3000 and `apps/api` on :3001 in the dev topology, so any client-side
fetch from the portal to the API is cross-origin and fails — `apps/api` ships no CORS
configuration, correctly, because §16's configuration inventory is a closed list with no
allowed-origins variable and the T3 engineer rightly refused to invent one. Server-component
fetches (cookie forwarded server-side) already work. T5 is building the portal now; the
integration path must be decided by the architect, not improvised.

## Decision

**The browser never talks to the API origin. Phase 1 adds no CORS configuration anywhere.**

- `apps/web` declares a `rewrites()` rule in `next.config`: `/api/:path*` →
  `${SUNIL_API_INTERNAL_URL}/api/:path*`. All client-side code fetches **relative**
  `/api/...` paths; the Next server proxies them on the private network.
- New configuration name: **`SUNIL_API_INTERNAL_URL`** (server-side only; default
  `http://api:3001` in Compose, `http://localhost:3001` for host-run dev). It is both the
  rewrite target and the base URL for server-component fetches.
- `NEXT_PUBLIC_API_URL` is **removed** from the configuration inventory — with same-origin
  relative paths, no API URL belongs in the client bundle.
- Consequential simplifications, now normative: cookies are first-party on a single origin
  (the `__Host-` prefix applies cleanly); CSP `connect-src` is `'self'` only; no
  `credentials: 'include'` semantics; the CSRF token flow is unchanged.
- Invitation links are constructed client-side from `window.location.origin`; no
  public-origin variable exists.
- The API's published host port remains for **non-browser** access only (QA exit-test
  suites, dev tooling) — it stays same-origin-only and returns no CORS headers.
- Any future cross-origin client (mobile app, third-party consumer) requires a new ADR;
  adding an allowed-origins variable is forbidden as a drive-by change.

## Rejected alternatives

- **CORS allowlist configuration (`SUNIL_CORS_ORIGINS`).** Workable, but strictly weaker:
  it opens a cross-origin surface that must then be re-secured (credentialed CORS
  semantics, origin-list mistakes, wider CSP), adds a config value that fails closed only
  if nobody "fixes" it with `*` under time pressure, and gives T5 *more* work (absolute
  URLs + `credentials:'include'`). Same-origin is the restrictive default; NFR-001's
  spirit applies to topology, not just routes.
- **Server-components-only data access (client-side fetch out of scope).** Login, MFA
  challenge and CSRF-bearing mutations are natural client-side interactions; forcing every
  mutation through server actions this late constrains T5's implementation and still needs
  the internal URL plumbing — all of the cost, none of the simplification.
- **Publishing web and API behind one dev reverse proxy (nginx/traefik service).** Achieves
  the same origin shape but adds a seventh always-on service to the Compose stack purely
  for path routing that Next already does natively.

## Consequences

- Zero changes to `apps/api` as built by T3 — the absence of CORS is now correct by design.
- T5 builds against relative paths and one env var; the Compose `web` service gains
  `SUNIL_API_INTERNAL_URL=http://api:3001`; `.env.example` updated (FR-092 diff test keeps
  it honest).
- **Phase 2 warning, recorded now:** the WebSocket gateway (Socket.IO) will not traverse a
  Next `rewrites()` proxy cleanly. Phase 2 must make an explicit ingress decision (its own
  ADR) — direct WS origin, a real proxy, or same-process gateway — instead of discovering
  this during integration. The deferred CSRF `Origin` check (Amendment A2) is revisited in
  that same ADR.
