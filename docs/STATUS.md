# SUNIL — STATUS

**Read this first.** It is the single source of truth for where the project stands.

| | |
|---|---|
| **Project** | S.U.N.I.L. — Personal + Business Agentic OS |
| **Current phase** | V1 — SUNIL Core (cloud-first) |
| **Plan of record** | [`docs/ROADMAP.md`](ROADMAP.md) — supersedes every earlier plan document |
| **Branch** | `main` (single-branch rule; feature work lands via short-lived branches → `main`) |
| **Delivery** | Minions Team 18 (portal `http://localhost:4317`) |
| **Due** | 2026-08-17 (Milestone 1 vertical slice) · budget ~$150 |
| **Last updated** | 2026-08-13 |

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

**Stage 3 — Architecture & Design**, running now (Architect ∥ Designer, in parallel).

**✅ GATE 1 APPROVED — 2026-08-14, by the owner.** Scope, requirements and all seven
recommended defaults accepted as-is. Recorded in
[`docs/decisions/ADR-000-gate-1-scope-decisions.md`](decisions/ADR-000-gate-1-scope-decisions.md).

Delivered so far:

| Document | What | Commit |
|---|---|---|
| `docs/REQUIREMENTS_V1.md` | The SRS — 61 FRs (39 in M1), 25 NFRs, ET-1…ET-11, M1…M11 | `811b73a` |
| `docs/ENVIRONMENT.md` | Read-only survey of this machine | `bd71286` |
| `docs/decisions/ADR-000…` | The seven Gate 1 decisions | this commit |

Nothing of V1 is built yet — no application code exists on `main`.

## 3. What happens next

1. **Stage 3 (running)** — Architect: architecture, data model, Model Router, plan
   validation, permission engine, threat model, ADR-001+, and the M1 task breakdown.
   Designer: design system + the M1 chat spec. → **Gate 2 (human)**
2. **Stage 4–6 — Build the Milestone 1 vertical slice**, per `ROADMAP.md` §22:
   chat → FastAPI → Conversation Gateway → Orchestrator → Claude provider →
   validated JSON plan → Project Manager Agent → GitHub read-only tool → result →
   chat, fully traced. QA writes the red exit tests first.
3. **Stage 7 — Staging**, then **Gate 3 (human)** before anything reaches production.

## 4. Known issues / open items

* **BLOCKER — Docker daemon is not running** (found 2026-08-13 by the environment
  survey, `docs/ENVIRONMENT.md`). Docker Desktop 29.7.2 is installed but its WSL2
  distro is stopped, and this machine has **no native PostgreSQL and no Redis**.
  The roadmap's whole data layer (Postgres + pgvector + Redis) therefore has no
  local fallback. **Human action required:** start Docker Desktop. Until then no
  DB-backed M1 work can be smoke-tested.
* No `docker-compose.yml` yet — Epic 1, not started.
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
