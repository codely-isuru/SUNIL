# ADR-010 — Repeatable-job identity via BullMQ Job Schedulers

_Status: Accepted · Owner: Solution Architect · Phase: 1_

## Context

FR-082/FR-084 and ET-4: the scheduler app only *produces* repeatable definitions; restarts
must not create duplicates (ET-4 4.7 asserts exactly one definition per job key after
re-registration); schedules must fire with the scheduler process down (the schedule lives in
Redis, executed by the worker). BullMQ historically offered the `repeat` option on `add()`,
whose repeat keys are derived from the options — changing a cron string or timezone silently
creates a *second* repeatable definition, the classic duplicate-jobs failure.

## Decision

Use the **BullMQ Job Schedulers API** (BullMQ ≥5.16): the scheduler app, on every boot, calls

```
queue.upsertJobScheduler(schedulerId, repeatOpts, jobTemplate)
```

for each definition with **stable, code-defined scheduler ids** (`system:session-sweep`,
`system:agent-staleness-sweep`, …). Identity is the explicit id, not a hash of the options:

- Re-registration on restart is idempotent — same id, same single definition (ET-4 4.7).
- Changing the interval/cron *updates* the existing definition in place instead of
  duplicating it.
- The scheduler process then idles; workers execute due occurrences whether or not the
  scheduler is alive (FR-082's stopped-scheduler test), because the schedule state is in
  Redis (persisted per ADR-002).
- Scheduler ids are constants in `packages/core`; `JobExecution.schedulerId` records which
  definition produced each run, making ET-4's history assertions directly queryable.
- The legacy `repeat` option is **banned** in this codebase (lint grep in review checklist;
  warning §18.3 of the architecture doc).

## Rejected alternatives

- **Legacy `repeat` option with hand-managed `jobId`.** Its option-derived repeat keys are
  precisely the duplicate-definition hazard ET-4 4.7 exists to catch; BullMQ's own docs
  supersede it with Job Schedulers.
- **Postgres-driven scheduling (poll a `scheduled_jobs` table; e.g. pg-boss or hand-rolled).**
  Durable and transactional, but it replaces the architecture-mandated BullMQ mechanism
  (ARCHITECTURE §1/§2.3) and adds a poller loop we would own; rejected as an unforced
  deviation. Postgres remains the *history* store (FR-083), not the schedule store.
- **OS-level cron / host Task Scheduler.** Breaks NFR-017 portability, lives outside the
  containers, and violates "state lives in Redis + Postgres".
- **In-process `setInterval` in the scheduler.** Explicitly forbidden by ARCHITECTURE rule 4
  and FR-082/ET-4 4.10; listed only for completeness.

## Consequences

- ET-4 is provable end to end: definitions survive restarts (Redis AOF + named volume),
  re-registration cannot duplicate (upsert semantics), execution history survives even a
  Redis wipe (Postgres), and a stopped scheduler does not stop execution.
- BullMQ must be pinned ≥5.16; the version pin in `PHASE1_ARCHITECTURE.md` §4 records this
  floor.
- Removing a scheduler id from code leaves an orphan definition in Redis; the scheduler's
  boot sequence therefore also lists existing Job Schedulers and removes any whose id is no
  longer in the code-defined set (reconciliation, logged + audited).
