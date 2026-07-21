# SUNIL — Target Architecture

SUNIL (Systems Utility & Neural Intelligence Liaison) is a secure, modular,
autonomous personal and business AI assistant platform for Isuru. This document
defines the recommended architecture. The repository is green-field (see
`CURRENT_ARCHITECTURE.md`), so the stack below is a decision, not an
inheritance.

## 1. Stack decision

A single-language TypeScript monorepo, chosen for strict typing across the
whole system, first-class SDKs for every target integration (Microsoft Graph,
Jira, Anthropic, OpenAI, Gemini, Ollama), and a mature queue ecosystem.

| Concern | Choice | Rationale |
|---|---|---|
| Monorepo | pnpm workspaces + Turborepo | Shared types between web/api/workers |
| Frontend | Next.js (App Router) + React + Tailwind CSS | Fast, responsive portal; SSR for dashboard; design tokens via CSS variables |
| Backend API | NestJS (Fastify adapter) | Modular services, guards for RBAC, OpenAPI generation built in |
| Database | PostgreSQL 16 + Prisma | Relational core; migrations; `pgvector` extension for semantic memory |
| Queue / jobs | BullMQ + Redis | Persistent scheduled/recurring/retryable jobs; survives restarts |
| Realtime | WebSocket gateway (Socket.IO) | Chat streaming, agent activity feed, notifications |
| Auth | Session-based (Lucia-style) + optional TOTP MFA | Short-lived sessions, secure cookies, CSRF protection |
| Secrets | Envelope encryption (AES-256-GCM) behind a `SecretStore` interface | Swappable later for AWS/Azure/Vault |
| Validation | Zod at every API and integration boundary | Runtime validation to match TS types |
| Observability | Pino structured logs + OpenTelemetry hooks + health endpoints | Redaction built into the logger |

### Monorepo layout

```
apps/
  web/            Next.js portal
  api/            NestJS HTTP + WebSocket API
  worker/         BullMQ workers (agents, integrations, workflows)
  scheduler/      Cron/schedule producer (thin, stateless)
packages/
  core/           Domain types, message contracts, shared Zod schemas
  db/             Prisma schema, migrations, repositories
  llm/            Provider adapters + model router
  agents/         Agent runtime + built-in agent definitions
  integrations/   Graph, Jira, Teams, weather, IMAP/SMTP, support adapters
  memory/         Memory service (relational + pgvector retrieval)
  ui/             Shared React components + design tokens
prototype/        Original HTML prototypes (design reference, read-only)
docs/             This documentation set
```

## 2. Logical services

### 2.1 SUNIL Orchestrator (`packages/agents` + `apps/worker`)

The central authority. Responsibilities: receive user requests (chat, schedule,
event); classify intent; decompose into subtasks; select agent + model via the
router; enqueue agent jobs; track progress; enforce approval gates; write
memory; notify; summarise.

Agents never talk to the outside world directly on their own authority — every
tool call flows through the orchestrator's permission check and audit log.

**Structured agent messages** (Zod-validated, persisted to the event log):

```
task_assigned | task_started | task_progress | information_required |
approval_required | task_blocked | task_completed | task_failed |
agent_heartbeat
```

Each envelope carries: `taskId`, `agentId`, `parentTaskId?`, `payload`,
`tokensUsed`, `estimatedCost`, `timestamp`. The orchestrator maintains per-agent
state (status, current task, progress, tool calls, errors, findings, usage,
timestamps) in the `agent_activity` tables — the durable activity log.

### 2.2 Agent Runtime

A reusable framework where an agent is **configuration, not code**: identity,
role, system instructions, tool allowlist, LLM provider/model (or routing
feature), memory access level, integration permissions, max duration, token/cost
budget, approval policy, retry policy, schedule, parent/child links.

Built-in agent templates: Personal Assistant, Email Triage, Email Reply, Task
Planning, Reminder, Weather, Codely Operations, Support, Jira, Teams,
Development Manager, Requirements Analyst, UI/UX, Frontend Dev, Backend Dev,
DevOps, QA, Security Review, Research, Reporting. All are rows in the `agents`
table, editable in the portal, and executed by the same runtime.

Agent execution is a BullMQ job: the worker loads config, builds the system
prompt, runs the LLM tool-loop, emits structured messages, and enforces budget/
timeout/permission limits in the loop itself (not in the prompt).

### 2.3 Job & Workflow Engine

BullMQ queues per concern (`agents`, `integrations:sync`, `workflows`,
`notifications`, `briefs`). Features: cron-scheduled repeatable jobs, one-time
delayed jobs, event-triggered workflows, exponential-backoff retries, timeouts,
failed-job tracking with manual rerun, pause/resume, dependency chains
(FlowProducer), approval steps (workflow parks in `waiting_approval` and resumes
on decision), cancellation, and full execution history persisted to Postgres.
No critical job may rely on in-memory timers; the scheduler app only *produces*
repeatable jobs — state lives in Redis + Postgres and survives restarts.

Workflows are stored as a typed JSON graph (triggers → conditions → actions →
delays → branches → approvals → notifications) and interpreted by the workflow
worker — the same model the portal's workflow builder edits.

### 2.4 Model Router (`packages/llm`)

Provider adapters implement one interface (`complete`, `stream`, `embed`,
capability flags) for Anthropic, OpenAI, Gemini, Ollama and any
OpenAI-compatible endpoint. The router selects primary/fallback models from
**feature routing rules** stored in the database (feature → provider/model,
max cost, max latency, required capabilities, failover order) — no hard-coded
conditions. Every call logs provider, model, agent, feature, tokens in/out,
estimated cost, latency, errors and retries to `usage_records`.

### 2.5 Memory (`packages/memory`)

Two stores behind one service: relational rows for structured records
(preferences, clients, projects, decisions, relationships) and `pgvector`
embeddings for semantic retrieval. Memory types: short-term conversation,
working task, long-term semantic, episodic, preference, business/project
knowledge, agent-specific, team-shared.

Every memory carries source attribution, confidence, created/updated/review
dates, sensitivity classification and per-agent access level. Writes go through
a gate: explicit corrections, repeated decisions and approved outcomes are
learnt; raw generated answers are not silently promoted to fact. Deletion
removes the row *and* its embedding so it can never be retrieved again.

### 2.6 Integration Layer (`packages/integrations`)

Adapter-per-provider behind common interfaces (`MailProvider`,
`ChatProvider`, `IssueProvider`, `SupportProvider`, `WeatherProvider`,
`CalendarProvider`). OAuth tokens live in the encrypted secret store; sync
state (delta tokens, cursors, last success/failure) lives in
`integration_accounts`. All imports are idempotent via external IDs. Details in
`INTEGRATIONS.md`.

### 2.7 Computer Control

A separate, never-publicly-exposed executor service with tiered permission
levels (read-only → create → edit → safe commands → browser → app control →
system config → destructive), command allow/denylists, working-directory
jails, timeouts, resource limits, output capture, evidence capture and audit
logging. High-risk actions always park on an approval. Full model in
`SECURITY_MODEL.md`.

## 3. Portal (apps/web)

Navigation: Dashboard, SUNIL Chat, Daily Brief, Tasks, Calendar, Emails,
Support, Jira, Teams, Agents, AI Teams, Workflows, Memory, Approvals,
Notifications, Integrations, LLM Providers, Model Routing, Usage, Activity
Logs, Settings, System Health.

The prototype's HUD aesthetic is retained as the **SUNIL design language**,
extracted into design tokens in `packages/ui`:

```
--sunil-cyan: #22d3ee   --sunil-bg: #030712   --sunil-panel: rgba(7,16,32,.72)
--sunil-amber: #fbbf24  --sunil-ok: #34d399   fonts: Orbitron / Share Tech Mono
```

The canvas sphere becomes `<SunilPresence />` (idle / thinking / speaking
states). The dashboard page recreates the prototype layout with live data:
SUNIL status, daily brief, weather, schedule, priority/overdue tasks, active
agents, running workflows, emails needing attention, support, Jira, Teams
highlights, approvals, recent memories, system health, integration status,
recent errors. Chat supports streaming, history, attachments, tool indicators,
visible agent delegation, task creation, memory references, approvals, voice
in/out, markdown/code rendering and deep links.

## 4. Data model (summary)

Prisma schema groups (full list mirrors the project brief §12):

* **Identity**: users, roles, permissions, sessions
* **LLM**: providers, models, feature routing rules, usage/cost records
* **Agents**: agents, teams, team members, tool permissions, activity, tool executions
* **Integrations**: integrations, integration accounts, credential references, sync logs
* **Work**: workflows, workflow executions, scheduled jobs, tasks, subtasks, reminders, projects, clients, daily briefs
* **Comms**: communications, email messages, support tickets, jira links, teams message links, conversations, conversation messages
* **Memory**: memories, memory sources (+ pgvector embeddings)
* **Governance**: approvals, notifications, audit logs, system settings

Conventions: UUID PKs, `externalId` + unique indexes for idempotent imports,
idempotency keys on outbound actions, soft-delete only where audit requires it,
migrations for every change.

## 5. API surface

REST under `/api/*` (NestJS, OpenAPI-generated), WebSocket for chat/activity:
`/api/auth, /api/chat, /api/agents, /api/teams, /api/tasks, /api/reminders,
/api/projects, /api/workflows, /api/integrations, /api/providers, /api/models,
/api/model-routing, /api/memory, /api/approvals, /api/notifications,
/api/daily-briefs, /api/activity, /api/audit, /api/system-health,
/api/computer-actions`.

Every route: Zod-validated input, authenticated session, RBAC guard, rate
limiting, idempotency keys on mutating endpoints, structured errors, audit
logging on side-effects.

## 6. Deployment shape

Docker Compose services: `postgres` (pgvector image), `redis`, `api`, `web`,
`worker`, `scheduler`, optional `ollama` profile. Health checks and persistent
volumes on all stateful services; dev and prod compose variants;
`.env.example` documents every variable. The computer-control executor runs
only on trusted hosts and is never published in the compose ingress.

## 7. Key architectural rules

1. Agents act only through the orchestrator's permission and audit layer.
2. External content (email, web, tickets, messages) is data, never
   instructions — see prompt-injection defences in `SECURITY_MODEL.md`.
3. Model selection is configuration (routing rules), never hard-coded.
4. All background work is durable (Redis + Postgres), never in-memory timers.
5. Secrets are encrypted at rest, redacted in logs, never returned by APIs.
6. Every import and outbound action is idempotent and audited.
7. Mocked integrations must be clearly marked and never presented as complete.
