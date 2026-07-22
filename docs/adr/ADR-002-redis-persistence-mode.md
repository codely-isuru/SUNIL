# ADR-002 — Redis persistence mode (routed question Q7)

_Status: Accepted · Owner: Solution Architect · Phase: 1_

## Context

Exit test ET-4 requires that no scheduled occurrence is silently lost across a real container
restart (FR-084; critical scenario 14's durability half). BullMQ stores queue state — waiting,
delayed and repeatable/Job-Scheduler definitions — in Redis, so Redis persistence policy
determines the worst-case loss window. The BA's straw man: AOF `everysec` on a named volume.
Also relevant: BullMQ corrupts silently under key eviction, and a clean `docker compose stop`
sends SIGTERM (Redis flushes and saves on graceful shutdown).

## Decision

Pin `redis:7.4-alpine` and run with:

```
--appendonly yes --appendfsync everysec --maxmemory-policy noeviction
```

on a named volume (`redisdata:/data`). Redis 7's default `aof-use-rdb-preamble yes` stays on
(compact rewrites). RDB snapshot defaults remain enabled as a secondary artefact.

**Resulting worst-case data-loss window:**

- **Clean container stop/start (the ET-4 scenario): zero loss** — Redis fsyncs and exits
  gracefully on SIGTERM.
- **Hard crash of the Redis process/host: ≈1 second** of acknowledged writes (the everysec
  fsync interval).

Two design decisions cap the blast radius of even that 1 s window: repeatable-schedule
definitions are **re-created idempotently by the scheduler at every boot**
(`upsertJobScheduler`, ADR-010), so schedule durability does not depend on Redis persistence
alone; and execution history lives in Postgres (FR-083), so the historical record survives
even a full Redis wipe. The residual exposure is a delayed one-off job enqueued in the final
~1 s before a hard crash — accepted for Phase 1, documented in the phase report.

`noeviction` is mandatory: any eviction policy can delete BullMQ keys under memory pressure,
which is silent job loss — the exact failure ET-4 exists to prevent.

## Rejected alternatives

- **RDB snapshots only.** Loss window = minutes (snapshot interval); a restart inside the
  window silently loses delayed jobs — fails the intent of ET-4 even if a lucky test run
  passes. Rejected outright.
- **AOF `appendfsync always`.** Loss window ~0 on hard crash, but an fsync per write on a
  single dev machine measurably degrades queue throughput for no Phase 1 requirement — the
  1 s window is already below any scheduled granularity in the system.
- **No persistence, rely on idempotent re-registration alone.** Covers repeatables but loses
  every waiting/delayed one-off job on any restart — fails FR-084's "jobs waiting in a queue
  at shutdown" clause.
- **Valkey 8 instead of Redis.** Functionally equivalent for BullMQ and Apache-2.0 licensed;
  not chosen now because the `redis:7.4` image is the ecosystem default with the most
  operational documentation. Recorded as the sanctioned drop-in swap if Redis licensing
  posture ever matters for deployment (Phase 7 revisit).

## Consequences

- ET-4 can be executed against real container stops with a provable zero-loss expectation,
  and against hard-kill scenarios with a stated ≤1 s bound.
- The Compose `redis` service must carry the exact command flags; a review check in BL-002
  verifies them (they are load-bearing configuration, not tuning).
- AOF grows on disk; default auto-rewrite thresholds handle it — no operator action in
  Phase 1.
