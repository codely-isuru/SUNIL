# SUNIL — Phased Implementation Plan

Each phase is completed, tested and documented before the next begins. No
feature is claimed complete unless implemented and tested. Mocked integrations
are clearly marked.

## Phase 0 — Repository assessment ✅ (this commit)

* Cloned repo assessed: green-field, prototypes preserved under `prototype/`.
* Architecture and planning documents produced (`docs/`).

## Phase 1 — Foundation

**Goal:** a running, secured, empty platform.

* Scaffold pnpm/Turborepo monorepo (`apps/web`, `apps/api`, `apps/worker`,
  `apps/scheduler`, `packages/*`).
* PostgreSQL + Prisma with the identity, settings and audit schema groups;
  initial migration.
* Session auth (register disabled — single-owner system with invited users),
  RBAC roles/permissions, optional TOTP MFA, secure cookies, CSRF, rate
  limiting.
* `SecretStore` abstraction with AES-256-GCM envelope encryption.
* Audit log service (every mutating endpoint writes an audit record).
* LLM provider abstraction (`packages/llm`) with Anthropic + OpenAI + Ollama
  adapters and usage logging (no routing UI yet).
* Agent runtime skeleton (`packages/agents`): config-driven agent, structured
  message envelopes, heartbeats.
* BullMQ + Redis wiring; scheduler app producing repeatable jobs; execution
  history persisted.
* Docker Compose (postgres/pgvector, redis, api, web, worker, scheduler),
  `.env.example`, `docs/LOCAL_SETUP.md`.
* Base portal layout: navigation shell, design tokens extracted from the
  prototype, `<SunilPresence />` canvas component, dark theme.

**Exit tests:** auth flows, RBAC guards, audit writes, queue survives restart,
secret round-trip never exposes plaintext via API.

## Phase 2 — Core SUNIL

**Goal:** talk to SUNIL; SUNIL delegates, tracks and asks permission.

* Central chat (streaming over WebSocket, history, markdown/code, attachments).
* Orchestrator v1: intent classification, task decomposition, agent selection,
  structured progress tracking, final summaries.
* Agent delegation visible in chat; agent activity feed.
* Tasks & reminders (projects, priorities, due dates, recurrence, subtasks,
  dependencies, sources, duplicate prevention by source external ID).
* Notification centre + approval centre (approve / reject / edit-and-approve /
  approve-once / trusted rule).
* Basic memory: preference + episodic writes with source attribution;
  pgvector retrieval into chat context; memory browser with edit/pin/delete.
* Model routing rules table + portal page; router with primary/fallback and
  budget caps; usage dashboard v1.

**Exit tests:** delegation round-trip, approval blocks side-effects, memory
delete removes retrieval, routing fallback on provider failure.

## Phase 3 — Personal Daily Brief

**Goal:** the 7:15 AM (Australia/Hobart) brief, end to end.

* Microsoft Graph OAuth for the personal Hotmail account; delta-sync mail
  reader (read-only scopes first).
* Email summarisation pipeline: unread/important, since-last-brief, action
  detection, deadline/payment/appointment extraction, newsletter separation,
  task/reminder suggestions, links back to originals.
* Weather adapter (configurable provider + location; default Hobart): current,
  forecast, rain probability, range, wind, warnings, practical recommendation.
* Calendar integration (Graph Calendar) + today's reminders + overdue tasks.
* "Remaining from yesterday": incomplete, auto-rescheduled, blocked, awaiting
  approval, waiting-on-others; portal actions to defer/reassign/cancel.
* Brief scheduling (editable schedule + timezone), dashboard rendering,
  notification delivery, optional email/browser-notification/voice adapters.

**Exit tests:** brief fires at 07:15 Hobart across DST changes; yesterday's
incomplete tasks included; no auto-replies possible with read-only scopes.

## Phase 4 — Business Integrations

**Goal:** work accounts wired in with per-account permissions.

* `isuru@codely.digital`: summarise, categorise, client/project association,
  draft replies, approval-gated external sending.
* `admin@codely.digital`: operational triage (hosting/billing/domains/
  security), task creation with auditable email→task links, urgency
  escalation, repetitive-notification suppression.
* `info@ezycleanco.com.au`: enquiry/booking/complaint detection; marketing &
  SEO filtering via configurable rules + classifier with a reviewable
  "blocked" category (never permanent deletion); approval-gated replies;
  escalation rules for complaints/legal/refunds/safety/high-value.
* Microsoft Teams (Graph): channels/chats/mentions sync, summaries, decision/
  blocker/deadline detection, task creation with back-links, exclusion lists.
* Jira (OAuth/API token): assigned/updated/overdue/blocked/stale queries,
  project summaries, approved create/update, loop-free sync via external IDs.
* Codely Support: `SupportProvider` interface + adapter for the actual
  provider once confirmed (email/Jira/custom/WordPress — currently unknown;
  the adapter boundary is designed so this does not touch core logic).

**Exit tests:** Ezy Clean marketing filter, duplicate-prevention across email/
Jira/Teams, draft-not-sent-without-permission, escalation paths.

## Phase 5 — Autonomous AI Teams

* Team registration (leader, members, roles, shared context, shared queue,
  team LLM defaults, permissions, budget, escalation, completion criteria).
* Development-team template (PM, Requirements, Architect, UI/UX, Frontend,
  Backend, QA, DevOps, Security, Docs).
* Orchestrated multi-agent execution with SUNIL as central authority; progress
  tracking; review gates; **no production deployment without approval**.

## Phase 6 — Computer Control

* Safe command executor (allow/denylists, directory jail, timeouts, resource
  limits, output + evidence capture).
* File operations, browser automation, application-control adapters.
* Permission levels 1–8, per-agent policies, sandboxing, high-risk approvals,
  rollback where possible, secret redaction, prompt-injection hardening.

## Phase 7 — Production readiness

* Security review + penetration checklist; performance passes; full test
  coverage of the critical scenarios; monitoring + failure notifications;
  `docs/DEPLOYMENT.md`, `docs/BACKUP_AND_RECOVERY.md`; user documentation.

## Critical test scenarios (tracked from the brief)

1. Daily brief runs at 7:15 AM Australia/Hobart.
2. Yesterday's incomplete tasks are included.
3. Marketing/SEO emails ignored for Ezy Clean Co (and reviewable, not deleted).
4. Customer enquiry → task + draft reply.
5. Drafts never sent without permission.
6. Jira issues never duplicated.
7. Teams messages link back to generated tasks.
8. Failed LLM providers fall back per routing config.
9. Agents report progress to SUNIL.
10. Dangerous computer actions request approval.
11. Prompt injection in an email cannot override permissions.
12. API keys never exposed by the frontend.
13. Deleted memory is gone from retrieval.
14. Recurring workflows survive restarts.
15. All external actions create audit records.

## Per-phase reporting

Each phase ends with: work completed, files changed, migrations, tests added +
results, UI evidence, known limitations, configuration required, security
considerations, and the recommended next phase.
