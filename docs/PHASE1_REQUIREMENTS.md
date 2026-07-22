# SUNIL — Phase 1 (Foundation) Requirements Specification

_Document owner: Business Analyst / Product Manager (Minions delivery team)_
_Status: **Draft for Gate 1 review** — requires human confirmation of §8 before build starts_
_Source documents: `README.md`, `docs/IMPLEMENTATION_PLAN.md`, `docs/SUNIL_ARCHITECTURE.md`, `docs/SECURITY_MODEL.md`, `docs/CURRENT_ARCHITECTURE.md`, `docs/INTEGRATIONS.md`, `prototype/sunil-command-centre.html`_

> **Boundary note.** This document specifies *what* Phase 1 must do and *how it will be
> tested*. It makes **no stack, framework or design decisions** — those are already made in
> `SUNIL_ARCHITECTURE.md` §1 and are restated here only to make them testable. Where the
> architecture documents are silent on an implementation detail, this document records it as
> an **assumption** (§6) or an **open question** (§8) for the Solution Architect or the owner
> to resolve. It contains no dates, budgets or delivery commitments.

---

## 1. Purpose and scope

### 1.1 Purpose

Phase 1 delivers **a running, secured, empty platform**: the monorepo, database, identity and
access control, secret storage, audit trail, provider and agent abstractions, durable job
infrastructure, local container stack and the portal shell — with no end-user feature on top of
it. Its value is that every later phase can be built without re-litigating security, durability
or project structure, and that the five exit tests in §5 prove the foundations actually hold.

Phase 1 is complete when the five exit tests pass and a developer can bring the whole stack up
on a clean Windows 11 machine by following `docs/LOCAL_SETUP.md`.

### 1.2 In scope

| # | Item | Source |
|---|---|---|
| 1 | pnpm + Turborepo monorepo (`apps/web`, `apps/api`, `apps/worker`, `apps/scheduler`, `packages/core`, `db`, `llm`, `agents`, `ui`) | IMPLEMENTATION_PLAN Phase 1; ARCHITECTURE §1 |
| 2 | PostgreSQL 16 + pgvector, Prisma schema for the **identity**, **settings** and **audit** groups, initial migration | Phase 1; ARCHITECTURE §4 |
| 3 | Session auth with public registration **disabled** (single owner + invited users), RBAC roles/permissions, optional TOTP MFA, secure cookies, CSRF, rate limiting | Phase 1; SECURITY_MODEL §1 |
| 4 | `SecretStore` abstraction with AES-256-GCM envelope encryption | Phase 1; SECURITY_MODEL §2 |
| 5 | Audit log service — every mutating endpoint writes an audit record | Phase 1; SECURITY_MODEL §9 |
| 6 | `packages/llm`: provider abstraction + Anthropic, OpenAI and Ollama adapters + usage logging | Phase 1; ARCHITECTURE §2.4 |
| 7 | `packages/agents`: config-driven agent skeleton, structured message envelopes, heartbeats | Phase 1; ARCHITECTURE §2.1–2.2 |
| 8 | BullMQ + Redis wiring, scheduler app producing repeatable jobs, execution history persisted to Postgres | Phase 1; ARCHITECTURE §2.3 |
| 9 | Docker Compose (postgres/pgvector, redis, api, web, worker, scheduler), `.env.example`, `docs/LOCAL_SETUP.md` | Phase 1; ARCHITECTURE §6 |
| 10 | Base portal: navigation shell, design tokens extracted from the prototype, `<SunilPresence />` canvas component, dark theme | Phase 1; ARCHITECTURE §3; CURRENT_ARCHITECTURE reuse table |

### 1.3 Out of scope — explicit exclusions

Phase 1 is **not** a usable assistant. The following are Phase 2–7 and **must not be built
early**, however tempting the adjacency. Any pull request implementing one of these is out of
scope for Phase 1 and should be rejected or moved to the Phase 2 backlog.

| Excluded | Belongs to | Why it will be tempting |
|---|---|---|
| SUNIL chat UI, WebSocket streaming, conversation history, attachments | Phase 2 | The portal shell will look empty without it |
| Orchestrator v1 — intent classification, task decomposition, agent selection | Phase 2 | The agent runtime skeleton exists and "almost" does this |
| **Model routing rules table, routing UI, primary/fallback failover, budget caps, usage dashboard** | Phase 2 | `packages/llm` exists; Phase 1 explicitly says *"no routing UI yet"*. Phase 1 logs usage; it does not route or cap |
| Tasks, subtasks, reminders, projects, clients, recurrence | Phase 2 | Prisma schema is being written anyway |
| Memory service, pgvector embeddings/retrieval, memory browser | Phase 2 | pgvector is installed in Phase 1 — installed ≠ used |
| Notification centre, approval centre, approval gates, trusted rules | Phase 2 | The audit service touches similar tables |
| Workflow engine, typed JSON workflow graph, FlowProducer dependency chains, workflow builder | Phase 2/3 | BullMQ is wired in Phase 1 |
| Daily brief, scheduling at 07:15 Australia/Hobart, weather, calendar, "remaining from yesterday" | Phase 3 | The scheduler app exists |
| Microsoft Graph / Teams / Jira / Ezy Clean mailbox / support adapters; `packages/integrations`; `packages/memory` | Phase 3–4 | The `SecretStore` is exactly what OAuth tokens need |
| Gemini and OpenAI-compatible generic LLM adapters | Phase 2+ | The interface supports them; Phase 1 names only Anthropic, OpenAI, Ollama |
| AI teams, team templates, multi-agent execution, review gates | Phase 5 | The agent table shape suggests it |
| Computer control, command executor, permission tiers 1–8, browser automation | Phase 6 | SECURITY_MODEL describes it in full |
| Prompt-injection classifier and its CI suite, penetration checklist, production deployment, backup/recovery docs, monitoring | Phase 6/7 | Security work feels like it should be "done now" |
| Voice in/out, "Brief Me" audio, speech synthesis | Phase 3 | It exists in the prototype |
| Any production or externally reachable deployment; any real outbound email | Phase 7 / never in dev | SECURITY_MODEL §10 forbids it during development |

Also explicitly excluded from Phase 1: multi-tenancy, public sign-up, billing, mobile apps,
and any dashboard widget bound to live business data (the dashboard shell renders structure and
static/placeholder content only — clearly labelled as such per architectural rule 7).

---

## 2. Personas and roles (Phase 1 only)

Phase 1 has **no external users**. Four actors matter.

### 2.1 P-1 — Owner (Isuru)

The single principal of the system; the only account that exists after bootstrap. Technical,
operates on `Australia/Hobart`. In Phase 1 he can: sign in, complete MFA, view the portal shell,
manage users/roles, invite a user, store and rotate a secret, and read the audit log. He cannot
yet do anything that produces business value — this is expected and must be stated in the phase
report. Holds the `owner` role, which carries every permission including `*:admin`-class grants.

**Needs from Phase 1:** confidence that his credentials and API keys cannot leak; a login that
cannot be brute-forced; a visible audit trail; a system that survives a machine restart.

### 2.2 P-2 — Invited user

A future collaborator (e.g. another developer or an assistant) created **only** by owner
invitation. In Phase 1 this persona exists to prove that RBAC actually restricts: an invited
user with a lesser role must be blocked from owner-only routes. No self-registration path exists
for this persona at any point.

**Needs from Phase 1:** accept an invitation, set a password, sign in, and be correctly denied
everything not granted.

### 2.3 P-3 — System/agent actor (non-human principal)

A configured agent executed by the agent runtime. In Phase 1 it does no real work: it is
instantiated from configuration, emits structured message envelopes and heartbeats, and is
recorded in the activity log. Critically, it is an **auditable actor** — audit records must be
able to name an agent, not only a human (SECURITY_MODEL §9). It has no tool access and no
outbound network authority in Phase 1.

### 2.4 P-4 — Operator / developer (build-time persona)

The engineer bringing the stack up locally on Windows 11. Not a system role; included because
`docs/LOCAL_SETUP.md`, `.env.example` and the Compose stack are written *for* this persona and
the Phase 1 developer-experience NFRs are measured against them.

### 2.5 Role/permission baseline (Phase 1)

Roles are data, not code. The Phase 1 seed must create at minimum:

| Role | Intent | Illustrative permissions |
|---|---|---|
| `owner` | Full authority; exactly one holder | all permissions |
| `admin` | Manage users, integrations, settings; cannot alter the owner account | `user:read`, `user:invite`, `settings:write`, `audit:read`, `secret:write` |
| `viewer` | Read-only; used to prove default-deny | `dashboard:read`, `audit:read` |
| `agent` | Non-human principal; no portal login | none in Phase 1 |

> The exact permission string vocabulary is an **architecture/implementation decision** and is
> deferred to the Solution Architect (see §8, Q4). The requirement is only that permissions are
> rows, routes declare them, and the default is deny.

---

## 3. Functional requirements

Priority key: **MUST** = Phase 1 fails without it. **SHOULD** = expected, may be descoped only
with a recorded decision. **COULD** = desirable, drop first under pressure.

### 3.A Monorepo and tooling

#### FR-001 — Monorepo scaffold — MUST
The repository is a pnpm workspace orchestrated by Turborepo containing the apps and packages
listed in `SUNIL_ARCHITECTURE.md` §1 "Monorepo layout".

- **Given** a clean checkout on Windows 11 with Node v22.14.0 and pnpm 11.8.0
  **When** the operator runs the documented install command from the repository root
  **Then** installation completes with exit code 0 and the directories `apps/web`, `apps/api`,
  `apps/worker`, `apps/scheduler`, `packages/core`, `packages/db`, `packages/llm`,
  `packages/agents`, `packages/ui` all exist and are registered workspace members.
- **Given** the installed workspace **When** the operator runs the repo-wide build task
  **Then** every workspace package builds with exit code 0 and no TypeScript errors.
- **Given** the installed workspace **When** the operator runs the repo-wide lint and typecheck
  tasks **Then** both exit 0.
- **Given** `prototype/` **When** any Phase 1 build task runs **Then** the prototype files are
  unmodified (byte-identical to the Phase 0 commit) — they are read-only design reference.

#### FR-002 — Shared type/contract package — MUST
`packages/core` holds domain types, message contracts and shared Zod schemas, and is consumed by
at least `apps/api` and one other workspace member.

- **Given** a Zod schema exported from `packages/core`
  **When** `apps/api` and `apps/worker` import it
  **Then** both compile against the same type and no duplicate local definition of that schema
  exists elsewhere in the repo.

#### FR-003 — Test harness — MUST
Every app and package can run an automated test suite from a single root command, and the suite
runs without network access to any third-party provider.

- **Given** a machine with **no LLM provider API keys configured**
  **When** the operator runs the repo-wide test task
  **Then** the full suite executes and passes, with all external providers served by mocked
  transports (FR-065).
- **Given** the test task **When** it completes **Then** a machine-readable result summary
  (pass/fail counts per workspace) is produced for the QA engineer's phase report.

#### FR-004 — Configuration and `.env.example` — MUST
All runtime configuration comes from environment variables, validated at process start; the
repository contains `.env.example` documenting **every** variable with a comment and a safe
placeholder, and **no real values**.

- **Given** a required environment variable is missing or malformed
  **When** `apps/api`, `apps/worker` or `apps/scheduler` starts
  **Then** the process exits non-zero within 10 seconds with a message naming the offending
  variable, and the message does **not** print the value of any secret variable.
- **Given** `.env.example` **When** it is scanned by the security reviewer
  **Then** it contains no key, token, password or connection string with a real value, and every
  variable read anywhere in the codebase appears in it.
- **Given** the repository **When** `git status` is run after a normal dev session
  **Then** `.env` and any `*.local` env files are ignored and untracked.

### 3.B Database and schema

#### FR-010 — PostgreSQL 16 with pgvector — MUST
The database service runs PostgreSQL 16 from a pgvector-capable image, and the `vector`
extension is enabled by migration.

- **Given** the Compose stack is up
  **When** the operator connects to the database via the API container or a Compose `exec`
  (no local `psql` client is available on the host)
  **Then** `SELECT extname FROM pg_extension` includes `vector`.
- **Given** pgvector is enabled **When** Phase 1 code is inspected **Then** no embedding column
  is populated and no retrieval query exists — installation only (see §1.3 exclusions).

#### FR-011 — Identity schema group — MUST
Prisma models exist for users, roles, permissions, the role↔permission relation, the user↔role
relation, sessions, invitations and MFA secrets/recovery codes.

- **Given** the initial migration is applied
  **When** the schema is introspected
  **Then** tables exist for users, roles, permissions, role-permission, user-role, sessions and
  invitations; all use UUID primary keys; users have a unique index on email; sessions carry an
  expiry and a revocation marker.
- **Given** a user row **When** it is read **Then** it contains no plaintext password — only a
  hash field — and no plaintext TOTP secret (see FR-041).

#### FR-012 — Settings schema group — MUST
Prisma models exist for system settings (key/value with type and description) and for the
Phase 1 subset of LLM provider configuration records (provider, base URL, enabled state,
default model, credential *reference*), plus `usage_records`.

- **Given** the initial migration is applied **When** the schema is introspected
  **Then** a system settings table and an LLM provider table exist, and the provider table
  stores a **credential reference**, never a credential value.
- **Given** a `usage_records` row **When** it is read **Then** it carries provider, model,
  feature, agent reference (nullable), tokens in, tokens out, estimated cost, latency, error
  state and timestamp (ARCHITECTURE §2.4).

#### FR-013 — Audit schema group — MUST
A Prisma model exists for audit logs carrying actor type (human/agent/system), actor id, action,
target type, target id, before/after payloads (nullable), request correlation id, IP/user-agent
where applicable, outcome (success/failure) and timestamp.

- **Given** the audit table **When** an update or delete is attempted against an existing audit
  row through the application data layer
  **Then** the operation is rejected — the log is append-only (SECURITY_MODEL §9).
- **Given** an audit row for an agent actor **When** it is read **Then** actor type is `agent`
  and the agent identifier is populated, proving non-human actors are representable.

#### FR-014 — Initial migration and owner bootstrap — MUST
A single initial migration creates the Phase 1 schema, and a documented, idempotent bootstrap
seeds the roles, permissions and exactly one owner account.

- **Given** an empty database **When** the migration and bootstrap are run
  **Then** the roles in §2.5 exist with their permissions, exactly one user holds `owner`, and
  the run exits 0.
- **Given** a database already bootstrapped **When** the bootstrap is run again
  **Then** it exits 0 and creates no duplicate roles, permissions or owner accounts.
- **Given** the bootstrap **When** its source and documentation are reviewed
  **Then** the owner's initial credential is supplied by environment/operator input, is **not**
  a hard-coded default committed to the repository, and the operator is required to change it or
  set it at bootstrap time.

#### FR-015 — Schema conventions — SHOULD
UUID primary keys, `createdAt`/`updatedAt` on all mutable entities, `externalId` + unique index
where idempotent import will later apply, and a migration for every schema change.

- **Given** any Phase 1 model **When** reviewed **Then** it uses a UUID primary key and carries
  creation and update timestamps unless it is an append-only log (creation timestamp only).
- **Given** a schema change **When** it is committed **Then** a corresponding migration file is
  committed in the same change and `prisma migrate` reports no drift.

### 3.C Authentication, authorisation and hardening

#### FR-020 — Public registration disabled — MUST
No route, form, API endpoint or UI affordance permits self-registration.

- **Given** the running API **When** a request is made to any plausible registration endpoint
  (`POST /api/auth/register`, `/api/auth/signup`, and any similar path) by an unauthenticated
  caller **Then** the response is 404 or 405 and **no user row is created** under any input.
- **Given** the portal login page **When** it is rendered **Then** it presents no "create
  account", "sign up" or "register" affordance.
- **Given** the generated OpenAPI document **When** it is inspected **Then** it contains no
  registration operation.

#### FR-021 — Invitation flow — MUST
An authorised user (owner/admin) can invite a user by email; the invitee accepts via a
single-use, time-limited token and sets their own password.

- **Given** an authenticated owner **When** they invite `new.user@example.test` with role
  `viewer` **Then** an invitation row is created with a hashed single-use token, an expiry, the
  target role, the inviting actor, and an audit record is written.
- **Given** a valid unexpired invitation token **When** the invitee submits a compliant password
  **Then** a user is created with exactly the invited role, the invitation is marked consumed,
  and an audit record is written.
- **Given** an invitation token that is already consumed, expired, or altered by one character
  **When** it is submitted **Then** the request is rejected, no user is created, and the failure
  is audited.
- **Given** an unauthenticated or insufficiently privileged caller **When** they attempt to
  create an invitation **Then** the request is denied (401/403) and audited.

> The **delivery mechanism** for the invitation link (email vs. copy-to-clipboard) is an open
> question — see §8 Q1. Default recommendation: display the link in the portal for the owner to
> convey manually, because no outbound mail transport exists in Phase 1 and SECURITY_MODEL §10
> forbids real emails in development.

#### FR-022 — Session login and logout — MUST
Session-based authentication with server-side session records.

- **Given** a valid email and password for an active user **When** login is submitted
  **Then** a server-side session row is created, a session cookie is set, the response body
  contains no password hash or secret, and a `auth.login.success` audit record is written.
- **Given** an incorrect password **When** login is submitted **Then** the response is a generic
  failure that does **not** reveal whether the email exists, no session is created, and a
  `auth.login.failure` audit record is written.
- **Given** an authenticated session **When** the user logs out **Then** the server-side session
  is revoked, the cookie is cleared, a subsequent request with the old cookie is rejected 401,
  and the logout is audited.
- **Given** a session whose expiry has passed **When** it is used **Then** the request is
  rejected 401 regardless of cookie validity.

#### FR-023 — Secure session cookies — MUST
Session cookies are `httpOnly`, `SameSite=Lax`, `Secure` (configurable off only for local
plain-HTTP development, with the production default being on), path-scoped, and short-lived
(SECURITY_MODEL §1).

- **Given** a successful login **When** the `Set-Cookie` header is inspected
  **Then** it contains `HttpOnly`, `SameSite=Lax` and (when the secure flag config is enabled)
  `Secure`, and carries an explicit expiry/max-age.
- **Given** the production configuration profile **When** it is loaded **Then** the secure-cookie
  flag defaults to enabled and cannot be disabled by omission (SECURITY_MODEL §8: production
  config never defaults to permissive values).
- **Given** any browser-executable context **When** it attempts `document.cookie`
  **Then** the session cookie is not readable.

#### FR-024 — Server-side session revocation — MUST
Sessions can be revoked individually and in bulk per user, taking effect immediately.

- **Given** two active sessions for one user **When** the owner revokes all sessions for that
  user **Then** the next request on each session returns 401 and the revocation is audited.
- **Given** a user whose role is changed **When** the change is applied **Then** the new
  permissions take effect on the next request without requiring the user to re-authenticate,
  **or** the user's sessions are revoked — whichever behaviour is chosen must be documented and
  consistently tested (see §8 Q5).

#### FR-025 — RBAC roles and permissions — MUST
Roles map to permissions in the database; users hold roles; permissions are checked per route.

- **Given** the seeded roles **When** the permissions API/repository is queried
  **Then** `owner` resolves to a superset of `admin`, which is a superset of `viewer`.
- **Given** a user's role is changed from `viewer` to `admin`
  **When** their effective permissions are recomputed
  **Then** the change is reflected without a code deployment, and the change is audited with
  before/after values (SECURITY_MODEL §9: permission changes are audited).

#### FR-026 — Default-deny route guards — MUST
Every API route declares the permission it requires; a route without a declared permission is
inaccessible rather than open.

- **Given** an authenticated `viewer` **When** they call an endpoint requiring `user:invite`
  **Then** the response is 403, no state changes, and an authorisation-denied audit record is
  written.
- **Given** an unauthenticated caller **When** they call any route other than the explicitly
  public ones (login, invitation acceptance, health)
  **Then** the response is 401.
- **Given** a route added without a permission declaration
  **When** the automated guard-coverage test runs
  **Then** the test **fails**, naming the undeclared route (default deny is enforced by test, not
  by convention).
- **Given** the guard **When** it denies **Then** the response body reveals no information about
  the resource's existence beyond the status code.

#### FR-027 — Optional TOTP MFA — MUST (feature) / optional (usage)
The owner account can enrol in TOTP MFA; MFA is optional per user but, once enrolled, mandatory
at login for that user.

- **Given** an authenticated owner without MFA **When** they begin enrolment
  **Then** a TOTP secret is generated, stored via the `SecretStore` (never in plaintext), and
  presented once for QR/manual entry.
- **Given** enrolment in progress **When** the user submits a valid current TOTP code
  **Then** MFA is activated, a set of single-use recovery codes is issued (displayed once,
  stored hashed), and the activation is audited.
- **Given** an MFA-enrolled user **When** they log in with a correct password
  **Then** the session is not fully established until a valid TOTP code is supplied, and an
  invalid or reused code is rejected and audited.
- **Given** an MFA-enrolled user **When** they disable MFA **Then** re-authentication is
  required and the change is audited.
- **Given** a recovery code **When** it is used once **Then** it cannot be used again.

#### FR-028 — CSRF protection — MUST
All state-changing browser requests carry a CSRF token validated server-side
(SECURITY_MODEL §1).

- **Given** an authenticated browser session **When** a POST/PUT/PATCH/DELETE is sent with a
  valid session cookie but a missing or incorrect CSRF token
  **Then** the request is rejected (403), no state changes, and the rejection is audited.
- **Given** the same request with a valid CSRF token **Then** it succeeds.
- **Given** a safe method (GET/HEAD/OPTIONS) **When** it is sent **Then** no CSRF token is
  required and no state changes.

#### FR-029 — Rate limiting and brute-force lockout — MUST
Rate limiting applies to all API routes; auth endpoints additionally have brute-force lockout.

- **Given** more than the configured threshold of failed login attempts for one account within
  the configured window **When** the next attempt is made — even with the correct password —
  **Then** it is rejected with a lockout response, the lockout is audited, and it clears after
  the configured cool-off or on owner intervention.
- **Given** a client exceeding the general request rate limit **When** it sends a further request
  **Then** it receives 429 with a `Retry-After` header.
- **Given** the lockout thresholds **When** they are inspected **Then** they are configurable via
  environment variables documented in `.env.example`.

> Concrete threshold values are **not specified here** — proposed defaults are in §8 Q6 for
> confirm-or-correct.

#### FR-030 — Password storage and policy — MUST
Passwords are stored only as a salted hash from a memory-hard algorithm; a documented minimum
policy is enforced at set-password time.

- **Given** any password set or change **When** the stored row is inspected
  **Then** it contains a salted hash with algorithm parameters, and the plaintext appears in no
  table, log, response body or error message.
- **Given** a password below the configured minimum length or on the configured weak-password
  rejection list **When** it is submitted **Then** it is rejected with a message that does not
  echo the password.
- **Given** a password change **When** it succeeds **Then** it is audited (event only — never the
  value) and, per FR-024, the session policy for other sessions is applied.

#### FR-031 — Security headers and CSP — SHOULD
The portal and API set a strict Content-Security-Policy and standard security headers, and no
untrusted string is rendered via `innerHTML` (CURRENT_ARCHITECTURE names this as the prototype's
specific hazard).

- **Given** a portal page response **When** headers are inspected **Then** `Content-Security-Policy`,
  `X-Content-Type-Options: nosniff`, `Referrer-Policy` and a frame-ancestors restriction are
  present.
- **Given** the portal source **When** it is scanned **Then** there is no use of `innerHTML`,
  `dangerouslySetInnerHTML` or equivalent with data that is not a compile-time constant.
- **Given** a value containing `<script>alert(1)</script>` stored in any Phase 1 user-editable
  field **When** it is rendered in the portal **Then** it appears as literal text and no script
  executes.

### 3.D Secret storage

#### FR-040 — `SecretStore` abstraction — MUST
A single `SecretStore` interface (put / get / delete / rotate / describe) is the only path by
which credentials are persisted; the Phase 1 implementation is local envelope encryption, and
the interface is shaped so a managed vault can replace it without changing callers
(SECURITY_MODEL §2).

- **Given** the codebase **When** it is searched for credential persistence
  **Then** every write of a credential value goes through `SecretStore`, and no credential column
  holds a plaintext value anywhere in the schema.
- **Given** the `SecretStore` interface **When** a second, in-memory test implementation is
  substituted **Then** all consuming code compiles and its tests pass unchanged, demonstrating
  swappability.

#### FR-041 — AES-256-GCM envelope encryption — MUST
Secrets are encrypted with a per-secret data key, itself encrypted by a master key supplied via
the environment; the algorithm is AES-256-GCM with a unique IV per encryption and an
authentication tag verified on read.

- **Given** a secret is stored **When** the stored row is inspected directly in the database
  **Then** the plaintext does not appear, and the row contains ciphertext, a unique IV, an
  authentication tag and a key/version reference.
- **Given** two writes of the **same** plaintext **When** the rows are compared
  **Then** the ciphertexts differ (unique IV per encryption).
- **Given** a stored secret whose ciphertext or tag has been tampered with by one byte
  **When** it is read **Then** decryption fails loudly with an authentication error, no plaintext
  or partial plaintext is returned, and the failure is audited.
- **Given** the master key environment variable is absent or of the wrong length
  **When** the API starts **Then** it refuses to start (FR-004) rather than falling back to a
  default or generated key.

#### FR-042 — Secrets are never returned by an API — MUST
No API response, at any status code, in any environment, contains a stored secret value
(SECURITY_MODEL §2; ARCHITECTURE rule 5).

- **Given** a stored secret **When** it is read through any API endpoint (list, detail, export,
  settings, OpenAPI example, error response)
  **Then** the response contains only: identifier, label, provider/owner reference, scopes where
  applicable, a masked fingerprint (e.g. last 4 characters or a hash prefix), and timestamps.
- **Given** the full set of Phase 1 API responses exercised by the test suite
  **When** every response body is scanned for the known plaintext of a stored test secret
  **Then** there are **zero** matches. (This is exit test ET-5.)
- **Given** a secret field in the portal **When** it has been saved **Then** it is write-only:
  the UI never repopulates the value and offers only "replace" or "rotate".
- **Given** an unhandled server error while handling a secret **When** the error response is
  produced **Then** it contains no secret value and no stack frame containing one.

#### FR-043 — Secret access auditing and log redaction — MUST
Every secret read, write, rotation and deletion writes an audit record; the logger redacts known
secret patterns and named fields globally.

- **Given** a `SecretStore.get` for a stored secret **When** it completes
  **Then** an audit record exists naming the actor, the secret identifier and the operation —
  and **not** the value.
- **Given** a log statement that includes an object with fields named `password`, `apiKey`,
  `token`, `secret`, `authorization` or `clientSecret`
  **When** it is emitted **Then** those values appear as a redaction marker in the log output.
- **Given** the full log output of the test suite **When** it is scanned for known test secret
  plaintexts **Then** there are zero matches.

#### FR-044 — Secret rotation — SHOULD
A stored secret can be replaced without changing its identifier or breaking references.

- **Given** a secret referenced by an LLM provider record **When** it is rotated
  **Then** the reference is unchanged, subsequent reads return the new value, the previous
  ciphertext is no longer retrievable, and the rotation is audited.

### 3.E Audit log service

#### FR-050 — Audit log service — MUST
A shared audit service writes structured, append-only audit records from any app in the monorepo.

- **Given** the audit service **When** `record()` is called with actor, action, target and
  outcome **Then** a row is persisted with a server-generated timestamp that the caller cannot
  override.
- **Given** an audit write fails **When** the calling operation is a security-relevant mutation
  **Then** the behaviour is deterministic and documented — see §8 Q3 (recommended default:
  fail the request, because an unauditable mutation violates SECURITY_MODEL §9).

#### FR-051 — Every mutating endpoint writes an audit record — MUST
Coverage is enforced automatically, not by developer discipline.

- **Given** the running API **When** every non-idempotent endpoint (POST/PUT/PATCH/DELETE) in the
  Phase 1 surface is exercised once with a successful request
  **Then** each produces at least one audit record correlated to that request.
- **Given** an endpoint that mutates but writes no audit record
  **When** the audit-coverage test runs **Then** the test **fails**, naming the endpoint.
  (This is exit test ET-3.)
- **Given** a mutating request that is **denied** (401/403/429/CSRF) **When** it completes
  **Then** an audit record with outcome `failure` and the denial reason category exists.
- **Given** an audit record **When** it is read **Then** it carries a correlation id that matches
  the request's correlation id in the structured logs.

#### FR-052 — Append-only integrity — MUST
Audit records cannot be modified or deleted through the application.

- **Given** any Phase 1 API surface **When** it is enumerated **Then** no endpoint updates or
  deletes an audit record.
- **Given** the data layer **When** an update/delete against the audit model is attempted in a
  test **Then** it is rejected.

#### FR-053 — Audit read access — SHOULD
Audit records are readable through a permission-guarded, filterable API.

- **Given** a user with `audit:read` **When** they query audit records filtered by actor, action,
  target or time range **Then** matching records are returned in reverse-chronological order with
  pagination.
- **Given** a user without `audit:read` **When** they query **Then** 403.
- **Given** any audit query response **When** it is inspected **Then** it contains no secret value
  and no password hash (before/after payloads are redacted for sensitive fields).

### 3.F LLM provider abstraction

#### FR-060 — `LLMProvider` interface — MUST
`packages/llm` exposes one interface implemented by every adapter: `complete`, `stream`, `embed`
and capability flags (ARCHITECTURE §2.4).

- **Given** the three Phase 1 adapters **When** they are type-checked against the interface
  **Then** all three satisfy it, including declaring capability flags for streaming, embeddings
  and vision.
- **Given** an adapter that does not support a capability **When** that capability is invoked
  **Then** it throws a typed, documented "capability not supported" error rather than failing
  ambiguously.
- **Given** any adapter **When** it is called **Then** its inputs and outputs are validated by a
  Zod schema at the boundary (ARCHITECTURE §1 Validation row).

#### FR-061 — Anthropic adapter — MUST
An Anthropic adapter implementing `LLMProvider`, verifiable against a mocked transport.

- **Given** a mocked transport returning a canned Anthropic-shaped response
  **When** `complete` is called **Then** the adapter returns the normalised response shape and
  populates token counts from the mocked payload.
- **Given** a mocked transport returning a rate-limit or 5xx error **When** `complete` is called
  **Then** the adapter surfaces a typed error carrying provider, status and retryability, and
  does not throw a raw transport error.
- **Given** the adapter **When** its credential is needed **Then** it is retrieved via
  `SecretStore` and never read directly from a database column or logged.

#### FR-062 — OpenAI adapter — MUST
As FR-061, for OpenAI, including the `embed` capability against a mocked transport.

- **Given** a mocked embeddings response **When** `embed` is called **Then** a vector of the
  declared dimensionality is returned and the call is usage-logged.
- **Given** a mocked chat-completions error response **Then** a typed error is surfaced as in
  FR-061.

#### FR-063 — Ollama adapter — MUST
As FR-061, for a local Ollama endpoint (base URL configurable; no API key).

- **Given** an Ollama base URL configured and a mocked transport **When** `complete` is called
  **Then** the normalised response shape is returned.
- **Given** no Ollama service is reachable **When** `complete` is called
  **Then** a typed connectivity error is returned within the configured timeout, and neither the
  API nor the worker process crashes.

#### FR-064 — Usage logging — MUST
Every LLM call — successful or failed — writes a `usage_records` row.

- **Given** a successful mocked completion **When** it returns
  **Then** exactly one usage record is written carrying provider, model, feature label, agent
  reference (nullable in Phase 1), tokens in/out, estimated cost, latency in milliseconds and
  `error = null`.
- **Given** a failed or timed-out call **When** it returns **Then** a usage record is written
  with the error classification and the retry count.
- **Given** a usage record **When** it is read **Then** it contains no prompt or completion text
  that has not passed log redaction, and no credential (SECURITY_MODEL §2: LLM call logs are
  redacted before persistence).
- **Given** cost estimation **When** it is computed **Then** the per-model rates come from
  configuration/data, not hard-coded constants in call sites.

#### FR-065 — Mocked transports clearly marked — MUST
Because **no LLM provider API keys are available in this environment**, adapters are verified
against mocked transports only; architectural rule 7 requires this to be visible, not implicit.

- **Given** the Phase 1 deliverable **When** the phase report and `docs/LOCAL_SETUP.md` are read
  **Then** both state explicitly that Anthropic, OpenAI and Ollama adapters are
  **unverified against live provider endpoints** and list what live verification will require.
- **Given** the portal's provider settings page (if rendered in Phase 1)
  **When** it is viewed **Then** any provider without a configured credential is displayed as
  "not configured / unverified", never as connected or healthy.
- **Given** the code **When** a mock transport is used **Then** it is confined to test/dev
  fixtures and cannot be selected by a production configuration profile.

#### FR-066 — No routing in Phase 1 — MUST (as a constraint)
Phase 1 provides adapters and usage logging only. Feature routing rules, primary/fallback
selection, failover and budget caps are Phase 2.

- **Given** the Phase 1 codebase **When** it is reviewed **Then** there is no routing-rule table
  in use, no failover logic and no routing UI page; a caller selects a provider explicitly.
- **Given** a Phase 1 caller **When** it selects a provider **Then** the selection is passed in
  as configuration/parameter, never hard-coded in business logic (ARCHITECTURE rule 3 is
  respected in advance).

### 3.G Agent runtime skeleton

#### FR-070 — Config-driven agent — MUST
An agent is a configuration record, not code: identity, role, system instructions, tool allowlist
(empty in Phase 1), provider/model reference, max duration and budget fields.

- **Given** an agent configuration **When** the runtime instantiates it
  **Then** no agent-specific code path is required — a second agent with different configuration
  runs through the identical code.
- **Given** an agent configuration with an empty tool allowlist **When** it runs
  **Then** no tool is callable and no tool schema is presented to the model
  (SECURITY_MODEL §3: absent from the schema, not merely refused).
- **Given** an agent configuration that fails Zod validation **When** it is loaded
  **Then** loading fails with a validation error naming the invalid field, and no partially
  configured agent runs.

#### FR-071 — Structured message envelopes — MUST
The runtime emits Zod-validated envelopes of exactly the types listed in ARCHITECTURE §2.1:
`task_assigned`, `task_started`, `task_progress`, `information_required`, `approval_required`,
`task_blocked`, `task_completed`, `task_failed`, `agent_heartbeat`.

- **Given** each of the nine envelope types **When** one is constructed
  **Then** it validates against its schema and carries `taskId`, `agentId`, optional
  `parentTaskId`, `payload`, `tokensUsed`, `estimatedCost` and `timestamp`.
- **Given** a malformed envelope **When** it is submitted to the runtime
  **Then** it is rejected before persistence and the rejection is logged with the failing field.
- **Given** an envelope of type `approval_required` in Phase 1 **When** it is emitted
  **Then** it is persisted to the activity log and **no approval workflow executes** (Phase 2),
  and this limitation is stated in the phase report.

#### FR-072 — Activity persistence — MUST
Every emitted envelope is persisted to the agent activity log in Postgres — the durable record,
not an in-memory buffer.

- **Given** an agent run producing N envelopes **When** the process is killed and restarted
  **Then** all N envelopes emitted before the kill are still readable from the database.
- **Given** an agent activity query **When** it is filtered by agent and task
  **Then** envelopes are returned in emission order.

#### FR-073 — Heartbeats and stale-agent detection — MUST
A running agent emits `agent_heartbeat` at a configured interval; a silent agent is detectable.

- **Given** a running agent **When** the configured heartbeat interval elapses
  **Then** a heartbeat envelope is persisted with the agent's status and current task.
- **Given** an agent that stops emitting heartbeats for longer than the configured stale
  threshold **When** the staleness check runs
  **Then** the agent is marked failed/stale, the transition is persisted and audited, and its job
  is failed rather than left hanging (SECURITY_MODEL §3).
- **Given** the heartbeat interval and stale threshold **When** they are inspected
  **Then** both are configuration values, not constants in the runtime.

#### FR-074 — Budget and timeout enforcement points — SHOULD
The runtime enforces max duration and token/cost budget **in the loop**, not in the prompt
(ARCHITECTURE §2.2), even though Phase 1 has no real workload.

- **Given** an agent configured with a max duration of N seconds and a simulated long-running
  step **When** N is exceeded **Then** the run halts and emits `task_blocked` (or `task_failed`)
  with the reason, and the halt is persisted.
- **Given** an agent configured with a token budget and a mocked provider reporting usage above
  it **When** the budget is exceeded **Then** the loop halts and emits `task_blocked` with the
  budget reason — the model is never asked to self-limit.

### 3.H Queues, workers and scheduling

#### FR-080 — BullMQ + Redis wiring — MUST
Named queues exist and are connected to Redis with documented connection configuration.

- **Given** the Compose stack is up **When** the API and worker start
  **Then** both connect to Redis successfully, and a health endpoint reports Redis connectivity.
- **Given** Redis is unavailable at start **When** the worker starts **Then** it retries with
  backoff and logs a clear error rather than exiting silently or crash-looping without message.

#### FR-081 — Worker app consumes jobs — MUST
`apps/worker` processes jobs from the wired queues, with retry, backoff and failure capture.

- **Given** a job enqueued by the API **When** the worker is running
  **Then** the job is processed exactly once under normal operation and its result is persisted.
- **Given** a job whose handler throws **When** it is processed
  **Then** it is retried per the configured backoff policy and, after exhausting attempts, is
  recorded as failed with its error, and is visible/rerunnable rather than silently lost.
- **Given** a job handler exceeding its configured timeout **When** the timeout elapses
  **Then** the job is failed with a timeout classification.

#### FR-082 — Scheduler produces repeatable jobs — MUST
`apps/scheduler` is thin and stateless: it only **produces** repeatable job definitions; no
critical timing depends on an in-process timer (ARCHITECTURE §2.3 and rule 4).

- **Given** the scheduler starts **When** it registers its repeatable jobs
  **Then** the repeatable definitions exist in Redis and are visible via the queue API.
- **Given** the scheduler is stopped **When** a previously registered repeatable job's next
  execution time arrives and the worker is running
  **Then** the job still fires — proving the schedule lives in Redis, not in the scheduler
  process.
- **Given** the scheduler is restarted **When** it re-registers its jobs
  **Then** no duplicate repeatable job is created (registration is idempotent by job key).
- **Given** the Phase 1 codebase **When** it is reviewed **Then** no `setTimeout`/`setInterval`
  is the sole mechanism for any scheduled or recurring work.

#### FR-083 — Execution history persisted — MUST
Job executions are recorded in Postgres, not only in Redis.

- **Given** a job that completes **When** the execution finishes
  **Then** a Postgres execution-history row exists carrying job name, queue, attempt number,
  start/end timestamps, duration, outcome and error (nullable).
- **Given** Redis is flushed after a job has completed **When** the execution history is queried
  **Then** the completed execution is still readable from Postgres.

#### FR-084 — Durability across restart — MUST
Scheduled and queued work survives a full restart of the application containers.

- **Given** a repeatable job scheduled to fire during the outage window and durable Redis storage
  **When** all application containers (`api`, `worker`, `scheduler`) are stopped and started
  **Then** the repeatable definition still exists, execution resumes without manual
  re-registration, and no scheduled occurrence is silently lost. (This is exit test ET-4.)
- **Given** jobs waiting in a queue at shutdown **When** the worker restarts
  **Then** those jobs are processed.
- **Given** the Redis service **When** the Compose definition is inspected
  **Then** it uses a persistent named volume and a persistence configuration sufficient for the
  above (the specific persistence mode is an architecture decision — §8 Q7).

#### FR-085 — Queue observability — SHOULD
Queue depth, failed jobs and repeatable definitions are inspectable.

- **Given** the running stack **When** the operator queries the documented queue-status endpoint
  or command **Then** per-queue counts for waiting, active, completed, failed and delayed are
  returned, plus the list of repeatable job keys.

### 3.I Containers and developer experience

#### FR-090 — Docker Compose stack — MUST
A Compose file defines `postgres` (pgvector image), `redis`, `api`, `web`, `worker` and
`scheduler`, with an optional `ollama` profile.

- **Given** a clean Windows 11 host with Docker 29.6.1 running and `.env` created from
  `.env.example` **When** the operator runs the documented single bring-up command
  **Then** all six services reach a healthy state without manual intervention, and the portal is
  reachable at the documented local URL.
- **Given** the stack is up **When** the operator runs the documented tear-down command
  **Then** all services stop and the named data volumes persist.
- **Given** the stack is brought up a second time after tear-down **When** it becomes healthy
  **Then** previously stored data (owner account, audit records, job history) is still present.
- **Given** the Compose definition **When** it is reviewed **Then** no computer-control executor
  service is published, and no service other than `web`/`api` is exposed on the host beyond what
  local development requires (ARCHITECTURE §6, SECURITY_MODEL §7).

#### FR-091 — Health checks and health endpoints — MUST
Every stateful service has a Compose health check; `api` exposes a health endpoint reporting its
dependencies.

- **Given** the stack is up **When** `GET /api/system-health` (or the documented equivalent) is
  called **Then** it returns overall status plus per-dependency status for Postgres and Redis,
  and it exposes no secret, connection string or version detail that aids an attacker.
- **Given** Postgres is stopped **When** the health endpoint is called
  **Then** it reports the database as unhealthy with an appropriate status code and the API does
  not crash.

#### FR-092 — `.env.example` completeness — MUST
Covered by FR-004; additionally, it must document the master encryption key, database URL, Redis
URL, session/cookie configuration, rate-limit thresholds, provider base URLs and the LLM API key
variable names (names only, no values).

- **Given** `.env.example` **When** it is diffed against every `process.env` read in the codebase
  **Then** there are no undocumented variables and no documented-but-unused variables.

#### FR-093 — `docs/LOCAL_SETUP.md` — MUST
A setup document that a new developer can follow on Windows 11 end to end.

- **Given** a developer who has never seen the repository, a Windows 11 machine with Node,
  pnpm, git and Docker installed, and **no local `psql` client**
  **When** they follow `docs/LOCAL_SETUP.md` verbatim
  **Then** they reach a running stack and a successful owner login without needing to ask a
  question or read source code, and every database operation described is achievable through
  Compose/Prisma rather than a host-installed `psql`.
- **Given** the document **When** it is reviewed **Then** it includes: prerequisites with the
  verified versions, bring-up, migration, bootstrap, first login, MFA enrolment, running tests,
  tear-down, and a troubleshooting section covering Windows-specific issues (line endings, path
  length, bind-mount permissions, port conflicts).
- **Given** the document **When** it is reviewed **Then** it contains no real secret and states
  the Phase 1 limitations, including the unverified LLM adapters (FR-065).

### 3.J Portal shell

#### FR-100 — Design tokens extracted from the prototype — MUST
`packages/ui` exposes the SUNIL design language as tokens (CSS variables + typed exports), taken
from the prototype and named in ARCHITECTURE §3.

- **Given** `packages/ui` **When** the tokens are inspected
  **Then** they include at least `--sunil-cyan: #22d3ee`, `--sunil-bg: #030712`,
  `--sunil-panel: rgba(7,16,32,.72)`, `--sunil-amber: #fbbf24`, `--sunil-ok: #34d399`, and the
  Orbitron / Share Tech Mono type roles, plus panel, lamp and spacing tokens.
- **Given** any portal component **When** it is reviewed **Then** it references tokens, and no
  brand colour is hard-coded as a literal outside the token definitions.
- **Given** the prototype **When** it is compared to the token set **Then** the tokens are a
  faithful extraction, and any deliberate deviation is recorded by the UI/UX designer.

#### FR-101 — Navigation shell — MUST
An authenticated application shell with the navigation structure from ARCHITECTURE §3.

- **Given** an authenticated owner **When** the portal loads
  **Then** the shell renders with the navigation entries listed in ARCHITECTURE §3, where
  Phase 2–7 destinations are present but clearly marked unavailable/disabled rather than linking
  to broken pages.
- **Given** an unauthenticated visitor **When** they request any portal route other than login or
  invitation acceptance **Then** they are redirected to login and no protected content or data
  is present in the delivered payload.
- **Given** a user lacking a permission **When** the shell renders
  **Then** navigation entries they cannot use are hidden or disabled — and the corresponding API
  route still enforces the permission independently (UI hiding is never the control).
- **Given** the shell at 1920px, 1280px and 390px widths **When** it is rendered
  **Then** it remains usable with no horizontal page scroll and no overlapping content.

#### FR-102 — `<SunilPresence />` canvas component — MUST
The prototype's canvas sphere becomes a reusable React component with idle / thinking / speaking
states.

- **Given** `<SunilPresence state="idle" />` **When** it mounts **Then** the canvas renders the
  point sphere, HUD arcs and orbital ring, animating without console errors.
- **Given** the component **When** `state` changes to `thinking` and then `speaking`
  **Then** the visual state changes accordingly (at minimum the pulse behaviour distinguishes
  `speaking`), driven by the prop and not by internal timers tied to real events.
- **Given** the component **When** it unmounts **Then** its animation frame loop and resize
  listener are cleaned up and no animation continues (verifiable by test).
- **Given** a viewport resize **When** it occurs **Then** the canvas re-scales to device pixel
  ratio without visual distortion.
- **Given** a user with `prefers-reduced-motion: reduce` **When** the component renders
  **Then** animation is reduced or replaced with a static representation (see NFR-016).

#### FR-103 — Dark theme — MUST
The portal ships a dark theme as the default and only Phase 1 theme, built from the tokens.

- **Given** the portal **When** any Phase 1 page renders **Then** it uses the dark token palette
  consistently, with no unstyled or light-mode flash on first paint.

#### FR-104 — Login and session UI — MUST
Portal pages for login, MFA challenge, invitation acceptance and logout.

- **Given** the login page **When** valid credentials are submitted **Then** the user lands on the
  authenticated shell.
- **Given** an MFA-enrolled user **When** they submit valid credentials **Then** they are
  presented with the TOTP challenge before reaching the shell.
- **Given** an invitation link **When** it is opened **Then** the acceptance page allows setting a
  password and shows password-policy feedback; an invalid or expired link shows a generic failure
  without disclosing whether the invitation ever existed.
- **Given** any auth failure **When** it renders **Then** the message does not disclose whether an
  account exists.

#### FR-105 — No secrets reach the frontend — MUST
Directly supports critical scenario 12.

- **Given** the built portal bundle and every network response it receives during a full
  authenticated Phase 1 session **When** they are scanned for the known plaintext of a stored
  test secret and for any provider API key pattern **Then** there are zero matches.
- **Given** the portal **When** it needs a provider capability **Then** it calls the API; no
  provider credential is ever present in client-side code, environment or response.

---

## 4. Non-functional requirements

#### NFR-001 — Default deny — MUST
Every route, permission check and configuration flag defaults to the restrictive option; a new
route with no declared permission is unreachable, and production configuration profiles never
default to permissive values (SECURITY_MODEL §1, §8).
*Verification:* the guard-coverage test in FR-026 plus a configuration review of the production
profile.

#### NFR-002 — Encryption at rest for all credentials — MUST
No credential, token or password exists in plaintext in the database, in logs, in fixtures, in
Git history or in any API response.
*Verification:* schema review, repository secret scan, and the ET-5 response scan.

#### NFR-003 — Input validation at every boundary — MUST
All external input (HTTP body, query, params, headers used for logic, job payloads, agent
configuration, provider responses) is validated by Zod before use; validation failures return
structured errors with no internal detail leakage.
*Verification:* boundary inventory checked in code review; malformed-input tests for each
boundary class.

#### NFR-004 — Transport and header hardening — SHOULD
Secure cookies, CSP, `nosniff`, referrer policy and frame-ancestors restriction present on portal
responses; HTTPS assumed at the ingress for any non-local deployment.
*Verification:* automated header assertions in the API/portal test suite.

#### NFR-005 — Repository contains no secrets — MUST
No key, token, password or live connection string is committed at any point.
*Verification:* a secret-scanning step over the working tree and the Phase 1 commit range; the
security reviewer signs this off.

#### NFR-006 — API latency (local baseline) — SHOULD
On the reference local stack, authenticated Phase 1 API endpoints respond in under 300 ms at the
95th percentile for a single concurrent user, excluding LLM calls.
*Verification:* a repeatable local benchmark script; the number is a baseline for regression, not
a production SLO.

#### NFR-007 — Portal first-load performance — SHOULD
The authenticated shell reaches interactive in under 3 seconds on the reference local stack, and
`<SunilPresence />` sustains at least 30 fps on a mid-range laptop without pinning a CPU core.
*Verification:* browser performance measurement recorded in the phase report.

#### NFR-008 — Durability of background work — MUST
No scheduled or queued work depends on an in-memory timer or on a single process staying alive;
state lives in Redis and Postgres (ARCHITECTURE rule 4).
*Verification:* exit test ET-4 plus a code review confirming no sole-mechanism `setInterval`.

#### NFR-009 — Idempotent startup and bootstrap — MUST
Migrations, bootstrap and repeatable-job registration are all safely re-runnable.
*Verification:* run each twice on the same database/Redis and assert no duplicates and exit 0.

#### NFR-010 — Graceful degradation and clear failure — SHOULD
Loss of Redis or Postgres produces a clear unhealthy status and logged errors; no process
crash-loops without an actionable message; no silent data loss.
*Verification:* dependency-outage tests stopping each service in turn.

#### NFR-011 — Structured logging with redaction — MUST
All services emit structured logs with a request/job correlation id; the logger redacts secret
fields and patterns globally before output (SECURITY_MODEL §2).
*Verification:* log-scan test in FR-043; correlation id assertion in FR-051.

#### NFR-012 — Traceability from audit to logs — SHOULD
An audit record can be correlated to its request's logs via a shared correlation id, and
OpenTelemetry hook points exist even if no collector is configured in Phase 1.
*Verification:* trace one exercised mutation end to end in the QA evidence.

#### NFR-013 — Developer onboarding time — SHOULD
A developer new to the repository reaches a running stack and a successful owner login by
following `docs/LOCAL_SETUP.md` only, with no undocumented step.
*Verification:* a second engineer (not the author) performs a clean-machine dry run and records
every deviation; deviations are documentation defects.

#### NFR-014 — Type safety and quality gates — MUST
Strict TypeScript across the monorepo; lint, typecheck, test and build all run from the root and
must pass before Phase 1 is declared complete; no `any` introduced at module boundaries without a
recorded justification.
*Verification:* CI-equivalent local run with all four tasks green.

#### NFR-015 — Test coverage of the security surface — MUST
Automated tests exist for every requirement referenced by the five exit tests in §5; the exit
tests are executable, repeatable and not manual-only.
*Verification:* QA maps each exit test to named test cases in the phase report.

#### NFR-016 — Portal shell accessibility — SHOULD
The Phase 1 shell and auth pages meet WCAG 2.1 AA for the elements they contain: keyboard-only
navigation through login, MFA and the shell; visible focus indicators; text contrast ≥ 4.5:1
(and ≥ 3:1 for large text and meaningful UI boundaries) against the dark palette; form inputs
have programmatically associated labels and errors; `<SunilPresence />` is decorative
(`aria-hidden` with a text alternative for any status it conveys) and honours
`prefers-reduced-motion`.
*Verification:* automated accessibility scan of each Phase 1 page plus a manual keyboard pass;
contrast measured against the actual token values (the cyan-on-near-black palette must be checked
rather than assumed — dim cyan variants such as `rgba(34,211,238,.55)` on `#030712` are at risk
for body text).

#### NFR-017 — Windows 11 compatibility — MUST
Every documented command, script and container mount works on Windows 11 in the project's shell
without WSL-only assumptions; no path in tooling assumes POSIX-only separators; line endings do
not break scripts inside containers.
*Verification:* the entire Phase 1 acceptance run is performed on the Windows 11 host; any
Unix-only step is a defect.

#### NFR-018 — Modularity for later phases — SHOULD
`SecretStore`, `LLMProvider` and the agent runtime are consumed only through their interfaces, so
Phase 2–4 can add adapters and a router without editing callers.
*Verification:* substitute a test double for each interface and confirm consumers compile and pass
unchanged (FR-040 already asserts this for `SecretStore`).

#### NFR-019 — Honest completeness reporting — MUST
Anything mocked, stubbed or unverified is labelled as such in the code, the portal and the phase
report; nothing mocked is presented as complete (ARCHITECTURE rule 7).
*Verification:* the phase report contains an explicit "known limitations / mocked" section, and
the documentation agent cross-checks it against the code.

---

## 5. Phase 1 exit tests (release gate)

These are the five exit tests named in `IMPLEMENTATION_PLAN.md`, restated as executable
specifications. **All five must pass before Phase 1 is declared complete.** Each must be
automated and repeatable; manual-only evidence is not acceptable (NFR-015).

### ET-1 — Auth flows

**Covers:** FR-020, FR-021, FR-022, FR-023, FR-024, FR-027, FR-028, FR-029, FR-030, FR-104,
NFR-001, NFR-004.

| Step | Action | Pass condition |
|---|---|---|
| 1.1 | Attempt self-registration on every plausible registration path, authenticated and not | 404/405; user count unchanged |
| 1.2 | Log in as the bootstrapped owner with correct credentials | 200; session row created; session cookie carries `HttpOnly`, `SameSite=Lax`, explicit expiry, and `Secure` when the flag is enabled |
| 1.3 | Log in with a wrong password | Generic failure; no session; no account-existence disclosure; failure audited |
| 1.4 | Exceed the configured failed-attempt threshold, then submit the **correct** password | Lockout response; login refused; lockout audited |
| 1.5 | Enrol the owner in TOTP MFA, then log out and log in again | Password alone does not establish a session; a valid TOTP code does; an invalid or replayed code is refused |
| 1.6 | Use a recovery code, then reuse it | First use succeeds; reuse is refused |
| 1.7 | Invite a user as owner; accept the invitation; log in as that user | Invitation created and audited; user created with exactly the invited role; login succeeds |
| 1.8 | Replay the consumed invitation token; submit an expired token; submit a mutated token | All three refused; no user created |
| 1.9 | Send a state-changing request with a valid session cookie but no/incorrect CSRF token | 403; no state change |
| 1.10 | Log out, then reuse the old session cookie | 401 |
| 1.11 | Revoke a user's sessions from the owner account while that user has an active session | Next request from the revoked session returns 401 |

**Fail conditions (any one fails ET-1):** a user can be created without an invitation; a session
cookie lacks `HttpOnly` or `SameSite`; lockout can be bypassed; a consumed/expired invitation
works; a state-changing request succeeds without CSRF validation; an error message discloses
account existence.

### ET-2 — RBAC guards

**Covers:** FR-025, FR-026, FR-011, FR-101, NFR-001.

| Step | Action | Pass condition |
|---|---|---|
| 2.1 | Enumerate every registered API route and assert each declares a required permission (or is on the explicit public allowlist: login, invitation acceptance, health) | Zero routes without a declaration; the test names any offender |
| 2.2 | As a `viewer`, call each endpoint requiring a permission the viewer lacks | Every call returns 403; zero state changes |
| 2.3 | As `owner`, call the same endpoints | Each succeeds (or fails only for a reason unrelated to authorisation) |
| 2.4 | Unauthenticated, call every non-public route | Every call returns 401 |
| 2.5 | Grant the missing permission to the viewer's role in the database, then repeat 2.2 without a code change or redeploy | Calls now succeed — proving RBAC is data-driven |
| 2.6 | Hide a nav item in the UI for a viewer, then call the underlying API directly as that viewer | 403 — UI hiding is not the control |

**Fail conditions:** any route reachable without a declared permission; any 403 that leaks
resource existence detail; any permission change requiring a code change.

### ET-3 — Audit writes

**Covers:** FR-050, FR-051, FR-052, FR-053, FR-013, FR-043, NFR-011, NFR-012.
**Critical scenario link:** scenario 15 (partial — see §5.6).

| Step | Action | Pass condition |
|---|---|---|
| 3.1 | Enumerate every POST/PUT/PATCH/DELETE route in the Phase 1 surface and exercise each successfully | Each produces ≥1 audit record correlated to the request |
| 3.2 | Assert the coverage test fails when a deliberately unaudited mutating route is introduced (negative control) | The test fails and names the route |
| 3.3 | Trigger denied mutations (401, 403, CSRF, rate-limited) | Each produces an audit record with outcome `failure` and a denial category |
| 3.4 | Attempt to update and delete an audit record through the application | Both rejected |
| 3.5 | Read audit records as a user without `audit:read` | 403 |
| 3.6 | Read audit records as `owner` and scan every returned payload for secret plaintext and password hashes | Zero matches |
| 3.7 | Emit an agent-actor audit record and read it back | Actor type `agent` with the agent id populated |
| 3.8 | Correlate one audited mutation to its structured log lines by correlation id | The id matches in both |

**Fail conditions:** any mutating endpoint with no audit record; an audit record that can be
edited or deleted; a secret appearing in an audit payload; a missing correlation id.

### ET-4 — Queue survives restart

**Covers:** FR-080, FR-081, FR-082, FR-083, FR-084, FR-085, NFR-008, NFR-009, NFR-010.
**Critical scenario link:** scenario 14 (partial — see §5.6).

| Step | Action | Pass condition |
|---|---|---|
| 4.1 | Bring the stack up; register a repeatable job with a short interval; observe ≥2 executions | Execution-history rows exist in Postgres for each |
| 4.2 | Enqueue a delayed one-off job scheduled to become due **during** the outage window | Job accepted and visible as delayed |
| 4.3 | Stop `api`, `worker` and `scheduler` (a **real** container stop, not a mocked one); leave `postgres` and `redis` running | All three stop cleanly |
| 4.4 | Wait past the delayed job's due time and past at least one repeatable interval | — |
| 4.5 | Start `api`, `worker` and `scheduler` | Services become healthy |
| 4.6 | Observe the queues | The delayed job executes after restart; the repeatable definition still exists without manual re-registration; new executions are recorded |
| 4.7 | Verify no duplicate repeatable job key was created by the scheduler's re-registration | Exactly one definition per job key |
| 4.8 | Query execution history in Postgres for the whole window | The pre-restart executions are still present |
| 4.9 | Restart the **whole** stack including `postgres` and `redis` (volumes retained) | Owner account, audit records and execution history all survive |
| 4.10 | Grep the codebase for scheduled work relying solely on `setTimeout`/`setInterval` | Zero occurrences as a sole mechanism |

**Fail conditions:** any scheduled occurrence silently lost; a duplicate repeatable definition
after restart; execution history existing only in Redis; the test passing against a simulated
rather than a real process restart.

### ET-5 — Secret round-trip never exposes plaintext via an API

**Covers:** FR-040, FR-041, FR-042, FR-043, FR-044, FR-064, FR-065, FR-105, NFR-002, NFR-005,
NFR-011.
**Critical scenario link:** scenario 12 (substantially satisfied — see §5.6).

| Step | Action | Pass condition |
|---|---|---|
| 5.1 | Store a known sentinel secret value via the API/`SecretStore` | 201/200; no secret in the response |
| 5.2 | Inspect the stored row directly in the database | Ciphertext, unique IV, auth tag and key reference present; sentinel plaintext absent |
| 5.3 | Store the identical plaintext a second time and compare ciphertexts | Ciphertexts differ |
| 5.4 | Retrieve the secret through `SecretStore` inside the API and use it against a mocked provider transport | The provider call receives the correct plaintext — round-trip integrity holds |
| 5.5 | Call every Phase 1 API endpoint that could plausibly return the secret (detail, list, settings, export, OpenAPI document, and forced error responses) | Zero responses contain the sentinel; masked fingerprint only |
| 5.6 | Scan **all** captured HTTP response bodies and headers from the full test run for the sentinel | Zero matches |
| 5.7 | Scan the built portal bundle and all network traffic from an authenticated portal session for the sentinel and for provider key patterns | Zero matches |
| 5.8 | Scan the complete log output (all services) and all persisted `usage_records` for the sentinel | Zero matches; secret-named fields show the redaction marker |
| 5.9 | Corrupt one byte of a stored ciphertext or auth tag and read it | Authentication failure; no plaintext or partial plaintext returned; failure audited |
| 5.10 | Rotate the secret and repeat 5.4–5.6 | New value round-trips; old ciphertext unretrievable; rotation audited |
| 5.11 | Confirm every secret read/write/rotate in this test produced an audit record naming the operation but not the value | All present, none containing the value |

**Fail conditions:** the sentinel appears in **any** response body, header, log line, usage
record, bundle or error payload; identical plaintexts produce identical ciphertexts; tampered
ciphertext decrypts; a secret operation is unaudited.

### 5.6 Mapping to the 15 critical test scenarios

Phase 1 cannot fully satisfy any scenario that depends on Phase 2–7 features. The honest position:

| Scenario | Phase 1 status | Justification |
|---|---|---|
| **12 — API keys never exposed by the frontend** | **Substantially satisfied for the Phase 1 surface** | ET-5 (5.5–5.8) proves no secret leaves the API in any form and none reaches the portal bundle. It remains *partial* because Phase 3–4 will add integration credentials and OAuth tokens, and each new endpoint re-opens the question; the ET-5 response/bundle scan must therefore be a **standing regression test** run in every later phase, not a one-off. |
| **14 — Recurring workflows survive restarts** | **Foundation satisfied; scenario not yet satisfied** | ET-4 proves the *job infrastructure* survives a real restart, which is the durability half of the scenario. The scenario itself refers to **workflows** (Phase 2 workflow engine) and the 07:15 Hobart brief (Phase 3), neither of which exists. Phase 1 must claim durable jobs, not durable workflows. |
| **15 — All external actions create audit records** | **Foundation satisfied; scenario not yet satisfied** | ET-3 proves every mutating endpoint writes an audit record and that coverage is machine-enforced. Phase 1 performs **no external actions at all** (no email, Jira, Teams, computer control), so the scenario's actual subject does not exist yet. The value delivered is that the audit interceptor and the coverage test are in place before the first external action is ever written, and the coverage test must be extended to cover outbound adapters in Phase 3–4. |
| 1–11, 13 | Not addressed | Depend on Phase 2–6 features (brief, mail, Jira, Teams, routing, memory, approvals, computer control, prompt-injection defences). Phase 1 lays enabling foundations (durable jobs, audit, secrets, provider interface) but must not claim any of them. |

---

## 6. Assumptions

Stated explicitly; each is an inference, not something read verbatim in the source documents.
Any of these being wrong is a change of scope.

1. **A-01 — Phase 1 is local-only.** No staging or production deployment, no public hostname and
   no TLS termination are in Phase 1 scope; "secure cookies" are specified with a configurable
   flag for local HTTP development (FR-023). Inferred from SECURITY_MODEL §10 and the absence of
   deployment from the Phase 1 bullet list.
2. **A-02 — One owner account only.** The bootstrap creates exactly one owner; there is no
   supported path to a second owner in Phase 1.
3. **A-03 — No outbound email transport exists.** Invitations therefore cannot be emailed
   (drives §8 Q1). SECURITY_MODEL §10 forbids real emails in development regardless.
4. **A-04 — The Phase 1 Prisma schema covers identity, settings and audit groups only.** The
   other groups in ARCHITECTURE §4 (agents, integrations, work, comms, memory, governance) are
   **not** created in Phase 1, with three deliberate exceptions required by Phase 1's own bullets:
   `usage_records` (LLM usage logging), the agent activity/message-envelope tables (agent runtime
   skeleton) and job execution history. If the Solution Architect disagrees with adding these
   three, it becomes an architecture decision, not a requirements one.
5. **A-05 — pgvector is installed but unused.** No embedding is written or queried in Phase 1.
6. **A-06 — "Optional TOTP MFA" means the capability is mandatory, its use is optional.** The
   feature must be built and tested in Phase 1; whether the owner enrols is his choice.
7. **A-07 — The agent runtime skeleton executes no real LLM work.** It is exercised with mocked
   providers and simulated steps only; no agent performs a task of value in Phase 1.
8. **A-08 — Gemini is deferred.** ARCHITECTURE §2.4 and INTEGRATIONS list Gemini and generic
   OpenAI-compatible providers, but the Phase 1 bullet names only Anthropic, OpenAI and Ollama.
   The interface must accommodate them; the adapters are not built now.
9. **A-09 — The portal shell renders structure, not live business data.** Dashboard widgets are
   placeholders explicitly labelled as such; the prototype's hard-coded `SUNIL_DATA` is **not**
   carried across as if it were real (CURRENT_ARCHITECTURE reuse table; ARCHITECTURE rule 7).
10. **A-10 — Default timezone is `Australia/Hobart`.** The prototype's `Australia/Melbourne`
    clock is a known defect (CURRENT_ARCHITECTURE); any Phase 1 time display uses a configurable
    timezone defaulting to Hobart.
11. **A-11 — Testing is against mocked transports for all three LLM providers**, because no
    provider API keys exist in this environment. Live verification is a separate, later activity
    requiring keys (see §8 Q2).
12. **A-12 — "Every mutating endpoint" means every non-idempotent HTTP method** on the Phase 1
    API surface. Read-only endpoints do not write audit records in Phase 1 (secret *reads* are
    the exception, per SECURITY_MODEL §9).
13. **A-13 — English (en-AU) only.** No internationalisation in Phase 1.
14. **A-14 — Single-node infrastructure.** One Postgres, one Redis, one worker replica; no
    clustering, replication or HA in Phase 1.
15. **A-15 — The prototype files are read-only.** They are never edited, only referenced.

---

## 7. Risks and dependencies

| ID | Risk / dependency | Impact | Likelihood | Mitigation |
|---|---|---|---|---|
| **R-01** | **No LLM provider API keys are available.** Anthropic, OpenAI and Ollama adapters cannot be verified against live endpoints. | High — adapters may be subtly wrong (auth header shape, streaming framing, token-count field names, error taxonomy) and this will only surface in Phase 2 | Certain (already true) | Build every adapter against a mocked transport with fixtures captured from published provider response shapes; keep the transport injectable so a live smoke test is a configuration change, not a rewrite; label the adapters **unverified** in code, portal and phase report (FR-065, NFR-019); add a "live provider smoke test" item to the Phase 2 backlog; where a provider's contract is ambiguous, record it rather than guessing silently. Ollama is the cheapest route to a real end-to-end call if a local model is ever pulled — treat that as optional evidence, not a Phase 1 requirement. |
| **R-02** | **pgvector image availability / architecture mismatch.** The chosen pgvector-enabled Postgres 16 image may be unavailable, unpinned, or lack a matching tag; extension creation may fail. | High — the whole stack fails to come up | Medium | Pin an explicit image tag in Compose; verify `CREATE EXTENSION vector` in the initial migration and fail loudly if unavailable; add the pgvector check to ET-4 step 4.9 and the health endpoint; if the pinned image is unobtainable, the fallback (base Postgres 16 + extension build, or an alternative published image) is an **architecture decision** to be escalated to the Solution Architect, not chosen by the engineer mid-build. |
| **R-03** | **Windows/Docker path, volume and line-ending issues.** Bind mounts, `CRLF` in shell scripts run inside Linux containers, `node_modules` on a bind mount, long-path limits, and host port conflicts all commonly break Windows Docker development. | High — blocks the operator persona entirely; wastes disproportionate time | High | Prefer named volumes over bind mounts for dependency and data directories; enforce `LF` for shell scripts via `.gitattributes`; avoid host-path assumptions in Compose; run the **entire** Phase 1 acceptance on the Windows 11 host (NFR-017); document Windows-specific troubleshooting in `LOCAL_SETUP.md` (FR-093); no step may require a host `psql` client, since none is installed. |
| **R-04** | **BullMQ + Redis durability cannot be proven without a real restart.** A mocked or in-process "restart" would pass ET-4 while the real system loses jobs (e.g. Redis persistence not configured, repeatable keys regenerated, execution history only in Redis). | High — scenario 14 is a stated critical scenario; a false pass here is worse than a fail | Medium | ET-4 mandates stopping and starting **real containers** and includes a full-stack restart with volumes retained; Redis must use a persistent named volume with an explicit persistence configuration; execution history must be in Postgres (FR-083) so it survives a Redis flush; include the negative control (4.7 duplicate-key check) and the codebase grep (4.10). QA must record container ids/timestamps as evidence that the restart was real. |
| **R-05** | **Scope creep into Phase 2.** The foundation naturally invites "just add chat", "just add the routing table", "just add tasks" — and each addition dilutes the exit-test focus and inflates the surface the security reviewer must cover. | High — the phase never closes | High | §1.3 exclusion table is normative; any work item not traceable to a Phase 1 FR is rejected at code review; the audit-coverage and RBAC-coverage tests grow with every new endpoint, making unplanned surface immediately visible and costly; the DM holds the line at Gate 1 and at code review. |
| **R-06** | **Audit coverage decays as endpoints are added.** A convention-based approach ("remember to log") fails within one phase. | High — scenario 15's foundation is worthless if it is advisory | High | FR-051 requires machine-enforced coverage with a failing negative control (ET-3 step 3.2), so an unaudited mutating route breaks the build rather than passing review. |
| **R-07** | **Master encryption key handling in local development.** A developer-generated key committed by accident, or a key regenerated between runs, makes every stored secret undecryptable — or leaks it. | High | Medium | Key comes only from the environment; the process refuses to start without a valid-length key (FR-041); `.env` is git-ignored and `.env.example` carries a placeholder only; secret scanning over the Phase 1 commit range (NFR-005); `LOCAL_SETUP.md` documents key generation and the consequence of losing it. |
| **R-08** | **Under-specified permission vocabulary causes rework.** If permission strings are invented ad hoc per endpoint, Phase 2's much larger surface will need a painful renaming pass. | Medium | Medium | §8 Q4 escalates the vocabulary to the Solution Architect **before** endpoints are written; the BA will not choose it (role boundary). |
| **R-09** | **Session-auth implementation choice.** ARCHITECTURE says "session-based (Lucia-style)" — a style, not a named dependency. An engineer choosing a library unilaterally is an unrecorded architecture decision. | Medium | Medium | Escalated as §8 Q8 to the Solution Architect; requirements here are library-agnostic and expressed as behaviour (FR-022–FR-024), so any conforming implementation passes ET-1. |
| **R-10** | **Accessibility of the HUD palette.** The prototype's dim-cyan-on-near-black aesthetic is likely to fail WCAG AA contrast for body text and secondary labels. | Medium — a late accessibility failure forces visual rework | Medium-High | NFR-016 requires contrast measurement against actual token values during token extraction, not at the end; the UI/UX designer proposes accessible token variants that preserve the aesthetic (e.g. a compliant secondary-text token) and records any deliberate deviation from the prototype. |
| **R-11** | **Docker resource pressure on a single Windows host.** Six services plus optional Ollama on one developer machine may be slow or memory-constrained, distorting the NFR-006/NFR-007 baselines. | Low-Medium | Medium | Keep `ollama` behind an optional Compose profile (already specified); record the reference machine spec alongside any performance number so baselines are comparable. |
| **D-01** | **Dependency:** Solution Architect decisions on §8 Q4, Q5, Q7, Q8 (and Q3 if the recommended default is rejected) are needed before the backend engineer writes route guards, session handling and Compose persistence. | Blocking for BL-201/BL-202 | — | Gate 1 resolves these; the DM sequences architecture ahead of backend work in the backlog (§9). |
| **D-02** | **Dependency:** UI/UX design tokens (BL-501) must land before the portal shell (BL-502) to avoid hard-coded colours. | Blocking for BL-502/503 | — | Explicit ordering in §9; tokens are a small, early deliverable. |
| **D-03** | **Dependency:** Human answers to §8 Q1, Q2 and Q6 change Phase 1 behaviour (invitation delivery, live-verification expectation, lockout thresholds). | Blocking for BL-203 and the ET-1 thresholds | — | Consolidated into one questionnaire (§8) per the BA's hard rule; sensible defaults are proposed so the DM can run a confirm-or-correct rather than a blocking wait. |

---

## 8. Open questions for the human (ONE consolidated list)

Each question is genuinely blocking or materially changes Phase 1. Every one carries a
**recommended default** so this can be run as confirm-or-correct rather than an open-ended
interview. Silence on any item should be treated as acceptance of the stated default, and the
default will be recorded as a decision in the phase report.

> **Q1 — Invitation delivery.** No outbound mail transport exists in Phase 1 and SECURITY_MODEL
> §10 forbids real emails in development. How should an invitation reach the invitee?
> **Recommended default:** the portal displays a single-use invitation link for the owner to
> convey manually (copy to clipboard); no email is sent, and email-based invitation is added when
> a mail transport arrives in Phase 3.

> **Q2 — LLM adapter verification expectation.** No provider API keys are available in this
> environment, so Anthropic, OpenAI and Ollama adapters can only be verified against mocked
> transports. Is it accepted that Phase 1 ships these adapters explicitly labelled **"unverified
> against live endpoints"**?
> **Recommended default:** yes — ship mocked-verified adapters, label them clearly per
> architectural rule 7, and schedule a live smoke test in Phase 2 once keys exist.

> **Q3 — Behaviour when an audit write fails.** If the audit record cannot be persisted during a
> mutating request, should the request fail, or should it succeed with the audit failure recorded
> elsewhere?
> **Recommended default:** **fail the request** (audit-before-commit for security-relevant
> mutations). An unauditable mutation contradicts SECURITY_MODEL §9, and Phase 1's whole purpose
> is to make that guarantee real before any external action exists.

> **Q4 — Permission vocabulary ownership.** The permission-string scheme (e.g.
> `resource:action`), the seed role set and who may hold `owner` are design decisions the BA will
> not make (role boundary).
> **Recommended default:** the Solution Architect defines the vocabulary at Gate 1, seeded with
> the four roles proposed in §2.5 (`owner`, `admin`, `viewer`, `agent`), and confirms that
> exactly one `owner` may exist in Phase 1.

> **Q5 — Effect of a role change on live sessions.** When a user's role or permissions change,
> should existing sessions pick up the new permissions immediately, or should their sessions be
> revoked so they must sign in again?
> **Recommended default:** permissions are resolved per request (immediate effect), **and**
> privilege *reductions* additionally revoke that user's sessions. Whichever is chosen must be
> documented and tested under FR-024.

> **Q6 — Auth thresholds.** Confirm the brute-force and rate-limit values so ET-1 can assert
> against real numbers.
> **Recommended defaults:** 5 failed logins per account within 15 minutes triggers a 15-minute
> lockout; general API rate limit 100 requests/minute per session and 20/minute per IP on auth
> endpoints; session lifetime 8 hours idle / 24 hours absolute; invitation token valid 72 hours.
> All configurable via environment variables.

> **Q7 — Redis persistence mode and data-loss tolerance.** ET-4 requires that no scheduled
> occurrence is silently lost across a restart. The persistence configuration determines the
> worst-case loss window.
> **Recommended default:** enable AOF persistence with `everysec` fsync on a named volume,
> accepting at most ~1 second of loss; the Solution Architect confirms or overrides. (Flagged
> here as an architecture decision, not chosen by the BA.)

> **Q8 — Session-auth implementation.** ARCHITECTURE §1 specifies "session-based (Lucia-style)",
> which names a style rather than a dependency. Choosing the library or hand-rolling it is an
> architecture decision.
> **Recommended default:** the Solution Architect selects and records it at Gate 1; the
> requirements in FR-022–FR-024 are behavioural and library-agnostic, so any conforming choice
> passes ET-1 without changing this document.

> **Q9 — Scope confirmation on the three extra schema tables.** Phase 1's own bullets require
> `usage_records` (LLM usage logging), agent activity/envelope tables (agent runtime) and job
> execution history — which sit outside the named identity/settings/audit groups (assumption
> A-04).
> **Recommended default:** include these three in the Phase 1 initial migration, since the
> corresponding Phase 1 bullets cannot be satisfied without them; everything else in
> ARCHITECTURE §4 stays out.

> **Q10 — Portal shell breadth.** Should the Phase 1 navigation show the **full** Phase 2–7
> destination list (marked unavailable), or only the pages that actually function in Phase 1?
> **Recommended default:** show the full list with future destinations visibly disabled — it
> validates the layout at real density and sets expectations honestly — provided none of them
> links to a broken page and each is unmistakably marked as not yet available.

---

## 9. Phase 1 backlog

Items are assignable units of work with an owning specialist and explicit dependencies. IDs are
stable. **Nothing here promises a date or a duration** — sequencing and capacity are the Delivery
Manager's to set.

### 9.1 Dependency overview

```
Gate 1 (human answers §8)
   │
   ├── BL-101 Architecture decisions (solution_architect)  ── blocks BL-2xx
   │
   ├── BL-501 Design tokens (uiux_designer) ──────────────── blocks BL-502/503
   │
   └── BL-001 Monorepo scaffold (devops_engineer) ───────── blocks everything below
            │
            ├── BL-002 Compose stack ──┐
            ├── BL-201 Prisma schema ──┼── BL-202 Auth+RBAC ── BL-204 Audit ──┐
            │                          │        │                            │
            │                          │        └── BL-203 Invitations       │
            │                          │        └── BL-205 MFA               │
            │                          ├── BL-301 SecretStore ───────────────┤
            │                          ├── BL-401 Queue/worker/scheduler ────┤
            │                          └── BL-601 LLM package ── BL-602 adapters
            │                                   └── BL-701 Agent runtime
            └── BL-502 Portal shell ── BL-503 SunilPresence ── BL-504 Auth UI
                                                                            │
                                        BL-801..805 QA exit tests ──────────┤
                                        BL-901 Security review ─────────────┤
                                        BL-902/903 Documentation ───────────┘
```

### 9.2 Backlog items

| ID | Item | Owner | Covers | Depends on | Parallel-safe with |
|---|---|---|---|---|---|
| **BL-101** | Resolve architecture decisions from §8 (Q4 permission vocabulary, Q5 session/role semantics, Q7 Redis persistence, Q8 session-auth implementation, Q3 audit-failure policy if the default is rejected); record each as a short decision note | solution_architect | Q3–Q5, Q7, Q8; R-08, R-09 | Gate 1 answers | BL-001, BL-501 |
| **BL-102** | Confirm the Phase 1 schema boundary (Q9) and produce the module/package boundary map that engineers build against | solution_architect | A-04, FR-011–FR-013 | BL-101 | BL-001, BL-501 |
| **BL-001** | Monorepo scaffold: pnpm workspaces + Turborepo, all apps/packages, strict TS, lint/typecheck/test/build tasks from root, `.gitattributes` for LF | devops_engineer | FR-001, FR-002, FR-003, NFR-014, NFR-017 | — | BL-101, BL-501 |
| **BL-002** | Docker Compose stack: postgres/pgvector (pinned tag), redis (persistent volume), api, web, worker, scheduler, optional ollama profile; health checks; named volumes | devops_engineer | FR-090, FR-091, FR-010, R-02, R-03 | BL-001, BL-101 (Q7) | BL-201, BL-501 |
| **BL-003** | Environment configuration: startup validation, `.env.example` completeness check, secret-scan step | devops_engineer | FR-004, FR-092, NFR-005, R-07 | BL-001 | BL-002 |
| **BL-201** | Prisma schema (identity, settings, audit + the three Q9 tables), initial migration, idempotent bootstrap/seed | backend_engineer | FR-011–FR-015, NFR-009 | BL-001, BL-102 | BL-002, BL-501 |
| **BL-202** | Session auth + RBAC: login/logout, session records and revocation, secure cookies, CSRF, rate limiting and lockout, password hashing and policy, default-deny route guards + guard-coverage test | backend_engineer | FR-020, FR-022–FR-026, FR-028–FR-030, NFR-001, NFR-004 | BL-201, BL-101 | BL-301, BL-401 |
| **BL-203** | Invitation flow: create, single-use hashed token, expiry, accept, consume, all failure paths | backend_engineer | FR-021, FR-104 (API side) | BL-202, Q1 answer | BL-205 |
| **BL-204** | Audit log service + mutating-endpoint interceptor + append-only enforcement + coverage test with negative control + read API | backend_engineer | FR-050–FR-053, NFR-011, NFR-012, R-06 | BL-201, BL-202 | BL-301 |
| **BL-205** | TOTP MFA: enrol, verify, recovery codes, disable, login challenge | backend_engineer | FR-027 | BL-202, BL-301 | BL-203 |
| **BL-301** | `SecretStore` interface + AES-256-GCM envelope encryption + rotation + masked-fingerprint API + write-only semantics + access auditing | backend_engineer | FR-040–FR-044, FR-042, NFR-002 | BL-201 | BL-202, BL-401 |
| **BL-302** | Global log redaction (named fields + patterns) with structured logging and correlation ids | backend_engineer | FR-043, NFR-011 | BL-001 | BL-301 |
| **BL-401** | BullMQ + Redis wiring, named queues, worker app with retry/backoff/timeout/failure capture | backend_engineer | FR-080, FR-081, FR-085 | BL-002, BL-201 | BL-202, BL-301 |
| **BL-402** | Scheduler app: idempotent repeatable-job registration, no in-memory timers | backend_engineer | FR-082, NFR-008 | BL-401 | BL-601 |
| **BL-403** | Job execution history persisted to Postgres + queue status endpoint | backend_engineer | FR-083, FR-085 | BL-401, BL-201 | BL-402 |
| **BL-601** | `packages/llm`: `LLMProvider` interface, Zod boundary schemas, injectable transport, typed error taxonomy, usage-record writer | backend_engineer | FR-060, FR-064 | BL-201, BL-301 | BL-401, BL-701 |
| **BL-602** | Anthropic, OpenAI and Ollama adapters against mocked transports, with fixtures and the "unverified" labelling | backend_engineer | FR-061–FR-063, FR-065, R-01 | BL-601 | BL-701 |
| **BL-603** | Guard against premature routing: review that no routing rules, failover or budget caps exist | qa_engineer | FR-066, §1.3 | BL-602 | BL-801+ |
| **BL-701** | `packages/agents` skeleton: config-driven agent, Zod envelope schemas (all nine types), activity persistence | backend_engineer | FR-070–FR-072 | BL-601, BL-201 | BL-401 |
| **BL-702** | Heartbeats, stale-agent detection and in-loop budget/timeout enforcement | backend_engineer | FR-073, FR-074 | BL-701, BL-401 | BL-602 |
| **BL-501** | Design tokens extracted from `prototype/sunil-command-centre.html` into `packages/ui`, including accessible-contrast variants and a recorded deviation list | uiux_designer | FR-100, FR-103, NFR-016, R-10 | — | BL-001, BL-101 |
| **BL-502** | Portal navigation shell, dark theme, responsive breakpoints, permission-aware nav, disabled future destinations | frontend_engineer | FR-101, FR-103, FR-105, NFR-016 | BL-501, BL-001, Q10 answer | BL-503 |
| **BL-503** | `<SunilPresence />` React canvas component with idle/thinking/speaking states, cleanup on unmount, reduced-motion support | frontend_engineer | FR-102, NFR-007, NFR-016 | BL-501 | BL-502 |
| **BL-504** | Auth UI: login, MFA challenge, invitation acceptance, logout, auth-gated routing, no `innerHTML`, CSP compliance | frontend_engineer | FR-104, FR-031, FR-020 (UI side) | BL-502, BL-202, BL-203, BL-205 | BL-503 |
| **BL-505** | Placeholder dashboard clearly labelled as containing no live data | frontend_engineer | A-09, NFR-019 | BL-502 | BL-504 |
| **BL-801** | **ET-1** automated auth-flow test suite | qa_engineer | ET-1 | BL-202, BL-203, BL-205, BL-504 | BL-802–805 |
| **BL-802** | **ET-2** automated RBAC guard suite including route-declaration enumeration and the data-driven permission proof | qa_engineer | ET-2 | BL-202, BL-204 | BL-801, BL-803 |
| **BL-803** | **ET-3** automated audit-coverage suite including the negative control | qa_engineer | ET-3 | BL-204 | BL-801, BL-802 |
| **BL-804** | **ET-4** real-container restart durability test with evidence capture | qa_engineer | ET-4, R-04 | BL-402, BL-403, BL-002 | BL-801–803 |
| **BL-805** | **ET-5** secret round-trip and exposure-scan suite (responses, headers, logs, usage records, portal bundle) | qa_engineer | ET-5 | BL-301, BL-302, BL-602, BL-502 | BL-801–804 |
| **BL-806** | Cross-cutting NFR verification: performance baseline, dependency-outage behaviour, accessibility scan, Windows acceptance run | qa_engineer | NFR-006, NFR-007, NFR-010, NFR-016, NFR-017 | BL-002, BL-502 | BL-801–805 |
| **BL-901** | Security review of the Phase 1 surface: default-deny, cookie flags, CSRF, crypto usage and IV handling, redaction, repo secret scan, `.env.example`, CSP | security_reviewer | NFR-001–NFR-005, FR-041, FR-042 | BL-801–805 complete | — |
| **BL-902** | `docs/LOCAL_SETUP.md` including Windows troubleshooting and the stated Phase 1 limitations | documentation_agent | FR-093, NFR-013, NFR-019 | BL-002, BL-201, BL-504 | BL-903 |
| **BL-903** | Phase 1 report: work completed, files changed, migrations, tests + results, UI evidence, known limitations (incl. unverified LLM adapters), configuration required, security considerations, recommended next phase | documentation_agent | IMPLEMENTATION_PLAN "Per-phase reporting", NFR-019 | BL-901 | — |
| **BL-904** | Update `README.md` status from Phase 0 to Phase 1 and link this document | documentation_agent | README consistency | BL-903 | — |

### 9.3 Parallelisation notes for the Delivery Manager

- **Start immediately and in parallel:** BL-101 (architecture decisions), BL-501 (design tokens),
  BL-001 (monorepo scaffold). None depends on the others; all three are on the critical path.
- **Second wave, parallel:** BL-002/BL-003 (containers, config), BL-201 (schema). BL-502/BL-503
  (portal shell, presence component) can run entirely in parallel with all backend work because
  they depend only on tokens and the scaffold.
- **Serialised spine:** BL-201 → BL-202 → BL-204 is the tightest chain; BL-203 and BL-205 branch
  off BL-202 and can run concurrently with each other.
- **Independent backend streams once BL-201 lands:** the secrets stream (BL-301, BL-302), the
  queue stream (BL-401 → BL-402/BL-403), and the LLM/agents stream (BL-601 → BL-602/BL-701 →
  BL-702) are mutually independent and can be worked concurrently.
- **QA can author test suites against this specification before the code exists** — BL-801 to
  BL-805 are written from §5 and only *execute* against finished features. This is the single
  biggest parallelisation win available.
- **Gates:** BL-901 (security review) must follow all five exit tests, and BL-903 (phase report)
  must follow the security review. Neither may be shortened by running concurrently — no
  specialist reviews or signs off their own work.

---

## 10. Document control

| Aspect | Position |
|---|---|
| Authority | Subordinate to `SUNIL_ARCHITECTURE.md` and `SECURITY_MODEL.md`. Where this document appears to conflict with either, they win and this document is corrected. |
| Change control | Any change to §1.2, §1.3 or §5 is a scope change and requires a new human decision via the Delivery Manager. |
| Completion | Phase 1 is complete when ET-1 to ET-5 pass, BL-901 is signed off by the security reviewer, and BL-903 is published. |
| Commitments | This document contains no date, cost or delivery commitment, by design. |
