# 2026-08-13 — Roadmap reset and V1 kickoff

**Team:** Minions Team 18 · **Stage:** 1 → 2 (Intake → Requirements)

## Decisions taken with the owner

| Question | Decision |
|---|---|
| Existing TypeScript/NestJS build (422 tests, unmerged) | **Fresh start.** Archived, not merged. |
| Timeline | **ASAP — this week.** Milestone 1 due 2026-08-17. |
| Budget | ~$150 (premium plan) |
| Team | **Premium — 11 agents**, Architect and Security Reviewer on Fable at maximum effort |
| Development style | **Git-first** — every unit of work committed and pushed as it lands |

## What was done

1. **Archived the retired build.** Tag `archive/v0-typescript-foundation` created at `e1fa666`
   and pushed; branch `feature/phase-1-foundation` retained. Nothing was deleted from history.
2. **Reset `main` onto the new plan** (`d279c67`):
   - deleted the five superseded plan documents;
   - added `docs/ROADMAP.md` (the owner-supplied SUNIL Agentic OS Roadmap) as the plan of record;
   - added `docs/STATUS.md` and the git-first document structure (`decisions/`, `tasks/`, `worklog/`);
   - restored `.gitignore` on `main`, extended to cover Python;
   - removed stale build artefacts (`apps/`, `packages/`, `.turbo/`) left behind by the branch switch.
     Verified first that only `dist/`, `.turbo/` and `.vitest/` output remained — no source was lost.
3. **Carried agent memory across the reset** (`d241866`). `.minions/memory/` was restored from the
   archived branch, and the Backend Engineer's conventions were split: the stack-independent
   principles stay binding, the TypeScript-specific ones are marked archived.
4. **Registered Minions Team 18** on the portal (ruleset v1.8) with a live heartbeat.
5. **Stage 2 dispatched:** Business Analyst writing `docs/REQUIREMENTS_V1.md`; DevOps running a
   read-only environment readiness survey in parallel (`docs/ENVIRONMENT.md`).

## Notes

- `node_modules/` at the repo root is stale from the retired stack. Gitignored, left in place,
  to be replaced when the V1 frontend workspace is created.
- Next human checkpoint is **Gate 1** (scope, requirements, assumptions) once the SRS lands.
