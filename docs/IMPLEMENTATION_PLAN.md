# SUNIL — Phased Implementation Plan

Each phase is completed, tested and documented before the next begins. No
feature is claimed complete unless implemented and tested. Mocked integrations
are clearly marked.

---

## ⚠ CURRENT SCOPE (revised 2026-07-22 by the owner)

**SUNIL's near-term scope is a personal assistant: daily workflows and voice
chat. Nothing else.**

| Phase | Status |
|---|---|
| 0 — Repository assessment | ✅ Complete |
| 1 — Foundation | ✅ Built, awaiting independent review sign-off |
| **2 — Core SUNIL** | **IN SCOPE** — prerequisite for both goals |
| **3 — Daily workflows + voice chat** | **IN SCOPE — the deliverable** |
| 4 — Business integrations | ⏸ Deferred |
| 5 — Autonomous AI teams | ⏸ **PAUSED — explicit owner decision** |
| 6 — Computer control | ⏸ Deferred |
| 7 — Production readiness | Applies to the narrowed scope |

Rationale and consequences: `docs/SCOPE_CHANGE_2026-07-22.md`.

A deferred phase is **paused, not cancelled**. Its design work stands, its
interfaces remain the seams the code is built against, and nothing in the
delivered foundation is wasted or has to be undone.

---

## Phase 0 — Repository assessment ✅

* Cloned repo assessed: green-field, prototypes preserved under `prototype/`.
* Architecture and planning documents produced (`docs/`).

## Phase 1 — Foundation ✅ built (commit `f301a59`, branch `feature/phase-1-foundation`)

**Goal:** a running, secured, empty platform.

* pnpm/Turborepo monorepo (`apps/web`, `apps/api`, `apps/worker`,
  `apps/scheduler`, `packages/*`).
* PostgreSQL + Prisma with the identity, settings and audit schema groups
  (plus `usage_records`, agent activity and job history); initial migration.
* Session auth (registration disabled — single-owner, invite-only), RBAC,
  optional TOTP MFA, secure cookies, CSRF, rate limiting.
* `SecretStore` abstraction with AES-256-GCM envelope encryption.
* Audit log service — audit-before-commit; a failed audit write fails the request.
* LLM provider abstraction with Anthropic + OpenAI + Ollama adapters and usage
  logging. **Mock-verified only; structurally labelled unverified against live
  endpoints** (no API keys in the build environment).
* Agent runtime skeleton: config-driven agent, structured message envelopes,
  heartbeats, in-loop budget/timeout enforcement.
* BullMQ + Redis; scheduler producing repeatable jobs; execution history persisted.
* Docker Compose (postgres/pgvector, redis, api, web, worker, scheduler),
  `.env.example`, `docs/LOCAL_SETUP.md`.
* Base portal: navigation shell, design tokens, `<SunilPresence />`, dark theme.

**Exit tests:** auth flows, RBAC guards, audit writes, queue survives restart,
secret round-trip never exposes plaintext — all five proven with negative controls.

**Not yet done:** independent Security and QA review (Stage 6), app Dockerfiles,
the two `.woff2` font files, and any run against a live API.

## Phase 2 — Core SUNIL — IN SCOPE

**Goal:** talk to SUNIL; SUNIL tracks work and asks permission.

* Central chat (streaming over WebSocket, history, markdown/code, attachments).
* Orchestrator v1: intent classification, agent selection, structured progress
  tracking, final summaries. **Single-agent delegation only** — multi-agent
  decomposition belongs to the paused Phase 5 and is explicitly out of scope.
* Agent activity feed.
* Tasks & reminders (projects, priorities, due dates, recurrence, subtasks,
  dependencies, sources, duplicate prevention by source external ID).
* Notification centre + approval centre (approve / reject / edit-and-approve /
  approve-once / trusted rule).
* Basic memory: preference + episodic writes with source attribution; pgvector
  retrieval into chat context; memory browser with edit/pin/delete.
* Model routing rules table + portal page; router with primary/fallback and
  budget caps; usage dashboard v1.

**Exit tests:** delegation round-trip, approval blocks side-effects, memory
delete removes retrieval, routing fallback on provider failure.

## Phase 3 — Daily workflows + voice chat — IN SCOPE, the deliverable

**Goal:** the daily brief runs itself, and SUNIL can be spoken to and answer aloud.

### 3a — Daily workflows

* Microsoft Graph OAuth for the personal account; delta-sync mail reader
  (read-only scopes first).
* Email summarisation: unread/important, since-last-brief, action detection,
  deadline/payment/appointment extraction, newsletter separation, task and
  reminder suggestions, links back to originals.
* Weather adapter (configurable provider and location; default Hobart): current,
  forecast, rain probability, range, wind, warnings, practical recommendation.
* Calendar (Graph Calendar) + today's reminders + overdue tasks.
* "Remaining from yesterday": incomplete, auto-rescheduled, blocked, awaiting
  approval, waiting-on-others; portal actions to defer/reassign/cancel.
* Brief scheduling (editable schedule + timezone, default **Australia/Hobart**),
  dashboard rendering, notification delivery.
* Recurring routines beyond the brief, on the durable scheduler built in Phase 1.

### 3b — Voice chat — promoted to a first-class deliverable

Previously an "optional voice adapter". It is now half the phase, and it needs
design work that does not yet exist (see `SCOPE_CHANGE_2026-07-22.md` §3):

* **Speech in (STT)** and **speech out (TTS)** behind a `VoiceProvider`
  interface — no such interface exists yet in `INTEGRATIONS.md`.
* A provider decision, with the privacy trade-off stated explicitly: on-device
  or self-hosted versus a cloud API that receives the owner's spoken audio.
  `SECURITY_MODEL.md` currently says nothing about voice data.
* Voice conversation in chat: barge-in, turn-taking, transcript persistence, and
  what is retained versus discarded.
* Drive the **existing** `<SunilPresence />` `speaking` amplitude prop — it was
  specified and built in Phase 1 for exactly this and is currently inert.
* "Brief Me": the daily brief delivered aloud. The prototype's
  `speechSynthesis` en-GB fallback is the reference pattern.
* Accessibility: voice is an addition to the keyboard and screen-reader paths,
  never a replacement.

**Exit tests:** brief fires at its scheduled Hobart time across DST changes;
yesterday's incomplete tasks are included; no auto-replies possible with
read-only scopes; a spoken request produces a correct spoken answer; voice
audio handling matches whatever privacy decision is recorded.

## Phase 4 — Business integrations — ⏸ DEFERRED

Codely and Ezy Clean mailboxes, Teams, Jira, Codely Support. Design in
`INTEGRATIONS.md` stands; the `MailProvider` / `ChatProvider` / `IssueProvider` /
`SupportProvider` interfaces remain the seams. Nothing built for the personal
daily brief has to be undone to add these later — the personal mailbox uses the
same `MailProvider` interface.

## Phase 5 — Autonomous AI teams — ⏸ PAUSED (owner decision, 2026-07-22)

Team registration, the development-team template, orchestrated multi-agent
execution and review gates. **Paused, not cancelled.**

Confirmed: **no team tables were built in Phase 1** — the delivered schema has
no `teams` or `team_members` model — so this pause orphans nothing and leaves no
dead schema behind. The single-agent runtime in `packages/agents` is what the
daily workflows use and is unaffected.

## Phase 6 — Computer control — ⏸ DEFERRED

Safe command executor, file operations, browser automation, permission tiers 1–8.
The security model in `SECURITY_MODEL.md` §7 stands for when it resumes.

## Phase 7 — Production readiness

Security review and penetration checklist; performance passes; full coverage of
the in-scope critical scenarios; monitoring and failure notifications;
`docs/DEPLOYMENT.md`, `docs/BACKUP_AND_RECOVERY.md`; user documentation.

---

## Critical test scenarios

Scope-tagged after the 2026-07-22 revision. A deferred scenario is not dropped —
it returns with its phase.

| # | Scenario | Scope |
|---|---|---|
| 1 | Daily brief runs at its scheduled time, Australia/Hobart | **In — Phase 3** |
| 2 | Yesterday's incomplete tasks are included | **In — Phase 3** |
| 8 | Failed LLM providers fall back per routing config | **In — Phase 2** |
| 9 | Agents report progress to SUNIL | **In — Phase 2** |
| 11 | Prompt injection in content cannot override permissions | **In — Phase 2/3** |
| 12 | API keys never exposed by the frontend | **In — proven in Phase 1 (ET-5)** |
| 13 | Deleted memory is gone from retrieval | **In — Phase 2** |
| 14 | Recurring workflows survive restarts | **In — proven in Phase 1 (ET-4)** |
| 15 | All external actions create audit records | **In — proven in Phase 1 (ET-3)** |
| — | A spoken request produces a correct spoken answer | **In — Phase 3b (new)** |
| — | Voice audio handling matches the recorded privacy decision | **In — Phase 3b (new)** |
| 3 | Marketing/SEO email ignored for Ezy Clean (reviewable, not deleted) | ⏸ Phase 4 |
| 4 | Customer enquiry → task + draft reply | ⏸ Phase 4 |
| 5 | Drafts never sent without permission | ⏸ Phase 4 |
| 6 | Jira issues never duplicated | ⏸ Phase 4 |
| 7 | Teams messages link back to generated tasks | ⏸ Phase 4 |
| 10 | Dangerous computer actions request approval | ⏸ Phase 6 |

Scenarios 3–7 and 10 are **deferred, not weakened**. The rules behind them —
approval before any external action, no permanent deletion, idempotent imports —
remain binding on everything built in the meantime.

## Per-phase reporting

Each phase ends with: work completed, files changed, migrations, tests added and
results, UI evidence, known limitations, configuration required, security
considerations, and the recommended next phase.
