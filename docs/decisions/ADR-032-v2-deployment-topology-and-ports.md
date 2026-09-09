# ADR-032 — V2 dev topology: app on host, infrastructure in Compose, fixed loopback ports

**Status:** Proposed (Architect, V2 Phase 0) · **Date:** 2026-09-10 · **Decider:** Solution Architect
**Fixes an open point in:** `V2_DEVELOPMENT_PLAN.md` Phase 0 platform tasks ("Docker Compose adds
Postgres+pgvector, LiteLLM, n8n containers alongside api/web") — which processes run where, on
which ports, was unspecified; L-001 requires the trace to run at real addresses.
**Context refs:** ADR-001/005/013 (Docker off M1's critical path), ADR-008 (localhost, never
127.0.0.1, in browser-facing URLs), `ARCHITECTURE_V2.md` §5 (config inventory), ADR-033.

## Context

M1 ran everything on the host (uvicorn + `pnpm dev`), SQLite, no Compose file at all. V2 needs
Postgres+pgvector, LiteLLM and n8n as real services from Phase 0, and six parallel streams need one
addressing scheme so their tests and fakes agree on where things are.

## Decision

**Two named profiles in one `docker-compose.yml` at the repo root:**

1. **`infra` profile (the default dev loop):** containers for `postgres`, `litellm`, `n8n`
   (later `openhands`, optional `langfuse`). The API (uvicorn) and web (Next.js dev server) run
   **on the host**, as in M1 — fast reload, debuggable, no image rebuild per change.
2. **`full` profile (weekly integration checkpoint, Phase 2):** adds `api` and `web` containers so
   the whole stack boots green from one command; in-network URLs switch to service hostnames.

**Fixed port allocation** (all container ports published on `127.0.0.1` only — nothing V2 runs is
LAN-reachable):

| Service | Host address | Container/in-network | Notes |
|---|---|---|---|
| web (Next.js) | `http://localhost:3000` | `web:3000` (full profile) | browser entry; `WEB_ORIGIN` |
| api (uvicorn) | binds `127.0.0.1:8000`; browser addresses it as `http://localhost:8000` | `api:8000` (full profile) | `localhost`, never `127.0.0.1`, in browser-facing URLs — same-site cookie rule (ADR-008) |
| postgres (pgvector image) | `127.0.0.1:5432` | `postgres:5432` | databases: `sunil`, `litellm`, `n8n` — one server, three DBs, three users |
| litellm | `127.0.0.1:4000` | `litellm:4000` | LiteLLM's own default port |
| n8n | `127.0.0.1:5678` | `n8n:5678` | n8n's own default; MCP server under `/mcp`, webhooks under `/webhook` |
| openhands (Phase V2-D/F) | `127.0.0.1:3400` | `openhands:3000` | remapped: its default 3000 collides with web |
| langfuse (optional) | `127.0.0.1:3200` | `langfuse:3000` | same reason |

Host-mode processes reach containers via the published loopback ports (`http://localhost:4000`,
`postgres @ localhost:5432`, `http://localhost:5678`); full-profile containers use service
hostnames (`http://litellm:4000`, `postgres:5432`, `http://n8n:5678`). Every SUNIL-side URL that
can point at a container is validated by ADR-033 to exactly this set.

## Rejected alternatives

| Rejected | Why |
|---|---|
| **Everything in Compose from day one (single profile)** | Puts an image rebuild or a bind-mount + reload harness in every backend dev loop for six streams; M1's host-run loop is proven and ADR-005/013 deliberately kept Docker off the app's critical path. Infra-only containers give the new services without taxing the loop. |
| **Everything on host (install Postgres/LiteLLM/n8n natively)** | Three services × three OS setups × version drift across the team; n8n and LiteLLM are shipped and pinned as images. Containerising exactly the vendored infra is the low-friction line. |
| **Dynamic/ephemeral ports resolved at runtime** | Six streams writing tests against fakes need stable addresses in committed config; L-001 exists because unpinned topology is where architectures leak. Fixed ports, changed only by ADR. |
| **Publish on 0.0.0.0 (Docker's default)** | Exposes n8n (credential vault), LiteLLM (provider keys) and Postgres to the LAN in dev. `127.0.0.1:` publish specs cost nothing and are structural. |
| **Separate compose files per stream** | The Phase 2 "plug" step would then be a file merge under time pressure. One file, two profiles, owned by Phase 0. |

## Consequences

- `.env.example` and `ARCHITECTURE_V2.md` §5 carry this table as the single config inventory;
  contract fakes and stream tests hardcode these addresses.
- The full profile is the Phase 2 weekly checkpoint's boot target (`docker compose --profile full
  up`), catching in-network URL drift early.
- The L-001 trace in `ARCHITECTURE_V2.md` §6 runs on the `infra` profile addresses — the topology
  developers actually use daily.
