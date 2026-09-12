# ADR-036 — Tasks, activity and audit ship as three frozen read-only endpoints (C6); tasks gains a project_key column

**Status:** Accepted (owner Gate 2 ruling Q1 = freeze, 2026-09-11) · **Date:** 2026-09-11 ·
**Decider:** owner (Q1), Solution Architect (shape freeze + Q2)
**Fixes an open point in:** `V2_DASHBOARD_SPEC.md` §14 Q1 and Q2 — three of six dashboard views
(§7 Agent activity, §8 Tasks, §10 Audit browser) and, since round 4, the unified Dashboard landing
itself (§16.2) had no HTTP contract to build against; and `tasks` had no project linkage.
**Context refs:** contract **C6** (`docs/contracts/C6-ops-reads.md` + OpenAPI) — the freeze this
ADR authorises; C4 §6.5 + `docs/tasks/P0-fakes.md` F8 (the pagination law C6 reuses); C5
(failure kinds, `ProjectSummary`); ADR-031 (parked tasks), ADR-035 (bearer stays chat-only),
ADR-023 (the twelve-stage spine); `ARCHITECTURE_V1.md` §3.4/§7.3 (the raw tables).

## Context

Stream D's frontend could render approvals (C4) and chat outcomes (C5), but §7/§8/§10 — and the
round-4 Dashboard's three summary boxes — consumed shapes that existed only as §13 *proposals*.
Q1 asked the owner: freeze them, or cut the three views from the first release. The owner ruled
**freeze** at Gate 2 (2026-09-11). Q2 remained with the Architect: the §13.1 `Task` shape carries
`project_key`, but the `tasks` table has no such column (the project lives only in
`audit_events.detail`).

## Decision

1. **C6 freezes exactly the spec §13.1–13.3 shapes** as v1.0.0: `GET /api/v1/tasks` (+
   `/{task_id}` with `status_events`), `GET /api/v1/activity` (one-request snapshot: running /
   parked / recent≤20, each task folded with its latest audit stage), `GET /api/v1/audit`
   (turns grouped by `request_id`) + `/{request_id}` (events / approval_events partition).
   Read-only; owner-session lane identical to C4; no bearer lane (ADR-035 scope untouched).
2. **One pagination law, C4 §6.5's as QA pinned it (F8):** `created_at desc, id desc` with plain
   string (lexicographic) id comparison; cursor = last row's id; `next_cursor` null ONLY on a
   short page (an exactly-full final page returns a cursor; the next, empty page ends the walk);
   unknown cursor → 422. C6 must not mint a second law — Stream D writes one pager.
3. **Q2 ruled: add the column.** `tasks.project_key` (string, nullable), written once at task
   creation from the `ValidatedPlan` (the value `plan_created.detail.project_key` already
   records), never updated. One line of reasoning: the frozen shape already names it — a v1
   without the filter would contradict the ruling that froze the shape — and the value is known
   exactly once and immutable, so deriving it per-row from `audit_events.detail` at list time
   is the N+1-on-a-poll that §13.2 exists to kill. §9/§16 project counts ride
   `GET /api/v1/tasks?project_key=…`; no counts endpoint is added.
4. **Containment travels with the rows:** `objective`, audit `summary` and audit `detail`
   values are untrusted/untrusted-influenced and carry the C4 §4 / spec §6.3 plain-text-only
   rendering rule; the server returns them byte-faithful and never sanitises (C6 §4, test 10).

## Rejected alternatives

| Rejected | Why |
|---|---|
| **Cut the three views for v1** (ship approvals + chat only — Q1's other arm) | Was viable before round 4; the owner's unified Dashboard (§16.2) makes the missing endpoints degrade the *landing view itself*, not just three deep views, and the owner ruled freeze. The shapes were already designed, reviewed at Gate 2, and cost three read paths over existing tables — deferral bought nothing but placeholder boxes |
| **GraphQL-style single query / one composite `GET /api/v1/dashboard`** | Builds the "sixth data model" §16.1 forbids — the Dashboard is the summary tier of the five views, not its own contract. A composite response couples all sections' failure modes, while §16.5 requires one failed section to leave the rest working (per-section `ErrorPanel`); and a query language on a single-consumer, owner-only surface is standing attack surface plus a dependency for zero additional callers. Three plain REST reads keep C4's auth, error and pagination conventions verbatim |
| **Reuse `audit_events` raw** (generic `GET /api/v1/audit_events?filters`, client assembles tasks/activity/turns) | Re-creates the N+1 §13.2 exists to kill (activity = tasks × latest-stage lookups on a 10 s poll); moves grouping/derivation (`stage_count`, outcome, episode partition) into the client where each view forks its own reading; hands the browser raw `detail` payloads (T-32 untrusted excerpts) it mostly does not need instead of the projected trusted keys; and couples the web app to a table layout the rebuild may migrate. The audit *browser* still gets the full rows — through a shaped turn detail with the containment note attached |
| **Q2 alternative: no project filter in v1** (derive the column only where `plan_created.detail` is loaded — the spec's own default-if-unanswered) | Contradicts the frozen §13.1 shape (which carries `project_key` in row and filter); leaves §9's counts and §16.2's Projects box unbuildable; and permanently prices the Tasks project column at a per-row audit join. A nullable write-once column is the cheapest honest linkage and is backfillable later from `audit_events` if wanted |

## Consequences

- Stream D unblocks §7/§8/§10/§16 against `FakeOpsStore` (C6 §6); QA builds the fake + suite
  (`test_c6_ops_reads.py`, ten tests) on the branch that implements it.
- The DB migration adding `tasks.project_key` belongs to the stream that owns the tasks table
  schema; until it lands, the fake models the end state (the column exists in every fixture).
- `ARCHITECTURE_V2.md` §2 route table amended (dated) with `routes/{activity,tasks,audit}.py`.
- Q3/Q4/Q5/Q8/Q9 stay open and are not moved by this ADR; Q9 changes observed `stage_count`
  values only, never the C6 shapes.
