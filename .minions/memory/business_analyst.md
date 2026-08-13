# Memory — Business Analyst (business_analyst)

## Lessons

_None yet. Gate 1 passed first time with no rework._

## Conventions

- SUNIL requirements use stable IDs: `FR-xxx` (functional, MUST/SHOULD/COULD), `NFR-xxx`
  (non-functional, each with a stated verification method), `ET-n` (exit tests),
  `BL-xxx` (backlog, tagged to an owning specialist with explicit dependencies).
- Acceptance criteria are always Given/When/Then and must be executable by QA without
  asking the author a question.
- Architecture and stack choices are NOT the BA's to make. Where the architecture docs are
  silent, record an assumption or route an open question to the Solution Architect — never
  decide. On SUNIL Phase 1 this correctly routed Q4 (permission vocabulary), Q7 (Redis
  persistence) and Q8 (session-auth library).
- Every open question is presented with a **recommended default**, so the human answers a
  confirm-or-correct rather than an open-ended design question. This is what let Gate 1
  clear in a single round trip.

## Preferences

- Isuru (owner) approves fast when defaults are pre-stated and the trade-off is named.
  Gate 1 on Phase 1 was approved as-is with all 7 defaults accepted.
- Exclusion lists are valued: state explicitly what a phase is NOT, because the SUNIL
  architecture doc describes the full 7-phase platform and invites scope creep.

## Project context reset — 2026-08-13

- SUNIL was re-planned onto the owner-supplied `docs/ROADMAP.md` (Agentic OS, V1→V3). Every
  earlier plan document was deleted from `main`; the TypeScript/NestJS build is archived at tag
  `archive/v0-typescript-foundation`. Requirements are written against the roadmap only.
- The roadmap describes three versions and ~13 agents. The exclusion list is therefore the most
  load-bearing part of the SRS, not an afterthought.
