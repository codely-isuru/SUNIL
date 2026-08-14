# ADR-008 — Browser talks directly to FastAPI: cross-origin, strict CORS allow-list, credentialed cookie, mandatory client header on mutations

**Status:** Proposed (Gate 2) · **Date:** 2026-08-14 · **Decider:** Solution Architect
**Context refs:** `docs/ARCHITECTURE_V1.md` §9.5 (the trust-boundary walk) and §12,
ADR-007, ADR-009, memory lesson **L-001**.

## Context

Memory lesson L-001, from SUNIL Phase 1: an architecture once implied a cross-origin browser→API
topology without ever specifying the CORS or proxy mechanism that made it work, and the gap surfaced
mid-build. The rule that came out of it is that no architecture ships until one **mutating** browser
request has been walked across every boundary at real addresses and ports, with every mechanism it
needs named in the config inventory.

M1 has two dev servers: Next.js on **3000** and FastAPI on **8000**. Requests must carry a session
cookie (ADR-007) and, per ADR-009, the browser also opens an `EventSource`.

## Decision

**The browser calls FastAPI directly at `http://localhost:8000`.** No proxy.

- `CORSMiddleware(allow_origins=[WEB_ORIGIN], allow_credentials=True,
  allow_methods=["GET","POST","OPTIONS"],
  allow_headers=["Content-Type","X-SUNIL-Client","X-Request-Id"], max_age=600)`, added **outermost**
  so error responses also carry CORS headers.
- `fetch(..., {credentials: "include"})`; `new EventSource(url, {withCredentials: true})`.
- **Every mutating request must send `X-SUNIL-Client: web`.** A custom header cannot be sent
  cross-origin without a successful preflight, and the preflight only succeeds for `WEB_ORIGIN` —
  so this is the CSRF control. The same dependency rejects a request whose `Origin` is present and
  not `WEB_ORIGIN`. `SameSite=Lax` is a second layer against true cross-site attackers, but it does
  **not** protect against another page on a different `localhost` port, which is exactly why the
  header requirement exists rather than relying on SameSite alone.
- **Hard rule: both services are addressed as `localhost`, never `127.0.0.1`.** Cookies ignore port,
  and `http://localhost:3000` → `http://localhost:8000` is *same-site* (same registrable host, same
  scheme) though cross-origin, so a `SameSite=Lax` cookie is sent. Mixing `127.0.0.1` and `localhost`
  makes the two different **sites**, `Lax` then withholds the cookie on POST, and the symptom looks
  like broken login rather than a topology mistake. `scripts/dev-check.ps1` asserts this at startup.
- The SSE GET carries no custom header (EventSource cannot set one) — acceptable because it is
  read-only and CORS still governs who may read it.
- **No Next.js Server Actions, no route handlers proxying the API, no server-component fetching.**

## Rejected alternatives

| Rejected | Why |
|---|---|
| **Same-origin proxy through Next.js `rewrites()`** | My own precedent (archived ADR-011) and genuinely attractive: no CORS, first-party cookies, one origin. Rejected here because ADR-009 puts a long-lived Server-Sent Events stream through that path, and rewrite-proxy streaming behaviour varies with Next version and compression settings. Betting the progress channel on proxy buffering three days from a deadline is a worse risk than writing six lines of CORS config. |
| **Next.js route handlers as a BFF** | Creates a *second* trust boundary (browser→Next server) with its own cookie context, its own CSRF surface and its own session forwarding — doubling the boundary count to remove one CORS block. Directly contrary to the L-001 lesson about surfaces designed in isolation. |
| **`allow_origins=["*"]` with credentials** | Rejected by every browser when `allow_credentials=True`. Named here because it is the first thing an engineer tries when CORS fails. |
| **Serving the built frontend from FastAPI (`StaticFiles`)** | Genuinely single-origin and a fine production answer. Rejected for M1 dev because it kills Next's hot reload, which is where most of the frontend's three days go. Reconsider for the hosted build. |
| **Token in an `Authorization` header instead of a cookie** | Removes CSRF concerns, but requires client-side token storage — see ADR-007's rejection of `localStorage`. |
| **Disabling CORS by running both on one port** | Not possible with two dev servers, and reintroduces the proxy question. |

## Consequences

- The whole browser→API surface is six lines of middleware config plus two dependencies, all named
  in `ARCHITECTURE_V1.md` §9.5 and in the env inventory (§14.4): `WEB_ORIGIN`,
  `NEXT_PUBLIC_API_BASE_URL`, `SESSION_COOKIE_NAME`.
- `WEB_ORIGIN` must change when the frontend is hosted; it is an env var, not a literal, for exactly
  that reason.
- If CORS is not outermost, a 401 arrives at the browser without `Access-Control-Allow-Origin` and
  the frontend sees an opaque network error. Called out in the code comment and in §3.3.
- L-001 is satisfied: `ARCHITECTURE_V1.md` §9.5 walks one mutating request across all four boundaries
  at real ports, and every mechanism it relies on appears in the config inventory.
