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

*⚠ The host-port column of this table — and the host-mode URLs quoted beneath it — were corrected
by **Amendment 1** (below, 2026-09-10 fix round): postgres → 5433, n8n → 5680, web → 3001. The
original text is kept verbatim per the no-silent-edit convention; read the amendment's table as
current.*

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

---

## Amendment 1 — host ports, compose location and profiles reconciled to reality (2026-09-10, Phase 0 fix round, owner: Solution Architect)

**Driven by:** QA review 2026-09-10 blocker B6 = Security review blocker B1. This ADR froze a port
inventory from the plan while the parallel platform lane was discovering the dev machine's
reality; three host ports in the original table point at FOREIGN processes on that machine — a
stream following the frozen defaults would hand SUNIL's Postgres credentials to an unrelated
container and its n8n token/webhooks to an unrelated n8n. The "fixed ports, changed only by ADR"
rule was bypassed by the platform task with no amendment; this amendment closes that loop and
restores document/reality parity. Ground truth verified against
`origin/task/P0-platform:infra/docker-compose.yml`, `.env.example` and `docs/ENVIRONMENT.md` §9.

**Corrected host-port table (current):**

| Service | Host address | Container/in-network | Why it moved |
|---|---|---|---|
| web (Next.js) | `http://localhost:3001` | `web:3000` (full profile, later) | **3000 is occupied on the build machine** (platform `.env.example`: `WEB_HOST_PORT=3001`); `WEB_ORIGIN` follows |
| api (uvicorn) | binds `127.0.0.1:8000`; browser addresses it as `http://localhost:8000` | `api:8000` (later) | unchanged (ADR-008 `localhost` rule unchanged) |
| postgres (pgvector image) | `127.0.0.1:5433` | `postgres:5432` | **5432 is bound by an unrelated container** (`strapi-next-starter-db-1`) |
| litellm | `127.0.0.1:4000` | `litellm:4000` | unchanged |
| n8n | `127.0.0.1:5680` | `n8n:5678` | **5678 AND 5679 are bound by the host-native n8n source build** (`C:\repo\n8n`) |
| openhands (Phase V2-D/F) | `127.0.0.1:3400` | `openhands:3000` | unchanged (reserved; not yet in compose) |
| langfuse (optional) | `127.0.0.1:3200` | `langfuse:3000` | unchanged (reserved; not yet in compose) |
| *(never)* | ~~4317~~ | — | Minions Portal — CI-guarded, never bind |

**In-network names and ports are unchanged** (`postgres:5432`, `litellm:4000`, `n8n:5678`): only
host publishes move, so service-to-service URLs — including C4 §2's webhook host rule and
ADR-033's named-host set — are untouched. Host-mode processes reach containers at
`localhost:5433 / localhost:4000 / localhost:5680`.

**Compose location:** the file lives at **`infra/docker-compose.yml`** (platform's layout — infra
config grouped with `infra/postgres/`, `infra/litellm/`), not the repo root as first written.

**Profiles deferred:** the `infra`/`full` profile split is deferred until the `api` container
exists (today it is a commented stub); the shipped file declares no profiles, and
`--profile full` on a profile-less file would silently no-op. The two-profile design remains the
target state; this amendment defers its introduction to the phase that adds the first
app container.

**CI parity check (required; DevOps implements):** a CI step MUST parse
`infra/docker-compose.yml` (YAML-parsed, not grepped — long-form `published:` counts) and assert
(a) the set of published `host:container` pairs equals this amendment's table exactly, and (b)
every publish binds host IP `127.0.0.1`. The check exists so the next port drift is a red build,
not a review finding.

**Consequences carried forward:** ADR-033's quoted default for `SUNIL_N8N_MCP_BASE_URL` follows
this amendment (`http://localhost:5680/mcp`) and ADR-035's context line reads n8n at
`127.0.0.1:5680` — both annotated in place, dated; the named-host rule and the token design are
unchanged. `ARCHITECTURE_V2.md` §4 (TB1/TB5/TB9), §5 and §6 are regenerated to this table in the
same fix round.
