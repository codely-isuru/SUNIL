# SUNIL — STATUS

**Read this first.** It is the single source of truth for where the project stands.

| | |
|---|---|
| **Project** | S.U.N.I.L. — Personal + Business Agentic OS |
| **Current phase** | V1 — SUNIL Core (cloud-first) |
| **Plan of record** | [`docs/ROADMAP.md`](ROADMAP.md) — supersedes every earlier plan document |
| **Branch** | `main` (single-branch rule; feature work lands via short-lived branches → `main`) |
| **Delivery** | Minions Team 18 (portal `http://localhost:4317`) |
| **Due** | 2026-08-18 (Milestone 1 vertical slice) · budget ~$150 |
| **Last updated** | 2026-08-14 |

---

## 1. What happened

### 2026-08-13 — Reset onto the new roadmap

The project was re-planned. `SUNIL_AGENTIC_OS_ROADMAP.md` (V1 → V3) replaces every
prior plan document, and the previous TypeScript/NestJS build is retired.

* **Superseded and deleted from `main`:** `CURRENT_ARCHITECTURE.md`,
  `IMPLEMENTATION_PLAN.md`, `INTEGRATIONS.md`, `SECURITY_MODEL.md`,
  `SUNIL_ARCHITECTURE.md`.
* **Archived, not lost:** the whole TypeScript monorepo (Phase 0 + Phase 1
  foundation, 422 tests) is preserved at tag **`archive/v0-typescript-foundation`**
  and on branch `feature/phase-1-foundation`. Recover any of it with
  `git show archive/v0-typescript-foundation:<path>`.
* **Why:** the new roadmap specifies a Python/FastAPI backend with a Model Router,
  Central Orchestrator, agent framework and permission engine. That is a different
  system from the NestJS platform-services build, and the owner chose a fresh start
  over retrofitting.
* **Kept:** `prototype/` (UI reference mockups), `README.md`.

---

## 2. Where we are now

**Stage 5 — Development. RUNNING since 2026-08-14.**

**✅ GATE 2 CLOSED — 2026-08-14.** The owner reviewed the architecture (9/10) and build plan
(7.5/10) and approved the direction subject to targeted corrections, all of which are applied
(`f6f7c28`…`42062a8`). His review is committed at
[`docs/reviews/2026-08-14-owner-architecture-review.md`](reviews/2026-08-14-owner-architecture-review.md).

**M1 is now due 2026-08-18** — the owner granted one extra day rather than descope, after the
recalculated critical path showed the MUST-HAVE set missing 08-17 in the expected case.

**Lanes in flight** — each in its own worktree on its own task branch, per
[`docs/GIT_WORKFLOW.md`](GIT_WORKFLOW.md). Nobody commits to `main`.

| Lane | Worktree | Task | Status |
|---|---|---|---|
| BE-1 | `..\SUNIL-wte-core` | **T1** foundation + trace interface | running |
| QA | `..\SUNIL-wt\qa` | **T18** red exit-test harness (ET-1…ET-12) | running |
| FE | `..\SUNIL-wtrontend` | **T14** web scaffold + token contract | running |

* **Secrets:** the owner creates them per [`docs/SECRETS_SETUP.md`](SECRETS_SETUP.md).
  Needed by 2026-08-16; everything until then builds against fixtures.
* **T11 is paired** across both backend engineers — it gates seven of the twelve exit
  tests and had no slack as scoped.
* **ET-12 added** (prompt injection via GitHub content) as a mandatory M1 control, from
  the owner's review §16 step 13.

**✅ GATE 1 APPROVED — 2026-08-14, by the owner.** Scope, requirements and all seven
recommended defaults accepted as-is. Recorded in
[`docs/decisions/ADR-000-gate-1-scope-decisions.md`](decisions/ADR-000-gate-1-scope-decisions.md).

Delivered so far:

| Document | What | Commit |
|---|---|---|
| `docs/REQUIREMENTS_V1.md` | The SRS — 61 FRs (39 in M1), 25 NFRs, ET-1…ET-11, M1…M11 | `811b73a` |
| `docs/ENVIRONMENT.md` | Read-only survey of this machine | `bd71286` |
| `docs/decisions/ADR-000` | The seven Gate 1 decisions | `d7c7f79` |
| `docs/design/` | Design system, M1 chat spec, dashboard direction | `9bc72ec` |
| `docs/ARCHITECTURE_V1.md` | V1 architecture, M1 as first buildable slice | `ca02c02` |
| `docs/decisions/ADR-001…013` | The thirteen technical decisions | `8188570` |
| `docs/THREAT_MODEL.md` | 7 trust boundaries, 34 threats, 13 deferred controls | `b4450e3` |
| `docs/M1_BUILD_PLAN.md` | T1…T20, exclusive file ownership, exit-test coverage | `d3d90aa` |

Nothing of V1 is built yet — no application code exists on `main`. Build starts on
Gate 2 approval.

## 3. What happens next

1. **Stage 5 build** per [`docs/M1_BUILD_PLAN.md`](M1_BUILD_PLAN.md) §8.2 — critical
   path T1 → T2 → T4 → T8 → T10 → T11b → T20. Each task: green tests + CI (T21) +
   independent review, then merged to `main` by the Delivery Manager.
2. **Stage 4–6 — Build the Milestone 1 vertical slice**, per `ROADMAP.md` §22:
   chat → FastAPI → Conversation Gateway → Orchestrator → Claude provider →
   validated JSON plan → Project Manager Agent → GitHub read-only tool → result →
   chat, fully traced. QA writes the red exit tests first.
3. **Stage 7 — Staging**, then **Gate 3 (human)** before anything reaches production.

## 4. Known issues / open items

* ~~BLOCKER — Docker daemon not running~~ **CLEARED 2026-08-14.** The owner started
  Docker Desktop; verified directly: server 29.7.2, Linux containers, Compose v5.3.1.
  It is no longer on M1's critical path either way — ADR-001/005/013 put M1 on SQLite
  with no Redis and no pgvector, so M1 needs zero containers.
* Docker is still needed before Gate 3: the Alembic migration must be verified once
  against real PostgreSQL (architecture debt D-2).
* No LLM provider credentials configured in this shell. The Model Router needs
  them via a secret store, never in prompts or code (`ROADMAP.md` §26.5).
* `node_modules/` in the repo root is stale from the retired TS build (~1.1 GB);
  gitignored, left in place, replaced when the V1 frontend workspace is created.
* No CI pipeline yet on `main` (the old one was defined for the retired stack).

**Ready and verified:** Python 3.13.14 (+pip, venv), Node 24.19.0, pnpm 11.8.0,
Git 2.48.1 with working `origin` auth; ports 3000/3001/5173/8000/8080/5432/6379 all
free. Port 4317 is the Minions Portal and must stay free.

## 5. Where the detail lives

| Document | What |
|---|---|
| `docs/ROADMAP.md` | The plan of record — V1/V2/V3, epics, build order, design rules |
| `docs/decisions/` | ADRs — one file per locked decision |
| `docs/tasks/` | Living task files, one per Stage-4 issue |
| `docs/worklog/` | Dated worklog entries, one per unit of work |
| `.minions/memory/` | Per-agent lessons carried between sessions |
