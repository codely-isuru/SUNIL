# SUNIL Phase 1 — Delivery Plan (Stage 4)

Owner: Delivery Manager (Minions Team 9) · Branch `feature/phase-1-foundation`
Gates 1 and 2 passed. This plan sequences Stage 5 (Development) and Stage 6 (Review).

## Gate 2 decisions carried into the build

| Decision | Resolution |
|---|---|
| Secondary label colour | **Opaque `#1BA3BC`** (4.67:1). `rgba()` is banned as a text `color` — a fixed colour measures once and stays measured. |
| Body prose colour | **`#E3F5FA`** ice. Cyan `#22D3EE` retained for values, links, headings, active nav. |
| Architecture, 10 ADRs, threat model | Approved as written, including all five deviations from `SUNIL_ARCHITECTURE.md`. |
| Phase 1 dashboard | Honest-empty. No placeholder metrics, no sample charts. |

## Work breakdown

Five engineering tasks in two waves. Waves exist to prevent write collisions, not for
ceremony: every task in a wave owns a disjoint set of paths.

### Wave 1 — foundation

| ID | Owner | Scope | Paths owned |
|---|---|---|---|
| **T1** | backend_engineer (opus) | Monorepo scaffold, root tooling config, `packages/core`, `packages/db` (full Prisma schema §5, initial migration, client extensions, repositories, seed). **Installs the entire dependency set for all workspaces up front.** | root configs, `packages/core/**`, `packages/db/**`, app skeleton dirs |
| **T2** | devops_engineer (sonnet) | Compose topology, env inventory, local setup guide. Pins the pgvector tag and records the digest (R-02). | `docker-compose*.yml`, `.env.example`, `docs/LOCAL_SETUP.md` |

T1 owning the install is deliberate: three agents running `pnpm add` concurrently would
corrupt `pnpm-lock.yaml`. Wave 2 installs nothing.

### Wave 2 — parallel implementation (all depend on T1)

| ID | Owner | Scope | Paths owned |
|---|---|---|---|
| **T3** | backend_engineer (opus) | Auth, sessions, TOTP, RBAC guards, CSRF, rate limiting, `SecretStore`, audit service. The security core. | `apps/api/**` |
| **T4** | backend_engineer (opus) | `packages/llm` (3 adapters + transport seam), `packages/agents` (runtime skeleton), BullMQ queues, worker and scheduler apps. | `packages/llm/**`, `packages/agents/**`, `apps/worker/**`, `apps/scheduler/**` |
| **T5** | frontend_engineer (opus) | `packages/ui` design tokens, `<SunilPresence />`, portal shell, sign-in, MFA, dashboard, Settings, System Health. | `packages/ui/**`, `apps/web/**` |

### Stage 6 — independent review (no agent reviews its own work)

| Reviewer | Reviews | Model |
|---|---|---|
| security_reviewer (fable) | T3 primarily; crypto, session mechanics, secret exposure, audit bypass | fable · maximum |
| qa_engineer (opus) | All five tasks against the 5 exit tests and the FR acceptance criteria | opus · maximum |

QA runs at Opus because the engineers under review are at Opus — hard rule 3: a reviewer
never runs on a weaker model than the agent it reviews.

## Definition of done (per task)

1. Code compiles: `pnpm typecheck` clean for the owned workspaces.
2. Tests written and passing for the owned scope.
3. No dependency-DAG violation (`lint:deps`).
4. Nothing mocked is presented as complete — labelled per architectural rule 7.
5. No secrets in code, config, logs or output. `.env.example` carries names only.
6. A written handoff naming what was built, what was tested, and what was left undone.

## Exit criteria for Phase 1

The five exit tests in `PHASE1_REQUIREMENTS.md` (ET-1 … ET-5): auth flows, RBAC guards,
audit writes, queue survives restart, secret round-trip never exposes plaintext. ET-4 must
be proven against real container stops, not mocks.

## Known constraints carried in

- No LLM provider API keys. Adapters are mock-verified and labelled "unverified against
  live endpoints" in code, portal and phase report.
- Windows 11 host. Named volumes over bind mounts; `.gitattributes` forces LF; no step may
  require a host `psql` (none installed).
- Production deployment is out of scope. Autonomy is Level 3 — autonomous to staging only.
