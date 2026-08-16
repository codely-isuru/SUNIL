"""The HTTP layer: routes, middleware, request/response schemas.

`core/` must never import from `sunil.api` (§3.1) — the orchestrator is
invoked from an HTTP route today and from the scheduler in M10, and must
not be coupled to a `Request`. Dependencies only ever point this way:
`sunil.api` → `sunil.core` / `sunil.db`, never the reverse.
"""
