# SUNIL — Phase 1 (Foundation) Buildable Architecture

_Document owner: Solution Architect / Technical Lead (Minions delivery team)_
_Status: Issued for build. Subordinate to `SUNIL_ARCHITECTURE.md` and `SECURITY_MODEL.md`;
implements `PHASE1_REQUIREMENTS.md` (Gate-1 approved) and the Gate-1 decisions._
_Companion artefacts: `docs/adr/ADR-001` … `ADR-010`, `docs/THREAT_MODEL.md`._

> **Reading contract.** This document turns the already-decided stack into buildable detail.
> It re-chooses nothing that `SUNIL_ARCHITECTURE.md` decided; every place it *refines or
> deviates* is listed in §2 with justification. Engineers implement from this document and the
> ADRs; if a question is not answered here, it comes back to the Solution Architect rather than
> being decided ad hoc mid-build.

---

## 1. Decision summary (the three routed questions)

| Q | Decision | ADR |
|---|---|---|
| **Q4** Permission vocabulary & seed roles | Flat `resource:action` strings, concrete rows only (no wildcards at runtime). 21 Phase 1 permissions. Seed roles `owner` / `admin` / `viewer` / `agent` with deterministic UUIDs. **Exactly one `owner`**, enforced at three layers (bootstrap, service invariant, partial unique index). | ADR-001 |
| **Q7** Redis persistence | Redis 7.4, **AOF `appendfsync everysec`** with RDB preamble, `maxmemory-policy noeviction`, named volume. Worst-case loss: **≈1 s of acknowledged writes on a hard host crash; 0 on a clean container stop**. Schedule durability additionally does not depend on Redis alone (idempotent re-registration, §12.3). | ADR-002 |
| **Q8** Session auth | **Hand-rolled session management** following the documented Lucia/Copenhagen-Book pattern (opaque 256-bit token, SHA-256 hash stored server-side), because Lucia-the-library is deprecated. Primitives are never hand-rolled: `@node-rs/argon2` (argon2id) for passwords, `otpauth` for TOTP, Node `crypto` for randomness/hashing. | ADR-003 |

Other recorded decisions: Prisma confirmed (ADR-004), audit-before-commit transaction strategy
(ADR-005), secret envelope encryption scheme (ADR-006), pnpm + Turborepo mechanics (ADR-007),
LLM transport seam = official SDKs with injected `fetch` (ADR-008), CSRF header-token strategy
(ADR-009), repeatable-job identity via BullMQ Job Schedulers (ADR-010).

---

## 2. Deviations from and refinements to `SUNIL_ARCHITECTURE.md`

Per the acceptance rule, every deviation is visible and argued. Nothing else in this document
deviates.

| # | Architecture doc says | Phase 1 position | Why |
|---|---|---|---|
| D-1 | Auth: "Session-based (**Lucia-style**)" | Hand-rolled session layer in the Lucia *pattern*; Lucia is **not** a dependency | Lucia v3 was deprecated by its author and converted into a learning resource; depending on it would pin Phase 1 to an unmaintained package. The architecture named a style, not a library; ADR-003 records the choice and rejected alternatives. |
| D-2 | Realtime: "WebSocket gateway (Socket.IO)" | **No WebSocket gateway in Phase 1** | Chat/streaming/activity feeds are Phase 2 (`PHASE1_REQUIREMENTS.md` §1.3). Wiring Socket.IO now would be unexercised surface for the security reviewer. The NestJS module layout leaves a `gateway` seam for Phase 2. |
| D-3 | Queues: `agents`, `integrations:sync`, `workflows`, `notifications`, `briefs` | Phase 1 creates **`agents` and `system`** only | The other three queues belong to Phase 2–3 features. `system` is an addition not in the architecture list: Phase 1 maintenance jobs (session sweep, staleness sweep) need a home that is not a Phase 2 concern queue. The naming convention is unchanged; the remaining queues are added by the phases that consume them. |
| D-4 | §4 schema groups do not list a secrets table (credentials appear under Integrations as "credential references") | A **`secrets` table** is added to the Phase 1 migration | FR-040/FR-041 require envelope-encrypted storage *now*; integration accounts (Phase 3–4) will hold references into this table. This is the storage the architecture's `SecretStore` implies but never names. |
| D-5 | Monorepo layout lists `packages/integrations` and `packages/memory` | **Not scaffolded in Phase 1** | Empty placeholder packages invite scope creep (risk R-05) and dead code. They are created by Phase 3–4 when they gain content. The workspace globs (`packages/*`) already admit them without config change. |
| D-6 | — (silent on versions) | All majors pinned in §4 | Required by the task; not a deviation, recorded for completeness. |

---

## 3. Monorepo layout, dependency rule and pipeline

### 3.1 Workspace members

```
apps/
  web/          Next.js 15 portal (App Router). UI only; talks HTTP to apps/api.
  api/          NestJS 11 on the Fastify adapter. Auth, RBAC, audit, secrets, all REST.
  worker/       BullMQ processors (agents queue, system queue). No HTTP surface.
  scheduler/    Thin producer: upserts Job Schedulers, then idles. No queue consumption.
packages/
  core/         Domain types, Zod schemas, message-envelope contracts, error taxonomy,
                permission catalogue constants. Zero runtime deps beyond zod.
  db/           Prisma schema + migrations + generated client + client extensions
                (audit append-only guard) + thin repositories + seed/bootstrap script.
  llm/          LLMProvider interface, transport seam, Anthropic/OpenAI/Ollama adapters,
                usage-record writer, mock transports (test/dev only).
  agents/       Agent runtime: config loading/validation, envelope emission, heartbeats,
                in-loop budget/timeout enforcement.
  ui/           Design tokens (CSS variables + typed exports), shared React components,
                <SunilPresence />. No data fetching, no API knowledge.
prototype/      READ-ONLY design reference (byte-identical to Phase 0; FR-001).
docs/           This documentation set.
```

### 3.2 The dependency-direction rule (anti-cycle, structural)

**A workspace package may import only packages strictly below it in this DAG; apps may import
any package; nothing imports from `apps/*`.**

```
        core            (depends on: zod only)
       ↙  |  ↘
     db  llm  ui        (db → core; llm → core, db; ui → core [types only])
        ↘ |
        agents          (agents → core, db, llm)
          |
   apps/{web,api,worker,scheduler}
```

Enforcement is **structural, not conventional**, at three layers:

1. **pnpm strict linking.** With pnpm's isolated `node_modules`, a package physically cannot
   resolve a workspace package it has not declared in its own `package.json`. Declaring an
   edge that violates the DAG is the only way to cheat — and that is caught by:
2. **`dependency-cruiser`** run as the root `lint:deps` task, configured with the DAG above as
   allowed edges (`apps → packages`, `packages` per the arrows, `no-circular` globally).
   A violating import fails CI-equivalent local runs.
3. **TypeScript project references** mirror the same edges, so `tsc --build` order is the DAG
   and a cycle is a build error.

`packages/ui` importing from `core` is restricted to type-only imports (design tokens must not
drag server schemas into the client bundle); enforced by `import/consistent-type-specifier-style`
plus a dependency-cruiser rule limiting `ui → core` to `core/src/types` and `core/src/tokens`
paths.

### 3.3 pnpm + Turborepo configuration approach

- `pnpm-workspace.yaml`: `packages: ["apps/*", "packages/*"]`.
- Root `package.json` is private; all tasks run via `turbo run <task>`.
- **Lifecycle scripts are blocked by default** (pnpm ≥10 behaviour): maintain an explicit
  `pnpm.allowBuilds` allowlist (pnpm 11 name; formerly `onlyBuiltDependencies` — Amendment
  A4). Expected entries: `prisma`, `@prisma/engines`, `esbuild`. Anything else requesting a
  build script fails install — a supply-chain control (see THREAT_MODEL T-16). pnpm 11's
  release-age gate may write `minimumReleaseAgeExclude` entries; **every such exclusion is a
  Security Reviewer sign-off item**, not routine config.
- `turbo.json` pipeline:

| Task | dependsOn | Cached | Notes |
|---|---|---|---|
| `build` | `^build` | yes | `packages/db` build includes `prisma generate` (its output is an input to dependents) |
| `typecheck` | `^build` | yes | `tsc --noEmit` per workspace |
| `lint` | — | yes | ESLint 9 flat config, shared from root |
| `lint:deps` | — | yes | dependency-cruiser DAG check (root-level, not per package) |
| `test` | `^build` | yes | Vitest per workspace; root `pnpm test` = FR-003 single command; reporter emits JSON summary per workspace for the QA phase report |
| `dev` | — | no (persistent) | local dev servers |

- `.gitattributes` forces `eol=lf` for `*.sh`, `Dockerfile*`, `*.yml`, `*.yaml`, `prisma/**`
  (risk R-03: CRLF inside Linux containers).
- `.npmrc`: `engine-strict=true` with `engines: { node: ">=22 <23" }` in root `package.json`.

---

## 4. Pinned core dependencies (majors)

| Dependency | Pin | Justification / risk flag |
|---|---|---|
| Node | 22.x (LTS) | Confirmed on host (v22.14.0). |
| pnpm | 11.x | Confirmed on host (11.8.0). |
| TypeScript | 5.x (≥5.8), `strict: true` | — |
| Turborepo | 2.x | — |
| Next.js / React | 15.x / 19.x | App Router; self-hosted fonts via `next/font` (CSP §6.7). **Windows note:** dev-mode file watching in a Docker bind mount is slow — dev profile runs `web` on the host (§15.6); the Compose build is the acceptance path. |
| Tailwind CSS | 4.x | Consumes the `packages/ui` CSS-variable tokens directly. |
| NestJS | 11.x + `@nestjs/platform-fastify` (Fastify 5) | Guards/interceptors are the RBAC + audit enforcement points; OpenAPI via `@nestjs/swagger`. |
| Prisma | 6.x | ADR-004. `@default(uuid(7))` requires ≥5.19 — satisfied. |
| Zod | 4.x | Single source of runtime validation (`packages/core`). All workspaces must import the same major — enforced by declaring zod only in `core` and re-exporting. |
| BullMQ | 5.x (≥5.16) | Job Schedulers API (`upsertJobScheduler`) is the repeatable-identity mechanism (ADR-010). |
| ioredis | 5.x | BullMQ's client; also used for rate-limit/lockout counters. |
| Redis (image) | `redis:7.4-alpine` | ADR-002. License is RSALv2/SSPL — fine for local/self-hosted use; Valkey 8 is the recorded drop-in fallback if that ever changes posture. |
| Postgres (image) | `pgvector/pgvector:pg16` **pinned to an explicit tag at scaffold time** (e.g. `pgvector/pgvector:0.8.0-pg16`; DevOps records the exact digest) | Risk R-02; migration fails loudly if `CREATE EXTENSION vector` fails. |
| Pino | 9.x + `pino-http` | Redaction config is centralised (§9.5); `nestjs-pino` for request binding. |
| `@node-rs/argon2` | 2.x | argon2id with **prebuilt N-API binaries for win32-x64 and linux-x64-musl** — no node-gyp toolchain on Windows (the classic `argon2` package is the known-risk alternative and is rejected in ADR-003). |
| `otpauth` | 9.x | Pure-JS RFC 6238 TOTP; zero native deps. |
| `@anthropic-ai/sdk` | latest major at scaffold (pin exact) | Transport seam via injected `fetch` (ADR-008). |
| `openai` | latest major at scaffold (pin exact) | Same seam. |
| Vitest | 3.x | Workspace-aware; JSON reporter satisfies FR-003's machine-readable summary. |
| dependency-cruiser | 16.x | §3.2 enforcement. |
| ESLint | 9.x flat config + typescript-eslint 8 | Includes the lint fences named in §7.4/§8.5/§9.4. |

Known Windows/Node-22 risk flags: (a) any package that compiles with node-gyp at install —
none is in the set above by design; adding one requires an ADR; (b) Prisma engines download at
install (allowlisted build script); (c) CRLF — handled by `.gitattributes`.

---

## 5. Data model — complete Prisma schema design

### 5.1 Conventions (apply to every model unless stated)

- **PK convention:** `id String @id @default(uuid(7))` — UUIDv7, client-generated by Prisma.
  Time-ordered, so append-heavy tables (audit, envelopes, usage, executions) index well.
- `createdAt DateTime @default(now())`; `updatedAt DateTime @updatedAt` on every **mutable**
  entity. Append-only models (`AuditLog`, `AgentMessage`, `UsageRecord`, `JobExecution`)
  carry `createdAt` only — no `updatedAt`, deliberately.
- Table mapping: `@@map` to `snake_case` plural (`users`, `audit_logs`, …); columns `@map` to
  snake_case.
- **`externalId` convention (dormant in Phase 1):** any future model ingesting external data
  carries `source String` + `externalId String` + `@@unique([source, externalId])`. **No
  Phase 1 model imports external data, so no Phase 1 model carries it.** The convention is
  recorded here so Phase 3–4 engineers do not invent a second one.
- Email normalisation: trim + lowercase applied in the Zod boundary schema (`core`), so the DB
  unique index on `email` is effectively case-insensitive without the `citext` extension.
- Enums are Prisma enums (Postgres native enums), listed per model below.
- All FKs `onDelete: Restrict` unless stated — Phase 1 never cascades a delete through
  identity or audit data.

### 5.2 Identity group

**`User`** (`users`)

| Field | Type | Attributes |
|---|---|---|
| id | String | `@id @default(uuid(7))` |
| email | String | `@unique` (normalised lowercase) |
| passwordHash | String | argon2id PHC string (includes salt + params) |
| displayName | String | |
| status | UserStatus | enum `ACTIVE`, `DISABLED`; default `ACTIVE` |
| timezone | String | default `"Australia/Hobart"` (assumption A-10) |
| mfaEnabled | Boolean | default false — denormalised flag; source of truth is `MfaCredential.status` |
| createdAt / updatedAt | DateTime | |

Relations: `userRoles UserRole[]`, `sessions Session[]`, `invitationsSent Invitation[]`,
`mfaCredential MfaCredential?`, `mfaRecoveryCodes MfaRecoveryCode[]`.
No plaintext password or TOTP secret anywhere on this model (FR-011).

**`Role`** (`roles`)

| Field | Type | Attributes |
|---|---|---|
| id | String | `@id` — **no default; system roles are seeded with fixed UUIDs** (below) |
| slug | String | `@unique` (`owner`, `admin`, `viewer`, `agent`) |
| name | String | |
| description | String | |
| isSystem | Boolean | default false; system roles cannot be deleted or renamed via API |
| createdAt / updatedAt | DateTime | |

Fixed system-role UUIDs (deterministic so migrations/indexes can reference them):

```
owner  = 00000000-0000-7000-8000-000000000001
admin  = 00000000-0000-7000-8000-000000000002
viewer = 00000000-0000-7000-8000-000000000003
agent  = 00000000-0000-7000-8000-000000000004
```

These constants live in `packages/core` (single definition; seed and migration both use them).

**`Permission`** (`permissions`)

| Field | Type | Attributes |
|---|---|---|
| id | String | `@id @default(uuid(7))` |
| key | String | `@unique` — the `resource:action` string (ADR-001 catalogue) |
| description | String | |
| createdAt | DateTime | |

**`RolePermission`** (`role_permissions`) — join table

| Field | Type | Attributes |
|---|---|---|
| roleId | String | FK → Role |
| permissionId | String | FK → Permission |
| createdAt | DateTime | |

`@@id([roleId, permissionId])`.

**`UserRole`** (`user_roles`) — join table

| Field | Type | Attributes |
|---|---|---|
| userId | String | FK → User |
| roleId | String | FK → Role |
| assignedById | String? | FK → User (null for bootstrap) |
| createdAt | DateTime | |

`@@id([userId, roleId])`, `@@index([roleId])`.
**Single-owner constraint (Gate 1 / ADR-001):** the initial migration appends raw SQL:

```sql
CREATE UNIQUE INDEX one_owner_only ON user_roles (role_id)
  WHERE role_id = '00000000-0000-7000-8000-000000000001';
```

A second owner assignment fails at the database even if application checks are bypassed.

**`Session`** (`sessions`)

| Field | Type | Attributes |
|---|---|---|
| id | String | `@id @default(uuid(7))` |
| tokenHash | String | `@unique` — SHA-256 hex of the opaque cookie token; **raw token never stored** |
| userId | String | FK → User |
| state | SessionState | enum `PENDING_MFA`, `ACTIVE`, `REVOKED` |
| csrfSecret | String | 32 random bytes, base64url (ADR-009) |
| createdAt | DateTime | |
| lastSeenAt | DateTime | sliding-refresh bookkeeping |
| idleExpiresAt | DateTime | now + `SUNIL_SESSION_IDLE_HOURS` (8) |
| absoluteExpiresAt | DateTime | createdAt + `SUNIL_SESSION_ABSOLUTE_HOURS` (24); never extended |
| revokedAt | DateTime? | |
| revokedReason | String? | e.g. `logout`, `admin_revoke`, `privilege_reduction`, `password_change`, `expired_sweep` |
| ip | String? | |
| userAgent | String? | |

`@@index([userId])`, `@@index([idleExpiresAt])` (sweep job).
Expiry + revocation marker satisfy FR-011; state machine in §6.2.

**`Invitation`** (`invitations`)

| Field | Type | Attributes |
|---|---|---|
| id | String | `@id @default(uuid(7))` |
| email | String | normalised |
| tokenHash | String | `@unique` — SHA-256 of the single-use link token |
| roleId | String | FK → Role (the invited role; **never `owner`** — service invariant + seed excludes it) |
| invitedById | String | FK → User |
| expiresAt | DateTime | createdAt + `SUNIL_INVITE_TTL_HOURS` (72) |
| consumedAt | DateTime? | set atomically on acceptance |
| revokedAt | DateTime? | owner/admin can revoke a pending invite |
| createdAt | DateTime | |

`@@index([email])`.

**`MfaCredential`** (`mfa_credentials`)

| Field | Type | Attributes |
|---|---|---|
| id | String | `@id @default(uuid(7))` |
| userId | String | `@unique` FK → User |
| secretName | String | **reference into `SecretStore`** (e.g. `mfa:totp:<userId>`) — the TOTP secret itself is envelope-encrypted in `secrets`, never a column here (FR-027) |
| status | MfaStatus | enum `PENDING`, `ACTIVE` |
| lastUsedStep | BigInt? | last accepted TOTP timestep — replay prevention (§6.4) |
| activatedAt | DateTime? | |
| createdAt / updatedAt | DateTime | |

**`MfaRecoveryCode`** (`mfa_recovery_codes`)

| Field | Type | Attributes |
|---|---|---|
| id | String | `@id @default(uuid(7))` |
| userId | String | FK → User |
| codeHash | String | `@unique` — SHA-256 (input is high-entropy random, slow hash unnecessary) |
| usedAt | DateTime? | single-use marker |
| createdAt | DateTime | |

`@@index([userId])`.

### 5.3 Settings group

**`SystemSetting`** (`system_settings`)

| Field | Type | Attributes |
|---|---|---|
| id | String | `@id @default(uuid(7))` |
| key | String | `@unique` (dot-namespaced, e.g. `llm.modelRates`) |
| value | Json | |
| valueType | String | `string` \| `number` \| `boolean` \| `json` — for portal rendering |
| description | String | |
| updatedById | String? | FK → User |
| createdAt / updatedAt | DateTime | |

Seeded keys include `llm.modelRates` (per-model token rates used for cost estimation —
FR-064's "rates from configuration/data, not call-site constants").

**`LlmProvider`** (`llm_providers`)

| Field | Type | Attributes |
|---|---|---|
| id | String | `@id @default(uuid(7))` |
| slug | String | `@unique` (`anthropic`, `openai`, `ollama`) |
| name | String | |
| baseUrl | String? | required for `ollama`; optional override for others |
| enabled | Boolean | default `false` |
| defaultModel | String? | |
| credentialName | String? | **reference into `SecretStore`** — never a credential value (FR-012) |
| verificationStatus | ProviderVerification | enum `UNCONFIGURED`, `MOCK_VERIFIED`, `LIVE_VERIFIED`; Phase 1 rows can never reach `LIVE_VERIFIED` (Gate 1 / FR-065; §10.5) |
| createdAt / updatedAt | DateTime | |

**`Secret`** (`secrets`) — deviation D-4; scheme detail in §8 / ADR-006

| Field | Type | Attributes |
|---|---|---|
| id | String | `@id @default(uuid(7))` |
| name | String | `@unique` — the reference key used by `credentialName` / `secretName` |
| description | String | |
| ciphertext | Bytes | AES-256-GCM output over the plaintext |
| iv | Bytes | 12 bytes, unique per encryption |
| authTag | Bytes | 16 bytes |
| wrappedDek | Bytes | DEK encrypted under the KEK (AES-256-GCM) |
| dekIv | Bytes | 12 bytes |
| dekAuthTag | Bytes | 16 bytes |
| version | Int | default 1; incremented on rotation |
| masterKeyVersion | Int | which KEK wrapped the DEK (`SUNIL_MASTER_KEY_VERSION` at write time) |
| fingerprint | String | mask for display: `…` + last 4 chars + first 8 hex of SHA-256(plaintext) |
| rotatedAt | DateTime? | |
| createdAt / updatedAt | DateTime | |

### 5.4 Audit group

**`AuditLog`** (`audit_logs`) — append-only (enforcement §9.3)

| Field | Type | Attributes |
|---|---|---|
| id | String | `@id @default(uuid(7))` |
| actorType | ActorType | enum `HUMAN`, `AGENT`, `SYSTEM` |
| actorId | String? | user id or agent id; null for `SYSTEM` |
| actorLabel | String | denormalised display (`isuru@…`, `agent:email-triage`, `system:bootstrap`) — survives actor deletion |
| action | String | dot-namespaced verb, e.g. `auth.login.success`, `secret.rotate`, `user.role.change` (catalogue in `packages/core`) |
| targetType | String? | e.g. `user`, `secret`, `session` |
| targetId | String? | |
| before | Json? | redacted per §9.5 before persist |
| after | Json? | redacted per §9.5 before persist |
| outcome | AuditOutcome | enum `SUCCESS`, `FAILURE` |
| denialReason | String? | category only: `unauthenticated`, `forbidden`, `csrf`, `rate_limited`, `locked_out`, `validation` |
| correlationId | String | request/job correlation id (NFR-012) |
| ip | String? | |
| userAgent | String? | |
| createdAt | DateTime | `@default(now())` — server-generated; the service accepts no caller-supplied timestamp (FR-050) |

Indexes: `@@index([createdAt(sort: Desc)])`, `@@index([actorId])`, `@@index([action])`,
`@@index([targetType, targetId])`, `@@index([correlationId])`.

### 5.5 Usage group

**`UsageRecord`** (`usage_records`) — append-only

| Field | Type | Attributes |
|---|---|---|
| id | String | `@id @default(uuid(7))` |
| provider | String | slug |
| model | String | |
| feature | String | caller-supplied label (e.g. `agent-run`, `smoke-test`) |
| agentId | String? | FK → Agent (nullable — FR-064) |
| tokensIn | Int | |
| tokensOut | Int | |
| estimatedCostUsd | Decimal | `@db.Decimal(12, 6)` |
| latencyMs | Int | |
| errorClass | String? | typed taxonomy (§10.3); null on success |
| errorMessage | String? | redacted before persist |
| retryCount | Int | default 0 |
| correlationId | String? | |
| createdAt | DateTime | |

Indexes: `@@index([createdAt])`, `@@index([provider, model])`, `@@index([agentId])`.
No prompt/completion text is ever stored here (FR-064).

### 5.6 Agents group

**`Agent`** (`agents`)

| Field | Type | Attributes |
|---|---|---|
| id | String | `@id @default(uuid(7))` |
| slug | String | `@unique` |
| name | String | |
| role | String | short description of duty |
| systemInstructions | String | `@db.Text` |
| toolAllowlist | Json | default `[]` — **must be empty in Phase 1** (FR-070); non-empty fails Zod validation until Phase 2 relaxes it |
| providerId | String? | FK → LlmProvider |
| modelId | String? | |
| maxDurationSeconds | Int | |
| tokenBudget | Int? | |
| costBudgetUsd | Decimal? | `@db.Decimal(12, 6)` |
| heartbeatIntervalSeconds | Int | default from env `SUNIL_AGENT_HEARTBEAT_SEC` (30) |
| staleThresholdSeconds | Int | default from env `SUNIL_AGENT_STALE_SEC` (90) |
| status | AgentStatus | enum `IDLE`, `RUNNING`, `STALE`, `FAILED`, `DISABLED` |
| currentTaskId | String? | |
| lastHeartbeatAt | DateTime? | staleness sweep reads this |
| enabled | Boolean | default true |
| createdAt / updatedAt | DateTime | |

**`AgentMessage`** (`agent_messages`) — the envelope/activity log, append-only

| Field | Type | Attributes |
|---|---|---|
| id | String | `@id @default(uuid(7))` |
| type | EnvelopeType | enum `TASK_ASSIGNED`, `TASK_STARTED`, `TASK_PROGRESS`, `INFORMATION_REQUIRED`, `APPROVAL_REQUIRED`, `TASK_BLOCKED`, `TASK_COMPLETED`, `TASK_FAILED`, `AGENT_HEARTBEAT` |
| agentId | String | FK → Agent |
| taskId | String | UUID of the logical task |
| parentTaskId | String? | |
| payload | Json | Zod-validated per type before persist |
| tokensUsed | Int? | |
| estimatedCostUsd | Decimal? | `@db.Decimal(12, 6)` |
| sequence | BigInt | `@default(autoincrement())` — global monotonic emission order (FR-072 ordering) |
| correlationId | String | |
| createdAt | DateTime | |

Indexes: `@@index([agentId, taskId, sequence])`, `@@index([type])`, `@@index([createdAt])`.

### 5.7 Jobs group

**`JobExecution`** (`job_executions`) — append-only

| Field | Type | Attributes |
|---|---|---|
| id | String | `@id @default(uuid(7))` |
| jobName | String | |
| queue | String | `system` \| `agents` |
| bullJobId | String | BullMQ job id |
| schedulerId | String? | Job Scheduler id when repeatable (ADR-010) |
| attempt | Int | |
| startedAt | DateTime | |
| finishedAt | DateTime? | |
| durationMs | Int? | |
| outcome | JobOutcome | enum `RUNNING`, `COMPLETED`, `FAILED`, `TIMED_OUT`, `STALLED` |
| error | String? | `@db.Text`, redacted |
| result | Json? | small results only; large payloads are an anti-pattern |
| createdAt | DateTime | |

Indexes: `@@index([jobName, startedAt])`, `@@index([queue])`, `@@index([outcome])`,
`@@index([bullJobId])`.

### 5.8 Migration and bootstrap

- **One initial migration** creates everything above plus: `CREATE EXTENSION IF NOT EXISTS
  vector;` (fail loudly per R-02 — no embedding column exists, installation only, A-05); the
  `one_owner_only` partial unique index (§5.2); and the audit append-only trigger (§9.3).
- **Bootstrap** (`packages/db` script, run via `pnpm db:bootstrap`): idempotent upserts of the
  4 roles (fixed UUIDs), the 21 permissions, role-permission grants, the 3 `LlmProvider` rows
  (disabled, `UNCONFIGURED`), seed `SystemSetting` rows, and **exactly one owner**: email from
  `SUNIL_OWNER_EMAIL`, initial password from `SUNIL_OWNER_INITIAL_PASSWORD` **read from the
  environment at bootstrap time, never committed, never defaulted** (FR-014). Re-run: detects
  the existing owner and changes nothing. Every bootstrap action writes `SYSTEM`-actor audit
  records.

---

## 6. Authentication design

### 6.1 Token and cookie mechanics

- Session token: 32 bytes from `crypto.randomBytes`, base64url → cookie value. Server stores
  only `sha256(token)` (`Session.tokenHash`); DB theft yields no usable tokens.
- Cookie: name `__Host-sunil_session` when `SUNIL_COOKIE_SECURE=true` (production default),
  plain `sunil_session` for local HTTP dev. Attributes: `HttpOnly; SameSite=Lax; Path=/;
  Max-Age=<remaining absolute lifetime>`; `Secure` per the flag. The production configuration
  profile hard-fails startup if `SUNIL_COOKIE_SECURE` is explicitly false (FR-023 —
  permissive-by-omission is impossible).

### 6.2 Session lifecycle

```
login OK, no MFA      → create Session(state=ACTIVE)
login OK, MFA enrolled → create Session(state=PENDING_MFA)   ── only /api/auth/mfa/verify accepted
PENDING_MFA + valid TOTP/recovery → state=ACTIVE (same row; token unchanged is NOT allowed —
                                     the token is ROTATED on elevation to prevent fixation:
                                     new token issued, old hash overwritten)
any request           → validate: hash lookup → state=ACTIVE → now < idleExpiresAt
                        AND now < absoluteExpiresAt; else 401
validated request     → sliding refresh: idleExpiresAt = now + 8 h, throttled to at most one
                        write per 60 s (write-amplification guard); absoluteExpiresAt never moves
logout                → state=REVOKED, revokedAt, reason=logout; cookie cleared
revocation (any path) → same fields, reason recorded; takes effect on the next request because
                        every request validates against the row (no in-memory session cache)
expiry sweep          → repeatable `system:session-sweep` job marks expired rows REVOKED
                        (reason=expired_sweep) — bookkeeping only; expiry is enforced at
                        validation time regardless
```

Password change (self) and admin password reset revoke **all other** sessions of that user
(reason `password_change`), keeping the current one for self-change.

### 6.3 Login and brute-force mechanics

1. Per-IP auth rate limit checked first (20 req/min, Redis fixed-window `INCR`+`EXPIRE`) → 429
   with `Retry-After`.
2. Lockout check: Redis key `lockout:<emailHash>`; if present → generic lockout response,
   audited `auth.login.lockout` (FR-029). Lockout is set when the failure counter
   `authfail:<emailHash>` (INCR, 15-min TTL) reaches 5; lockout TTL 15 min. Owner can clear via
   `POST /api/users/:id/lockout/clear` (maps to `user:update`).
3. Credential check: fetch user by normalised email; **if absent, verify against a static dummy
   argon2 hash anyway** (timing-equalisation; no account-existence oracle — FR-022, ET-1 1.3).
4. Success path per §6.2. Failure: generic message, `auth.login.failure` audit record.
5. All thresholds from env (§16), defaults per Gate 1: 5 failures / 15 min → 15-min lockout;
   100 req/min per session; 20 req/min per IP on auth endpoints.

Lockout state lives in Redis (persisted by AOF; a rare hard-crash reset of a lockout window is
an accepted, documented residual — THREAT_MODEL T-03).

### 6.4 TOTP MFA

- **Enrol** (`POST /api/auth/mfa/enrol`, self-service): generate 20-byte secret via `otpauth`;
  store through `SecretStore` under `mfa:totp:<userId>`; create `MfaCredential(status=PENDING)`;
  return the `otpauth://` URI + secret **once** for QR/manual entry (this is the single
  sanctioned "secret leaves the API" moment — it is the enrolment payload, not a stored-secret
  read; it is never retrievable again).
- **Activate** (`POST /api/auth/mfa/activate` with a current code): verify (window ±1 step,
  30 s, 6 digits) → status `ACTIVE`, `user.mfaEnabled=true`; generate 10 recovery codes
  (10-char base32, shown once, stored SHA-256-hashed); audited.
- **Login challenge**: per §6.2 `PENDING_MFA`. Replay prevention: accepted code's timestep is
  stored in `MfaCredential.lastUsedStep`; any code for a step ≤ lastUsedStep is rejected
  (FR-027 "invalid or reused code").
- **Recovery**: `POST /api/auth/mfa/verify` with `{recoveryCode}`; hash-match + `usedAt IS
  NULL` update in one transaction (single use).
- **Disable**: requires current password re-auth; deletes the SecretStore entry and recovery
  codes; audited.

### 6.5 CSRF (ADR-009)

Per-session random `csrfSecret`; the client receives it in the login/mfa-verify response body
and from `GET /api/auth/me`, and sends it on every mutating request in the `X-CSRF-Token`
header. A global Nest guard rejects POST/PUT/PATCH/DELETE without a constant-time-equal header
(403, audited `csrf` denial). Safe methods exempt. Cookie value alone can never authorise a
mutation, so cross-site form/fetch requests fail even where `SameSite=Lax` would let them
through. Token rotates with the session token on MFA elevation.

### 6.6 Privilege-reduction session revocation — the exact hook (Gate 1)

All role mutation flows through **one choke point**: `RoleAssignmentService.changeRoles(userId,
newRoleIds, actor)` in `apps/api` (the only code permitted to write `UserRole`; a lint fence
bans `prisma.userRole` access outside it and the bootstrap). Inside the audited transaction
(§9.2) it:

1. resolves the effective permission set **before**;
2. applies the role change;
3. resolves the effective permission set **after** (same transaction);
4. writes the `user.role.change` audit record with before/after permission sets;
5. **if `after ⊉ before` (any permission lost): revokes every session of that user in the same
   transaction** (`reason=privilege_reduction`).

Because permissions are resolved per request (§7.3), *increases* are live immediately with no
revocation; *reductions* both revoke and would anyway be live on the next request. The
transaction guarantees revocation and the audit record commit atomically with the role change.

### 6.7 Security headers

Set by the API (Fastify hooks) and by `apps/web` (Next middleware): CSP
`default-src 'self'; script-src 'self' 'nonce-<per-request>'; style-src 'self' 'unsafe-inline';
img-src 'self' data:; font-src 'self'; connect-src 'self'; frame-ancestors 'none';
object-src 'none'; base-uri 'none'`, plus `X-Content-Type-Options: nosniff`,
`Referrer-Policy: same-origin`. Fonts (Orbitron / Share Tech Mono) are self-hosted via
`next/font` so no third-party origin appears in CSP. No `innerHTML`/`dangerouslySetInnerHTML`
anywhere (FR-031; lint rule `react/no-danger` set to error).

---

## 7. RBAC design

### 7.1 Vocabulary (ADR-001)

Flat, lowercase `resource:action` strings; concrete rows only — **no wildcard grammar exists at
runtime**. The Phase 1 catalogue (21 permissions, constants in `packages/core`):

```
user:read      user:invite    user:update
role:read      role:assign
session:read   session:revoke
secret:create  secret:read    secret:rotate   secret:delete
settings:read  settings:write
provider:read  provider:write
audit:read     usage:read
agent:read     agent:write
job:read       dashboard:read
```

`secret:read` grants **metadata** reads only — no permission string exists that returns a
secret value, because no API returns one (§8.4).

### 7.2 Seed roles

| Role | Permissions | Notes |
|---|---|---|
| `owner` | all 21 | Exactly one holder (three-layer enforcement, §5.2/ADR-001). The idempotent seed re-grants *all known permissions* to `owner` on every run, so later phases' new permissions flow to the owner automatically. |
| `admin` | all except `role:assign` | Role changes are owner-only in Phase 1 — this keeps the §6.6 choke point behind the strongest principal. Additional service invariant: admin operations may never target the owner account (checked on target, not permission). |
| `viewer` | `dashboard:read`, `audit:read` | The default-deny proof persona (ET-2). |
| `agent` | none | Non-human principal; no portal login (no password-login path is valid for it — agents are represented for audit, not authenticated via `/api/auth/login`). |

### 7.3 Guard mechanism and per-request resolution

- Effective permissions are resolved **per request**: session → user → roles → permissions in
  one indexed query (`user_roles ⋈ role_permissions ⋈ permissions`), cached only within the
  request (Gate 1: immediate effect). No cross-request permission cache exists in Phase 1;
  if profiling ever demands one, that is a new ADR because it interacts with §6.6.
- A global Nest guard chain runs in order: session validation → CSRF (mutating) → rate limit →
  permission check → handler.

### 7.4 Default deny — structural, not conventional

Every route handler must carry **exactly one** of three decorators:

| Decorator | Meaning |
|---|---|
| `@Public()` | On the explicit allowlist: login, MFA verify, invitation accept, system-health |
| `@SelfService()` | Requires an `ACTIVE` session; acts only on the caller's own account (logout, me, own MFA, own password, own sessions) |
| `@RequiresPermission('resource:action')` | Requires the named permission |

Enforcement layers:

1. **Runtime default deny:** the global guard reads the metadata; a route with *no* decorator
   is rejected 403 before the handler runs — absence of declaration is denial, not exposure.
2. **Enumeration test (ET-2 2.1):** a test walks the Nest route explorer, asserts every
   registered route carries exactly one decorator, and **fails naming any offender** — so an
   undeclared route cannot even reach a deployable build.
3. Denials return only the status code + a generic body (no resource-existence leakage,
   FR-026), and write a `FAILURE` audit record with the denial category.

Registration endpoints do not exist at all (FR-020): no handler, nothing in OpenAPI, and an
ET-1 probe test asserts 404/405 on the plausible paths.

---

## 8. `SecretStore` design

### 8.1 Interface (in `packages/core`; implementation in `apps/api`-side DI, storage via `packages/db`)

```
SecretStore
  put(name, plaintext: SecretInput, meta): Promise<SecretMetadata>
  get(name): Promise<SecretValue>          // server-side use only — see §8.4
  rotate(name, newPlaintext): Promise<SecretMetadata>
  delete(name): Promise<void>
  describe(name): Promise<SecretMetadata>  // id, name, description, fingerprint,
                                           // version, timestamps — never a value
```

Two implementations: `EnvelopeSecretStore` (Phase 1, below) and `InMemorySecretStore`
(test double — FR-040's swappability proof; consumers depend only on the interface).

### 8.2 Envelope encryption scheme (ADR-006)

- **KEK (master key):** env `SUNIL_MASTER_KEY` = base64 of exactly 32 bytes; validated at boot
  — wrong length or absent ⇒ process refuses to start (FR-041/FR-004). `SUNIL_MASTER_KEY_VERSION`
  (int, default 1). Optional `SUNIL_MASTER_KEY_PREVIOUS` (+ implicit version −1) enables KEK
  rotation: decrypt-with-old, re-wrap-with-current lazily on next read/rotate.
- **Per-secret DEK:** 32 random bytes, generated at `put`/`rotate`, never reused across secrets
  or versions.
- **Encrypt value:** AES-256-GCM, fresh 12-byte IV per encryption, 16-byte auth tag, **AAD =
  `${secretId}:${version}`** — binds ciphertext to its row and version so a copied ciphertext
  from another row fails authentication (swap attack).
- **Wrap DEK:** AES-256-GCM under the KEK, own fresh IV + tag, AAD = `${secretId}`.
- **Read:** unwrap DEK (auth-tag verified) → decrypt value (auth-tag + AAD verified). Any
  failure throws a typed `SecretIntegrityError`, returns **nothing partial**, and is audited
  (ET-5 5.9).
- **Rotate:** new DEK + IV + ciphertext written over the old columns in one update;
  `version`++, `rotatedAt` set; the previous ciphertext is not retained anywhere (FR-044
  "no longer retrievable"). Reference name unchanged.
- Unique-IV property gives ET-5 5.3 (same plaintext twice ⇒ different ciphertexts) for free.

### 8.3 Fingerprint

`fingerprint = "…" + last4(plaintext) + " / sha256:" + first8hex(sha256(plaintext))` — computed
at write, stored, and it is the *only* value-derived datum any API returns (FR-042).

### 8.4 "APIs never return a secret" — structural enforcement

1. `SecretStore.get` returns a **`SecretValue` wrapper class**, not a string: `toJSON()`,
   `toString()` and `util.inspect.custom` all yield `"[REDACTED]"`; the plaintext is reachable
   only via `secretValue.use(fn)` inside server code. Accidentally serialising it into a
   response or a log emits the marker, not the value.
2. Secret API endpoints are DTO-allowlisted (id, name, description, fingerprint, version,
   timestamps); a global serialisation interceptor **throws** if a `SecretValue` instance ever
   appears in an outgoing response object.
3. The portal treats secret fields as write-only: save/replace/rotate only, never repopulated
   (FR-042).
4. A lint fence: `SecretStore.get` is importable/injectable only in `apps/api` services,
   `apps/worker` and `packages/llm` (dependency-cruiser path rule); `apps/web` cannot even
   compile a call to it.
5. ET-5's sentinel scans (responses, headers, logs, usage records, bundle) are the standing
   regression proof.

### 8.5 Access auditing

Every `put`/`get`/`rotate`/`delete` writes an audit record (actor, operation, secret **name**,
outcome — never the value): mutations inside the audited transaction (§9.2); `get` writes a
`secret.read` record post-operation (reads are the stated exception to "mutations only",
assumption A-12 / SECURITY_MODEL §9).

---

## 9. Audit design

### 9.1 Service interface (in `packages/db`, consumed by every app)

```
AuditService
  record(tx: TransactionClient, entry: AuditEntry): Promise<void>   // inside a mutation tx
  recordDenial(entry: DenialEntry): Promise<void>                   // outside any tx
  query(filter, page): Promise<Paged<AuditRecord>>                  // guarded by audit:read
```

`AuditEntry` = actorType, actorId?, actorLabel, action, targetType?, targetId?, before?,
after?, outcome, correlationId, ip?, userAgent?. Timestamp is **server-generated in the
service**; there is no field for the caller to supply one (FR-050).

### 9.2 Audit-before-commit (Gate 1 / ADR-005)

Every security-relevant mutation runs inside **one Prisma interactive transaction** via a
`UnitOfWork` helper:

```
uow.runAudited(auditSpec, async (tx) => { …domain writes via tx… })
   // helper appends AuditService.record(tx, …) as the LAST write in the SAME transaction,
   // then commits. Audit insert fails ⇒ whole transaction rolls back ⇒ request fails 500
   // "operation not recorded" (generic body). The mutation can never commit unaudited.
```

**Denied requests** (401/403/CSRF/429/lockout): there is no mutation to protect;
`recordDenial` writes the single `FAILURE` record outside a transaction. If *that* write fails,
the denial still stands (deny-by-default is not weakened) and the failure is logged at `fatal`
with the correlation id — an operational alert condition, documented as the deliberate
asymmetry of the Gate-1 rule.

### 9.3 Append-only integrity — two layers

1. **Application:** a Prisma client extension in `packages/db` throws on
   `update/updateMany/delete/deleteMany` (and upsert) against `AuditLog` — every app gets the
   guarded client; the raw client is not exported.
2. **Database:** the initial migration adds
   `CREATE TRIGGER audit_logs_append_only BEFORE UPDATE OR DELETE ON audit_logs …
   RAISE EXCEPTION 'audit_logs is append-only';`
   so even raw SQL through the app role is rejected (FR-013/FR-052; ET-3 3.4).
   **As built (Amendment A5):** the guard additionally covers `TRUNCATE`
   (`BEFORE TRUNCATE` statement-level trigger) — stronger than originally specified, and
   endorsed. Consequence every engineer must know **before fighting it**: no test harness
   can reset `audit_logs`, ever. The sanctioned pattern (established by T3) is to scope
   every audit assertion by `correlationId`; tests must never assume an empty audit table.

### 9.4 Coverage enforced, not remembered

- Every mutating route handler must carry `@Audited('<action>')` metadata (in addition to its
  §7.4 permission decorator). The route-enumeration test asserts **every POST/PUT/PATCH/DELETE
  route carries it** — a new unaudited route fails the build, named (ET-3 3.2's negative
  control is a deliberately undecorated fixture route registered only in the test app).
- A request-scoped audit tally (via `AsyncLocalStorage` correlation context) is asserted by a
  global interceptor after each successful mutating response in dev/test: ≥1 audit record was
  written for this correlation id, else the interceptor throws. Discipline is therefore
  checked at both build time and run time.
- Lint fence: `prisma.auditLog.create` is callable only inside `AuditService`
  (dependency-cruiser path rule), so records go through the timestamp-controlled,
  redaction-aware service.

### 9.5 Redaction (shared with logging — NFR-011)

One redaction module in `packages/core`: named-field deny-list (`password`, `passwordHash`,
`apiKey`, `token`, `secret`, `authorization`, `clientSecret`, `recoveryCode`, `totp`,
`cookie`) applied deep to audit `before/after` payloads **and** wired into Pino's `redact`
paths; plus pattern scrubbing (PEM blocks, `sk-`-style key shapes, base64 runs ≥ 32 chars in
known-sensitive fields). ET-5 5.8 scans prove it holds.

---

## 10. LLM provider abstraction (`packages/llm`)

### 10.1 Interface

```
LLMProvider
  readonly slug: 'anthropic' | 'openai' | 'ollama'
  readonly capabilities: { streaming: boolean; embeddings: boolean; vision: boolean }
  readonly verification: 'mock-verified'        // literal type in Phase 1 — see §10.5
  complete(req: CompletionRequest): Promise<CompletionResult>
  stream(req: CompletionRequest): AsyncIterable<CompletionDelta>   // capability-gated
  embed(req: EmbedRequest): Promise<EmbedResult>                    // capability-gated
```

All request/response shapes are Zod schemas in `packages/core` and validated at the adapter
boundary in **both directions** (FR-060/NFR-003). Invoking an undeclared capability throws
typed `CapabilityNotSupportedError` (FR-060).

### 10.2 The transport seam (ADR-008)

Adapters for Anthropic and OpenAI use the **official SDKs constructed with an injected
`fetch`** (`Transport = typeof fetch`); Ollama uses plain `fetch` against its REST API via the
same seam. Tests inject a `MockTransport` returning fixture `Response`s captured from published
provider response shapes — the entire suite runs with **zero API keys** (FR-003, Gate 1).
`MockTransport` lives under `packages/llm/testing` and is imported only by test/dev fixtures;
the production configuration profile has no code path that can select it (FR-065): the DI
factory chooses real-`fetch` unconditionally outside `NODE_ENV=test` and a unit test asserts
that.

Credentials: the adapter factory resolves `LlmProvider.credentialName` through
`SecretStore.get(...)` at call time and passes the value via `SecretValue.use(...)` directly
into the SDK constructor — never through a DB column read, an env var, or a log (FR-061).

### 10.3 Error taxonomy

Typed `ProviderError { provider, status?, class: 'auth' | 'rate_limit' | 'server' |
'timeout' | 'connectivity' | 'contract', retryable: boolean, message }` — raw transport errors
never escape the adapter (FR-061/FR-063). `errorClass` in `usage_records` uses the same union.

### 10.4 Usage recording

A `UsageRecorder` wraps every adapter call (decorator composition in the package, not caller
discipline): one `usage_records` row per call, success or failure, with provider, model,
feature, nullable agentId, tokens in/out, estimated cost (rates from `SystemSetting
llm.modelRates` — never call-site constants), latency, errorClass, retryCount, correlationId
(FR-064). Message text never touches the row.

### 10.5 "Unverified against live endpoints" — the labelling mechanism (Gate 1 / FR-065)

- Code: each adapter exports `verification: 'mock-verified'` and a file-top banner comment.
- Data: `LlmProvider.verificationStatus` can only be `UNCONFIGURED` or `MOCK_VERIFIED` in
  Phase 1 — no Phase 1 code path writes `LIVE_VERIFIED` (the enum value exists for Phase 2's
  live smoke test).
- Portal: the providers page renders "not configured / **unverified against live endpoints**"
  from that field; never "connected/healthy".
- Docs: `LOCAL_SETUP.md` and the phase report state it and list what live verification
  requires (keys, a smoke-test script, recorded fixtures diffed against live responses).
- No routing, failover or budget caps exist anywhere in the package (FR-066); callers pass the
  provider slug explicitly as configuration.

---

## 11. Agent runtime skeleton (`packages/agents`)

### 11.1 Config shape (Zod `AgentConfigSchema` in `core`, hydrated from the `Agent` row)

identity (id, slug, name, role), systemInstructions, toolAllowlist (**must be `[]` in
Phase 1** — schema-enforced; a non-empty list fails load, FR-070), provider/model reference,
maxDurationSeconds, tokenBudget?, costBudgetUsd?, heartbeatIntervalSeconds,
staleThresholdSeconds. Validation failure names the field and no partially configured agent
runs.

### 11.2 Envelopes

Nine Zod-discriminated-union types (§5.6 enum). Every emission goes through
`runtime.emit(envelope)` → validate → persist `AgentMessage` (Postgres, not memory — FR-072).
Malformed envelopes are rejected pre-persist with the failing field logged. `APPROVAL_REQUIRED`
persists and **nothing else happens** (no approval workflow until Phase 2 — stated in the phase
report, FR-071).

### 11.3 Execution and heartbeats

Agent execution is a BullMQ job on the `agents` queue. While the job runs, the runtime emits
`AGENT_HEARTBEAT` every `heartbeatIntervalSeconds` and updates `Agent.lastHeartbeatAt` (an
in-process interval *inside a running job* is permitted — it is not the durability mechanism
for scheduled work). Staleness is detected **out of process** by the durable repeatable
`system:agent-staleness-sweep` job (every 60 s): `status=RUNNING AND lastHeartbeatAt <
now − staleThresholdSeconds` ⇒ mark `STALE`→`FAILED`, emit `TASK_FAILED`, fail the BullMQ job,
audit (FR-073; SECURITY_MODEL §3).

### 11.4 Budget/timeout enforcement points — in the loop, never in prompt text (FR-074)

The runtime loop checks **after every step**: elapsed ≥ maxDurationSeconds ⇒ halt +
`TASK_BLOCKED(reason=timeout)`; cumulative tokens/cost (from usage records of this run) ≥
budget ⇒ halt + `TASK_BLOCKED(reason=budget)`. In-flight LLM calls carry an `AbortController`
deadline. No budget or limit text is ever placed in the system prompt as a control — prompts
may *mention* limits for context, but enforcement is exclusively these loop checks.

---

## 12. Queue and scheduler design

### 12.1 Topology

Two BullMQ queues on the shared Redis: **`system`** (maintenance: `session-sweep`,
`agent-staleness-sweep`) and **`agents`** (agent runtime jobs). Default job options: 3
attempts, exponential backoff (base 5 s), per-job timeout via handler-level deadline;
failed jobs retained (visible + rerunnable, FR-081). `apps/worker` hosts the processors;
concurrency small and configurable.

### 12.2 What lives where (Redis vs Postgres)

| Redis (ephemeral-ish, AOF-persisted) | Postgres (durable record) |
|---|---|
| Queue state: waiting/active/delayed jobs, Job Scheduler definitions | `JobExecution` history rows (FR-083 — survives `FLUSHALL`) |
| Rate-limit and lockout counters | Audit records for job lifecycle transitions that are security-relevant |
| — | Agent envelopes/heartbeats (`agent_messages`) |

### 12.3 Repeatable-job identity — restarts cannot duplicate (ADR-010)

The scheduler app's **only** job is: on boot, call `queue.upsertJobScheduler(schedulerId,
repeatOpts, template)` for each definition with **stable, code-defined scheduler ids**
(`system:session-sweep`, `system:agent-staleness-sweep`). Upsert is idempotent by id: restart
⇒ same id ⇒ same single definition (ET-4 4.7). The scheduler then idles; it consumes nothing,
stores nothing in memory that matters (FR-082 — schedule state lives in Redis; the scheduler
being down does not stop the worker executing due occurrences).

### 12.4 How ET-4 is made provable

- Redis persistence per ADR-002 (AOF everysec + named volume + `noeviction`) keeps delayed
  jobs and scheduler definitions across a real container stop/start.
- Execution history is in Postgres, so pre-restart history survives even a Redis wipe
  (ET-4 4.8) — and re-registration is idempotent (12.3), covering even the pathological
  "Redis volume lost" case for *repeatable* definitions (delayed one-off jobs do depend on
  Redis persistence; that dependency is exactly what ADR-002 configures and what ET-4 4.2/4.6
  tests against real containers).
- Worker records `JobExecution` rows at start (RUNNING) and completion/failure; QueueEvents
  listener backstops `STALLED`.
- No `setTimeout`/`setInterval` is a sole mechanism for scheduled work anywhere (ET-4 4.10);
  the only in-process interval is the heartbeat inside an already-running job (§11.3), which
  the code review note in the phase report will call out with this justification.

### 12.5 Observability (FR-085)

`GET /api/jobs/status` (`job:read`): per-queue counts (waiting/active/completed/failed/
delayed) + Job Scheduler list. `GET /api/jobs/history` (`job:read`): paged `JobExecution`
query.

---

## 13. API surface (Phase 1 — complete)

Base `/api`. All routes: Zod-validated input, structured errors, correlation id, rate limits
(§6.3), audit per §9. Guard column = the §7.4 decorator. Response shapes are the Zod schemas
in `packages/core` (names given).

**Public (`@Public()`)**

| Route | Req / Res |
|---|---|
| `POST /auth/login` | `{email, password}` → `200 {user: UserSummary, mfaRequired: boolean, csrfToken?}` + cookie; generic 401 on failure; 423-style generic lockout body on lockout; 429 on IP limit |
| `POST /auth/mfa/verify` | (PENDING_MFA cookie) `{code?} \| {recoveryCode?}` → `200 {user, csrfToken}` + rotated cookie |
| `POST /invitations/:token/accept` | `{password}` → `201 {ok: true}`; generic 400 for consumed/expired/mutated token — no existence disclosure |
| `GET /system-health` | `200 {status, deps: {postgres: 'up'\|'down', redis: 'up'\|'down'}}` — booleans only, no versions/connection detail (FR-091) |

**Self-service (`@SelfService()`)** — logout; `GET /auth/me` → `{user, roles, permissions,
csrfToken}`; MFA enrol/activate/disable (§6.4); `POST /auth/password` `{current, new}`;
`GET /auth/sessions`; `DELETE /auth/sessions/:id`.

**Permission-guarded**

| Route | Permission | Notes |
|---|---|---|
| `GET /users`, `GET /users/:id` | `user:read` | `UserSummary` — never passwordHash |
| `PATCH /users/:id` | `user:update` | displayName, status; admin cannot target owner |
| `POST /users/:id/lockout/clear` | `user:update` | clears §6.3 lockout |
| `PUT /users/:id/roles` | `role:assign` | the §6.6 choke point |
| `GET /users/:id/sessions` | `session:read` | |
| `POST /users/:id/sessions/revoke` | `session:revoke` | bulk revoke (ET-1 1.11) |
| `GET /roles`, `GET /permissions` | `role:read` | |
| `POST /invitations` | `user:invite` | `{email, roleId}` → invitation + **the single-use link rendered for manual conveyance** (Gate 1 — no mail transport); role may not be `owner` |
| `GET /invitations`, `DELETE /invitations/:id` | `user:invite` | list pending / revoke |
| `POST /secrets` | `secret:create` | `{name, value, description}` → `SecretMetadata` (no value) |
| `GET /secrets`, `GET /secrets/:id` | `secret:read` | metadata + fingerprint only |
| `POST /secrets/:id/rotate` | `secret:rotate` | `{value}` → metadata |
| `DELETE /secrets/:id` | `secret:delete` | refuses if referenced by a provider/MFA credential |
| `GET /settings` / `PUT /settings/:key` | `settings:read` / `settings:write` | |
| `GET /providers` / `PATCH /providers/:id` | `provider:read` / `provider:write` | enabled, baseUrl, defaultModel, credentialName (reference) |
| `GET /audit` | `audit:read` | filters: actor, action, target, time range; reverse-chronological, paged; payloads redacted (FR-053) |
| `GET /usage` | `usage:read` | paged usage records |
| `GET /agents`, `GET /agents/:id/activity` | `agent:read` | activity = envelope query in emission order |
| `POST /agents`, `PATCH /agents/:id`, `POST /agents/:id/run` | `agent:write` | `run` enqueues a skeleton demo run (mock provider) |
| `GET /jobs/status`, `GET /jobs/history` | `job:read` | §12.5 |

OpenAPI is generated (`@nestjs/swagger`); a test asserts it contains **no registration
operation** (FR-020) and that example payloads contain no secret material.

---

## 14. Portal shell — architecture constraints

(The UI/UX designer owns tokens/layout — BL-501/502; these are the architectural constraints.)

- `apps/web` is Next 15 App Router. It holds **no secrets** of any kind: its only config is
  `SUNIL_API_INTERNAL_URL` (server-side only). **Browser↔API is strictly same-origin
  (ADR-011):** `next.config` `rewrites()` proxies `/api/:path*` to `SUNIL_API_INTERNAL_URL`,
  client code fetches relative `/api/...` paths, and no CORS configuration exists anywhere.
  Server components fetch `SUNIL_API_INTERNAL_URL` directly with the incoming cookie
  forwarded; Next middleware redirects unauthenticated visitors to `/login` (FR-101) — and
  the API enforces independently (UI is never the control). Invitation links are built
  client-side from `window.location.origin` — no public-origin config variable is needed.
- Pages: `/login`, `/mfa`, `/invite/[token]`, the authenticated shell with the **full
  ARCHITECTURE §3 navigation list** — Phase 2–7 destinations rendered visibly disabled, none
  linking to a broken page (Gate 1 / Q10).
- Nav filtering by the `permissions` array from `/api/auth/me`; hidden ≠ protected (ET-2 2.6).
- `<SunilPresence />` in `packages/ui`: props-driven `idle | thinking | speaking`, rAF loop +
  resize listener cleaned up on unmount, devicePixelRatio-aware, `aria-hidden`,
  `prefers-reduced-motion` honoured (FR-102, NFR-016).
- Dashboard renders structure + placeholder content **labelled as placeholder** (A-09,
  NFR-019). Dark theme only, tokens from `packages/ui` (FR-100/103); no hard-coded brand
  colours outside token definitions.

---

## 15. Deployment — Docker Compose

### 15.1 Services

| Service | Image / build | Health check | Depends on (healthy) |
|---|---|---|---|
| `postgres` | pinned `pgvector/pgvector:pg16` tag | `pg_isready -U $POSTGRES_USER` | — |
| `redis` | `redis:7.4-alpine` + command flags: `--appendonly yes --appendfsync everysec --maxmemory-policy noeviction` | `redis-cli ping` | — |
| `api` | multi-stage Node 22 build (`pnpm deploy` pruned) | `GET /api/system-health` | postgres, redis |
| `worker` | same base image, worker entry | process-level (`node healthcheck` pinging its own liveness file/Redis) | postgres, redis |
| `scheduler` | same base image, scheduler entry | as worker | redis |
| `web` | Next standalone build | `GET /` | api |
| `ollama` | `ollama/ollama` — **optional Compose profile `ollama`** | — | — |

Startup order via `depends_on: condition: service_healthy`; API runs
`prisma migrate deploy` as its entry step before listening (idempotent, NFR-009). Only `web`
and `api` publish host ports (FR-090); postgres/redis are reachable on the compose network
only, with **optional** host publishing behind a `debug` profile for developer inspection.
All **browser** traffic goes to `web` only (same-origin proxy, §14/ADR-011); `api`'s
published port exists for direct non-browser access (QA exit-test suites, dev tooling), not
for the portal.

### 15.2 Volumes

Named volumes only for data: `pgdata:/var/lib/postgresql/data`, `redisdata:/data`. Survive
`docker compose down` (no `-v`); documented in LOCAL_SETUP (ET-4 4.9, FR-090).

### 15.3 Windows-specific pitfalls (binding guidance for DevOps — R-03)

1. **Named volumes, never bind mounts, for `node_modules` and data dirs** — bind-mounted
   node_modules on Windows is both slow and symlink-hostile with pnpm.
2. `.gitattributes` LF enforcement for anything executed inside a container (§3.3).
3. No host `psql` exists: every DB operation in docs goes through
   `docker compose exec postgres psql …` or Prisma (FR-093).
4. Host-port conflicts (5432/6379/3000) are common: all published ports come from env
   (`SUNIL_PORT_WEB`, `SUNIL_PORT_API`, …) with documented defaults and a troubleshooting
   entry.
5. Long-path: keep workspace paths short (`C:\repo\SUNIL` is fine); no generated path segments
   near the 260-char limit.
6. **Dev loop:** infra (`postgres`, `redis`) in Compose; `api`/`web`/`worker`/`scheduler` run
   on the host via `turbo dev` for hot reload. The **full six-service Compose build is the
   acceptance configuration** — ET runs and the LOCAL_SETUP walk-through use it.

---

## 16. Configuration inventory (names only — values never appear anywhere)

`DATABASE_URL`, `REDIS_URL`, `SUNIL_MASTER_KEY`, `SUNIL_MASTER_KEY_VERSION`,
`SUNIL_MASTER_KEY_PREVIOUS` (optional), `SUNIL_OWNER_EMAIL`, `SUNIL_OWNER_INITIAL_PASSWORD`
(bootstrap-time only), `SUNIL_COOKIE_SECURE`, `SUNIL_SESSION_IDLE_HOURS=8`,
`SUNIL_SESSION_ABSOLUTE_HOURS=24`, `SUNIL_AUTH_MAX_FAILURES=5`,
`SUNIL_AUTH_FAILURE_WINDOW_MIN=15`, `SUNIL_AUTH_LOCKOUT_MIN=15`,
`SUNIL_RATE_SESSION_PER_MIN=100`, `SUNIL_RATE_AUTH_IP_PER_MIN=20`,
`SUNIL_INVITE_TTL_HOURS=72`, `SUNIL_AGENT_HEARTBEAT_SEC=30`, `SUNIL_AGENT_STALE_SEC=90`,
`SUNIL_TIMEZONE=Australia/Hobart`, `ANTHROPIC_API_KEY` (name documented, unset in this
environment), `OPENAI_API_KEY` (same), `OLLAMA_BASE_URL`, `SUNIL_PORT_WEB`, `SUNIL_PORT_API`,
`SUNIL_API_INTERNAL_URL` (server-side only; default `http://api:3001` in Compose,
`http://localhost:3001` for host-run dev — the Next rewrite target and server-component
fetch base, ADR-011).

**Deliberately absent (Amendment A1):** no `NEXT_PUBLIC_API_URL` (the client uses relative
same-origin paths; nothing API-shaped belongs in the bundle) and **no CORS/allowed-origins
variable of any kind** — the API is same-origin only by design. A future cross-origin client
requires a new ADR, not a config addition.

Every variable: validated by a Zod env schema at process start (fail fast, name the variable,
never print secret values — FR-004); documented in `.env.example` with comment + placeholder;
the FR-092 diff test keeps code and file in lockstep.

---

## 17. FR traceability

| FR group | Requirements | Delivered by |
|---|---|---|
| Monorepo & tooling | FR-001–004 | §3 (layout, DAG, pipeline), §16 (env validation), §4 (versions) |
| Database & schema | FR-010–015 | §5 (complete schema, conventions, migration, bootstrap) |
| AuthN/AuthZ & hardening | FR-020–031 | §6 (sessions, cookies, lockout, MFA, CSRF, headers), §7 (RBAC, default deny), §13 (routes); ADR-001/003/009 |
| Secret storage | FR-040–044 | §8; ADR-006 |
| Audit | FR-050–053 | §9; ADR-005 |
| LLM abstraction | FR-060–066 | §10; ADR-008 |
| Agent runtime | FR-070–074 | §11 |
| Queues/scheduling | FR-080–085 | §12; ADR-002/010 |
| Containers & DX | FR-090–093 | §15, §16 |
| Portal shell | FR-100–105 | §14 (constraints; tokens/layout owned by BL-501/502) |
| NFRs | NFR-001–019 | NFR-001 §7.4; NFR-002 §5/§8; NFR-003 §10.1/§16; NFR-004 §6.7; NFR-005 §16 + THREAT_MODEL T-16; NFR-006/007 measured by QA (no design blocker); NFR-008 §12; NFR-009 §5.8/§12.3/§15.1; NFR-010 §12/§15.1; NFR-011 §9.5; NFR-012 §9.1 correlationId; NFR-013 §15.3/LOCAL_SETUP; NFR-014 §3.3; NFR-015 QA-owned; NFR-016 §14; NFR-017 §15.3; NFR-018 §8.1/§10.1/§11 interfaces; NFR-019 §10.5 |

**Every one of the 59 FRs is satisfiable by this design; none is flagged unsatisfiable.**
Two are satisfied only in the honest, limited sense their own text requires: FR-061–063
adapters are **mock-verified only** (Gate 1; §10.5), and FR-071's `APPROVAL_REQUIRED` persists
without any approval workflow (Phase 2).

---

## 18. Warnings to engineers before build starts

1. **Do not substitute the `argon2` (node-gyp) package for `@node-rs/argon2`** — it drags a
   native toolchain onto Windows and violates §4. Same rule for any node-gyp dependency:
   adding one requires an ADR.
2. **Never call `prisma.$transaction` ad hoc for mutations** — use the `UnitOfWork` helper or
   your mutation will not be covered by audit-before-commit and the runtime tally will throw.
3. **BullMQ repeatables:** use only `upsertJobScheduler` with the stable ids in §12.3. The
   legacy `repeat` option creates key-derived duplicates on option changes — it is banned.
4. **`maxmemory-policy noeviction` on Redis is load-bearing.** Eviction silently destroys
   BullMQ state; do not "fix" memory pressure by changing it.
5. **`SecretValue` never crosses a serialisation boundary.** If you need the plaintext,
   you are inside `use(fn)` on the server or you are doing it wrong.
6. **Prisma client extension order matters:** the append-only guard must wrap the exported
   client; never import `@prisma/client` directly in apps (dependency-cruiser enforces it —
   don't fight the fence, ask the architect).
7. **The prototype directory is read-only** (FR-001). Tokens are *extracted*, files untouched.
8. **Zod major:** import zod only via `packages/core` re-export — a second major in the tree
   will produce incompatible schema types across workspaces.
9. **Scope fence:** if you find yourself writing routing rules, chat, tasks, memory or
   approvals — stop; it is Phase 2 (requirements §1.3) and will be rejected at review.

---

## 19. Amendment log (post-Gate-2, during build)

Rulings issued by the Solution Architect on questions escalated from the build. Each is
binding; inline sections above have been updated to match.

| # | Ruling | Sections/ADRs touched |
|---|---|---|
| **A1** | **No CORS in Phase 1.** Browser↔API is strictly same-origin via a Next rewrite proxy (`/api/:path*` → `SUNIL_API_INTERNAL_URL`); client fetches are relative; `NEXT_PUBLIC_API_URL` removed; no allowed-origins variable exists by design. **Phase 2 note:** the WebSocket gateway will not traverse a Next rewrite cleanly — Phase 2 must make its own ingress decision (new ADR) rather than discovering this late. | §6.7, §14, §15.1, §16; **ADR-011** |
| **A2** | **CSRF `Origin` check deferred.** The per-session header token (ADR-009) is the FR-028 control and is sufficient for Phase 1; the belt-and-braces `Origin` validation is explicitly deferred to the Phase 2 ingress ADR. Documents corrected so no control is claimed that the code does not have. | ADR-009; THREAT_MODEL T-04 |
| **A3** | **OpenAPI is not served over HTTP in Phase 1.** The generated document is a build/test artifact (gitignored `openapi.json`); the route-enumeration test failing on Swagger UI's undeclarable asset routes is §7.4 working as designed. Any future served variant must be a declared route with a permission from the `core` catalogue, using a static renderer rather than an asset-sprawling UI. | §7.4 (constraint recorded here) |
| **A4** | **pnpm 11 rename.** The build-script allowlist is `pnpm.allowBuilds` (formerly `onlyBuiltDependencies`). The age-gate's auto-added `minimumReleaseAgeExclude` block (`@anthropic-ai/sdk@0.112.4`, `typescript-eslint@8.65.0` family) is flagged for **Security Reviewer sign-off** under THREAT_MODEL T-16. | §3.3; ADR-004, ADR-007; THREAT_MODEL T-16 |
| **A5** | **Audit `BEFORE TRUNCATE` trigger recorded as-built** (stronger than §9.3 originally specified; endorsed). Binding test-harness rule: never reset `audit_logs`; scope audit assertions by `correlationId`. | §9.3 |
