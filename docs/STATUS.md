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

### 2026-09-10 — V2 clean slate (owner decision) · Minions V2 engagement starts

**Owner decision:** branch `V2` starts with **no application code**. Removed from `V2`:
`apps/` (M1 FastAPI + Next.js), `config/`, `scripts/`, `prototype/`, V1 CI and `.env.example`
(256 files). **`main` keeps the complete live-verified M1 build** as reference + fallback.
Recorded as **ADR-030 Amendment 1**; `V2_DEVELOPMENT_PLAN.md` is now ADOPTED with contracts
C1–C5 read as greenfield interfaces informed by M1. Branch cleanup 2026-09-10: all task/*,
feature/*, fix/* branches deleted local+origin (archive tag `archive/v0-typescript-foundation`
kept; full pre-cleanup bundle at `C:
epo\SUNIL-branches-archive-2026-09-10.bundle`).

**✅ WAVE 2 ROUND 1 (WIRING) COMPLETE — 2026-09-12.** SUNIL boots with REAL seams. Delivered and
merged: real ToolManager/permissions/approvals/providers wiring; security conditions C-1 + C-3
CLOSED (adversarially re-verified); C4 v1.2.0 (service owns time) and C1 v1.2.0 (typed
ApprovalRef, forge-proof) frozen + implemented end-to-end — a parked chat turn now carries its
real approval reference; reconciliation rule 4 + lazy-expiry finalisation; the lying integration
double RETIRED (real manager 14/14); all review residuals closed. Suite: 955/0/4 SQLite,
1003+/0/4 Postgres. e2e evidence on real Postgres in docs/tasks/S2-wiring.md. OPEN: live-model
turn awaits owner provider keys (infra/.env.litellm per SECRETS_SETUP.md). NEXT: round 2 —
Streams C (Mem0), E (n8n), F (OpenHands) — budget gate with the owner.

**✅ WAVE 1 MERGED TO `V2` — 2026-09-12 (c474baa).** The V2 core exists and is review-clean:
spine (12-stage governed turn, live-proven against fakes), tool chokepoint + permission engine +
GitHub tool + MCP adapters, model gateway (live-verified against real LiteLLM), approvals service
(CAS race-proven on real Postgres) + C6 ops reads, the full contract-fake suite, and the Obsidian
& Gold web app (screenshot-verified against the approved mockups, injection containment live).
Suite at merge: 912/0/4 SQLite · 951/0/4 Postgres. Reviews mirrored in docs/reviews/2026-09-12-*.
Branches cleaned: only `main` + `V2` remain.

**NEXT — WAVE 2 (the wiring round):** flip `wiring.py` to real seams and boot the governed turn
against the live Compose stack end-to-end. Blocking security conditions inherited by name
(THREAT_MODEL §9): C-1 transactional consume+attempt at the chokepoint, C-3 credential_env
allowlist. Plus: SA's decide-clock question (integration-w1 §8.3 — the C4 decision path has no
green coverage in the bootable config until answered), R2 ORM-class fence, R3 Origin move,
lane-flag tripwire hardening, agents.yaml grants-vs-catalogue warning, test-side schema
workaround removal. Then Streams C (Mem0), E (n8n), F (OpenHands).

**WAVE 1 BUILT + INTEGRATED (2026-09-12).** All six lanes done; merged onto `task/integration-w1`
(two unions hand-resolved: pyproject deps, unit conftest). Integration exposed and fixed 15
integration-only failures (win32 event-loop collision between lanes, five wiring gaps — the
merged app served 404 on every C4/C6 route — missing tasks.priority, 403→401 bearer symmetry).
Suite 897/2 (the 2 are QA-owned harness lines). Visual pass done: the real app ran in the
browser against mock data, faithful to the approved mockups incl. the injection-containment
behaviour on the approval card. IN FLIGHT: Alembic two-heads fix (fresh deploy blocker) +
id-type reconcile · QA wave review (harness lines + author=asserter re-reviews + cross-lane
sweep) · Security wave review (deferred-checklist verification on real code). Merge to `V2`
after verdicts. NEXT MILESTONE after merge: Phase-2 plugging — wiring.py still refuses real
seams by design; the app boots only with injected fakes.

**▶ RESUMED — owner, 2026-09-12.** All five unfinished lanes re-dispatched, each instructed to
reconstruct state from its own branch (task file + git log + wip diff + a ground-truth test run)
before writing anything, and to merge origin/V2 first (brings C6). S-A-tools stays done+held.

**⏸ PAUSED BY OWNER — 2026-09-11.** All five running wave-1 lanes stopped mid-task; every
worktree wip-committed and pushed (nothing lost, nothing merged, nothing reviewed). Resume map:
S-A-tools ✅ DONE (held for wave review) · S-spine ~60% (3 commits + wip: conversations/tasks/
memory-service/audit-hooks were in progress) · S-B-gateway wip only (was on the live LiteLLM
401 probe) · S-D-approvals wip only (C6 landed after its start; sweeper module in progress) ·
S-D-web 3 commits + wip (render smoke tests pending) · S-C6-fakes wip (mid-TDD red phase).
To resume: re-dispatch each unfinished lane with "continue from the wip commit on your branch —
read your task file and git log first." Portal Team 21 session stays live (heartbeat only).

**GATE 2 APPROVED — owner, 2026-09-11. Designs approved (round 4). PHASE 1 STREAMS LAUNCHED.**
Owner rulings recorded: Q1 = FREEZE spec (13)'s three read-only ops endpoints (dashboard consumes
them; SA formalising as contract addendum); Q4 risk labels = deferred to Phase 2 backlog; Q8 =
responsive web covers phone approvals in v1, no native app. Budget note: ~$250 of $300 consumed
by Phase 0; DM raised the engagement envelope to $500 for Phase 1 (owner may veto; flagged in
session). Wave 1 lanes: S0 ops-read contracts (SA) - spine (app/db/audit/chat/orchestrator) -
A tools+manager - B gateway/providers - D approvals service - D web dashboard. Wave 2 after
merges: C memory, E n8n, F OpenHands, integration.

**GATE 2 IS FULLY ASSEMBLED (2026-09-11) — everything now waits on the owner.** The package:
(1) plain-English briefing artifact (link in the session); (2) baseline docs on `V2` (contracts
C1 v1.1.1 / C2 v1.0.1 / C3-C4 v1.1.0 / C5 v1.0.0, ARCHITECTURE_V2, ADRs, 171 tests / 146 pass);
(3) UI design package on `task/P0-ui-design` (spec, 11 decisions, 6 mockups) — owner requires UI
approval before Stream D builds. Defaults RATIFIED by owner: consume-grace 1h, service-lane
restriction. Design open questions: Q1 (blocker — Activity/Tasks/Audit have no HTTP contract;
freeze spec §13's shapes or cut from v1), Q6 landing view, Q7 light theme, Q8 mobile, Q4 risk
labels → owner; Q2/Q3/Q5/Q9 → SA/Security at stream kickoff. No agents running.

**✅ PHASE 0 COMPLETE — 2026-09-10, awaiting Gate 2 (owner).** All exit criteria met on `V2`:
C1–C5 frozen (C1/C3/C4 v1.1.0, C2 v1.0.1, C5 v1.0.0) with OpenAPI; fakes + contract suites
published (170 tests: 145 pass, 25 self-activating skips; two mutation proofs); Compose platform
boots green loopback-only with 3 DB roles; CI: 3 gates green. Review chain: Security BLOCK →
fixes → BLOCK LIFTED; QA FAIL → fixes → suites green; independent backend review of the fakes
PASS-w-conditions → conditions closed. Open should for Stream A: empty-but-present ParkContext
behaviour (P0-fakes task file). Next: Gate 2 ratification, then the six parallel streams.

**Phase 0 progress (2026-09-10):** both lanes DONE and DM-verified — `task/P0-contracts`
(SA: C1–C5 frozen v1.0.0, ARCHITECTURE_V2, ADR-031..035, 9 commits) and `task/P0-platform`
(DevOps: Compose stack pg17+pgvector:5433 / LiteLLM:4000 / n8n:5680 booted + probed, CI green
run 34370950604, 8 commits). Independent QA + Security reviews IN FLIGHT; known cross-lane
drift to resolve before merge: ADR-032 ports (5432/5678) vs actual host bindings (5433/5680).
Merge to `V2` only after PASS/APPROVE, then Gate 2 (owner).

**Fix rounds returned and MERGED to `V2` (2026-09-10):** both lanes fixed every blocker and
every should — see the disposition tables in [`tasks/P0-contracts.md`](tasks/P0-contracts.md) and
[`tasks/P0-platform.md`](tasks/P0-platform.md). ADR-032 Amendment 1 lands the real ports
(5433/5680/3001); ADR-031 Amendment 1 fixes consume ownership (Tool Manager, single actor);
platform now loopback-only with 3 DB roles, fixture-tested CI gates, true first-boot evidence.
**Security delta re-verify (merged tip 8b0dafa): BLOCK LIFTED — Phase-0 architecture baseline
approved.** Residuals S-1..S-6 non-blocking (S-1 driver-token drift psycopg vs asyncpg and S-2
missing SUNIL_APPROVAL_CONSUME_GRACE_HOURS in .env.example go to the next engineering round);
QA fakes build DONE (task/P0-fakes: 102 passed/22 documented skips, mutation-proven, CI green)
— and it exposed a real C3 contract defect (write() had no scope). Backend engineer independent
review: PASS-with-conditions (AST-level transcription diff clean; buildability proven with a
probe ToolManager). SA closed C3 v1.1.0 + C4/C1 v1.0.1 + S-1..S-5 on task/P0-c3-scope; SA
follow-up adjudicating BE findings F3 (ParkRequest continuation source) / F4 (adapter_kind) /
F11 (extra=forbid) IN FLIGHT; then one consolidated QA update, merge, Gate 2.
12-item deferred-to-build checklist recorded in the re-verify report; highest-priority open item:
prove n8n MCP auth-token enforcement (Stream E). IN FLIGHT: QA building
the C1–C4 fakes + contract suites (exit criteria 3–4). Then Gate 2 (owner).

**Reviews returned (2026-09-10): Security BLOCK · QA FAIL — bounced to owners, fixes in flight.**
Reports: [`reviews/2026-09-10-P0-security-review.md`](reviews/2026-09-10-P0-security-review.md) ·
[`reviews/2026-09-10-P0-qa-review.md`](reviews/2026-09-10-P0-qa-review.md). Blockers: port
inventory drift (ADR-032 5432/5678 vs real 5433/5680/3001), 0.0.0.0 publishes (live-verified
LAN-reachable), single-superuser Postgres vs TB9, C1/C4 consume-twice contradiction, C3
audit_event_id unobtainable + dedupe contradictions, C1 hook fakes unspecified, C2 model-id
namespace mismatch, CRLF first-boot failure. DM rulings for the fix round: TB9 stands (three DB
roles); gateway alias namespace is authoritative for C2; retries live SUNIL-side (gateway
num_retries: 0); drop_params off. Fakes + contract suites (exit criteria 3–4) follow with QA
once contract fixes land.

**Engagement:** Minions team on branch `V2`, due **2026-10-08**, budget **$300**, urgency ASAP.
Models per owner: developers Opus 4.8 · QA Opus 5 · Solution Architect Fable 5.1 · Security
Reviewer Fable (hard rule). First unit of work: **Phase 0 — contracts C1–C5 + Compose platform
+ fakes** per `V2_DEVELOPMENT_PLAN.md`.


### 2026-08-21 — V2 architecture finalised (branch `V2`)

The owner delivered the **finalised SUNIL architecture** (`design/ARCHITECTURE_V2_FINAL.html`)
and a parallel-stream **development plan** (`V2_DEVELOPMENT_PLAN.md`). Decision recorded as
[ADR-030](decisions/ADR-030-integrate-open-source-components.md). Committed to branch **`V2`**.

**Stance (resolves the earlier draft conflict):** *integrate open-source behind SUNIL''s existing
seams* — the live M1 control plane stays at the centre; **no M1 code is retired.** This finalises
the earlier `update/v2-architecture` draft with two changes: **n8n replaces Windmill** (1,500+
connectors, MCP-native), and **OmniRoute** is admitted as a dev-only lane behind LiteLLM (PUBLIC
workloads only). Hermes is a channel gateway only; ContextForge and Graphiti rejected (ADR-030).

**Delivery:** to be built by the Minions team as six parallel streams (A–F) against five frozen
contracts (C1–C5). Model assignment for this engagement — **all developer/QA/ops roles on
Opus 4.8; Solution Architect + Security Reviewer on Opus 5.** M2 (streaming) and M9 (voice) files
are untouchable by V2 streams.


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

**M1 — COMPLETE AND LIVE-VERIFIED. Next phase: M9 (Voice).**

## ✅ M1 verified against real credentials, real data, a real model

```
564 fixture tests   passing
  7 live tests      passing   (2 honest skips: no private control repo; one env-scoped)
```

A real turn, driven through the browser on 2026-08-19:

```
request_id 70a19c8c-…    turn completed in 5.8s (target: 30s p95)
stages     : 12                     <- ET-6, in order, from audit_events
tool_calls : github / list_recent_activity / allow / validated_plan_id present   <- ET-4
llm_calls  : plan 260->126, analysis 2676->209    (one row per provider attempt)  <- ET-9
task       : completed / project_manager                                         <- ET-3
```

SUNIL read `codely-isuru/easy_clean_workforce` and reported the Sentry integration state,
the refreshed staging environment, and — unprompted — flagged an "unowned" dependency
install worth auditing plus outstanding owner-side gate items. Real analysis of real
commits, not a summary of fixtures.

**Provider note:** the hot path runs OpenAI (`gpt-5.1`); the Anthropic provider is built,
tested and one config line away. Both keys are live.

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
* ~~`docs/ARCHITECTURE_V1.md:759`'s worked example named `load_recent_activity`~~ **FIXED
  2026-08-17.** The real `config/tools.yaml` registers `list_recent_activity`; QA copied the
  doc and lost an hour to it. Corrected at source, and the repo now has no remaining
  reference to the wrong spelling.

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
