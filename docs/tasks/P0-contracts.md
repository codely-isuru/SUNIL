# Task — P0-contracts: V2 Phase 0 contract freeze + rebuild architecture

Owner (solution_architect) · Status: **in-review** (Gate 2 — owner)
**File ownership:** `docs/contracts/**`, `docs/ARCHITECTURE_V2.md`,
`docs/decisions/ADR-031..035*.md`, `docs/decisions/README.md` (table append only),
`docs/tasks/P0-contracts.md`. No app code (Phase 0 platform/fake implementation is a separate
task per the plan).

## Static spec (from the V2 development plan, Phase 0)

- **Background:** ADR-030 Amendment 1 — clean-slate rebuild on `V2`; `main` holds the M1 reference
  build. Six parallel streams need frozen seams before any code.
- **Objective:** freeze C1–C5 as versioned greenfield contracts (informed by M1 shapes), each with
  a QA-buildable fake spec; publish the rebuild architecture with trust boundaries, config
  inventory and the L-001 mutating-request trace; record every open-point decision as an ADR with
  rejected alternatives.
- **Acceptance criteria:** five contracts v1.0.0 with buildable fakes; C4/C5 valid OpenAPI 3.1
  (yaml parses clean); ARCHITECTURE_V2.md contains the traced mutating request + complete config
  inventory; ADRs argued with rejected alternatives; decisions README table updated; granular
  commits pushed to `origin task/P0-contracts`.
- **Security considerations:** §25/§26/§33 non-negotiables; central-memory lessons applied —
  approvals state machine has no schema default and no service-level bypass mode (2026-08-17 ×2);
  full transition enumeration (2026-08-05); funding/auth verified for LiteLLM/Mem0/n8n (2026-08-05).
- **Rollback:** documents only — revert the branch.
- **Documentation needs:** this is the documentation.

## Cross-lane consumers

- `docs/contracts/C1..C5` → consumed by Streams A–F and by the Phase 0 platform task
  (fakes + contract suites + Compose implement exactly these specs).
- `docs/decisions/README.md` table rows 031–035 → consumed by any later ADR author (numbering).
- `docs/ARCHITECTURE_V2.md` §5 → consumed by the platform task (`.env.example`,
  `docker-compose.yml` are generated from it).

## Progress

- [2026-09-10 | solution_architect] Read plan/ADR-030+A1/roadmap §24-26/§33; inspected M1 reference
  shapes read-only via `git show main:` (tool_framework/base.py, permissions/engine.py,
  api/schemas.py, routes/chat.py, settings.py, memory/short_term.py, deps.py — confirmed
  `X-SUNIL-Client: web`); ran central memory brief (no instruction-shaped content found; lessons
  applied and cited in C4/ADR-033).
- [2026-09-10 | solution_architect] Committed, in order: C1 (tool adapter + hooks + fake), C2
  (provider/gateway + FakeProvider), C3 (memory recall/write + FakeMemoryProvider), C4 (OpenAPI
  3.1 + rationale + FakeApprovalsService — yaml parse-verified), C5 (OpenAPI 3.1 + rationale +
  StubTurnExecutor v2 — yaml parse-verified), ADR-031..035 + README table/amendment index,
  ARCHITECTURE_V2.md (TB1–TB9, §5 inventory, §6 L-001 trace), this file. Handed to Delivery
  Manager for owner Gate 2.

## Issues

- none yet (pre-review).

## Questions (proceeding on stated assumptions rather than stalling)

1. **Postgres from day one** (ARCHITECTURE_V2 §1): the plan's platform task adds the Postgres
   container anyway; I made it the app default on V2, keeping ADR-001's portable schema (SQLite
   for unit tests). If the owner prefers SQLite-default as on M1, only §5's `DATABASE_URL` default
   changes — no contract changes.
2. **Approval TTL default 72 h** (C4/§5): owner may prefer shorter for destructive ops;
   per-operation TTLs are a v1.1 additive extension if wanted.
3. **`input_modality=voice` is 422 until the voice milestone is rebuilt on V2** (C5 §2.2) —
   assumed acceptable since M9 designs carry over as requirements, not code (ADR-030 A1).

## Outcome

- Commits (branch `task/P0-contracts`, pushed): C1..C5 contracts, ADR-031..035 + README,
  ARCHITECTURE_V2.md, task file — see `git log --oneline a263193..`.
- Test evidence: C4/C5 YAML parsed clean with PyYAML (documented in Progress); no code claimed.
- Notes: Phase 0 exit additionally requires the platform task (fakes, contract suites, Compose
  boot) which builds FROM these specs; that task is not this one.
