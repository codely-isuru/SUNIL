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
| **Last updated** | 2026-08-17 |

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

**Stage 5 — Development: COMPLETE. M1's vertical slice is built, merged and green.**

## ✅ M1 exit tests pass on `main`

```
513 passed, 0 failed, 6 deselected (live)   — full suite
 18 passed                                   — tests/exit, ET-1 … ET-12
```

Everything is merged to `main`. `POST /api/v1/chat` runs the full roadmap §22
path — chat → gateway → orchestrator → validated plan → Project Manager agent →
read-only GitHub tool → analysis → response — with all twelve NFR-020 trace
stages emitted in order and reconstructable from `audit_events` alone.

**The six deselected tests are the only work M1 has left**, and they need the
owner's credentials (`docs/SECRETS_SETUP.md`): two live end-to-end exit tests,
and four that verify the GitHub PAT is genuinely read-only and single-repo —
because T-17 currently rests on "provisioning is the owner's action", and
provisioning is not verification.

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

### 2026-08-16 — interrupted by a usage limit, recovered clean

The session hit its usage limit and **all six lanes terminated mid-task**. No work was
lost. Every worktree was audited; two dirty trees were committed as `wip(...)` and
pushed (QA's harness rebase, OPS's conftest rule), two unpushed branches were pushed
(T3's capture vocabulary, T11a's base). All nineteen task branches are on `origin`.

**Schedule impact, stated plainly: the interruption cost roughly two calendar days.**
M1 remains due 2026-08-18. The extra day the owner bought on 08-14 has been consumed
by the outage rather than by the build.

---

### 2026-08-16/17 — the merge queue

`main` @ `845f65c` now carries **the whole frontend lane** (`21ab696`) and **seven backend
branches** — T1, T2, T3, T4, T5, T7, T9 — each with an independent QA verdict behind it.

The remaining branches (T6, T8, T10, T11a, T18, T19, T21, T22, T16c) hit real conflicts,
chiefly a **union** in `settings.py` where `main`'s ET-10 redaction fix and T6's ADR-017
loopback validator must both survive. Taking either side would silently drop a security
control, so resolution went to the engineer owning both sides on `task/integration-1`
rather than being improvised at the merge point.

**The recurring defect of this milestone: a branch is green against what it was cut from,
not against what exists.** Three confirmed instances — T5 carrying pre-fix redaction while
its own tests passed; T8's merge-base resolving to a superseded T2 tip; and T11a never
having merged T3, T8 or T10 at all (311 → 417 tests once it did). The worktree model bought
clean concurrent lanes and cheap merges; what it does not give is any signal when the ground
moves under a branch that is already green. Both halves of that trade are now on record.

---

## 3a. Carried into M2 — open, recorded, not blocking

* **Mutation coverage of the wrapper escaping is uncertified.** The Security Reviewer
  mutation-tested its own new assertions: 3 of 4 mutations killed their intended test
  (neutering the ADR-017 loopback guard, removing `follow_redirects=False`, removing
  projection-layer escaping). The 4th — mutating the **wrapper** escaping at
  `projection.py:193` — changed no test outcome, and it could not establish whether the
  mutation applied. **The code is confirmed correct three independent ways** (live prompt
  inspection, a direct delimiter-count test, and the bare `assert` at `:194` now a real
  raise). What is unproven is that any test would catch a *future* regression in that
  layer. Ten minutes with a working mutation settles it.
* **ET-12 alone would not catch a projection-layer regression** — and that is correct
  behaviour, not a defect: ET-12 is an outcome test, and the outcome still holds when one
  layer is removed, because the wrapper is the backstop. **Consequence: the two layer
  tests are load-bearing, not redundant with ET-12.** Do not delete them while tidying.
* **DC-1** — M1's injection posture rests on the analysis call having no tools. That
  expires when agents loop at M6.
* **DC-14** — stored-plan verification (`validated = true` before privileged execution).
  The `validated_plan_id` seam is built and the column carries it; the check is M5.
* **Exclusive file ownership** prevented every cross-lane collision except one, and that
  one (`sunil/capture.py`, created independently by two lanes) came from an ambiguous DM
  instruction rather than from the rule failing.
* `docs/ARCHITECTURE_V1.md:759`'s worked-example plan JSON names `load_recent_activity`;
  the real `config/tools.yaml` registers `list_recent_activity`. QA copied the doc and lost
  an hour to it. Architect's to correct.

---

## 4. Known issues / open items

* ~~BLOCKER — Docker daemon not running~~ **CLEARED 2026-08-14.** The owner started
  Docker Desktop; verified directly: server 29.7.2, Linux containers, Compose v5.3.1.
  It is no longer on M1's critical path either way — ADR-001/005/013 put M1 on SQLite
  with no Redis and no pgvector, so M1 needs zero containers.
* **BUG (integration, found 2026-08-14 by the DM while building T8's base):** two test
  modules share the basename `test_capture.py` — `tests/unit/test_capture.py` (T2) and
  `tests/unit/registry/test_capture.py` (T3). With no `__init__.py` in the test
  directories, pytest raises `import file mismatch` and **aborts the whole collection**:
  `1 error in 0.68s`, no tests run. Each lane passes in isolation; only the merge shows it.
  CI would have gone red on the first multi-lane merge and looked like a code defect.
  **FIXED** by BE-1 during T5 — it renamed its own file to `test_db_capture.py` after
  trying `--import-mode=importlib` and reverting it, because T3's registry tests depend
  on prepend-mode's `sys.path` insertion. OPS retains the harder half: making CI fail
  loudly on a collection *error* (exit 2), and on the wider "absent is green" family.
* **DEBT (ruled 2026-08-16, DM):** the frontend has **no test runner** — vitest/jest/
  testing-library are not in `ARCHITECTURE_V1.md` §14.3's approved list, and the engineer
  correctly refused to add one on a bugfix rather than smuggling in a dependency. Timing
  and race logic like `useTurn`'s is exactly what benefits from fake timers. **Deferred to
  M11 hardening** — choosing a test library is not a decision to take in the last two days
  of a milestone. Consequence carried knowingly: `T16c` ships verified by review and
  reasoning, not by a regression test.
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
