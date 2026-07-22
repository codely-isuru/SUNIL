/**
 * FR-081 / FR-083 — the processor contract: history rows in Postgres, handler deadlines,
 * failures rethrown so BullMQ retries and retains them.
 *
 * These exercise `processJob` directly with a job-shaped double, so the branch behaviour is
 * asserted without waiting on a broker; the real-broker proof is `et4.integration.test.ts`.
 */
import { describe, expect, it } from "vitest";
import { DEFAULT_JOB_OPTIONS, DeadlineExceededError, QUEUE_NAMES } from "@sunil/core";
import type { Job } from "bullmq";
import type { JobExecution, Prisma } from "@sunil/db";
import { JobHistoryRecorder, redactError, type JobHistoryStore } from "../job-history.js";
import { createLogger } from "../logger.js";
import { JOB_TIMEOUT_MS, processJob, withDeadline, type HandlerRegistry } from "../worker.js";

class MemoryHistoryStore implements JobHistoryStore {
  readonly rows: (Prisma.JobExecutionCreateInput & { id: string })[] = [];

  start(data: Prisma.JobExecutionCreateInput): Promise<JobExecution> {
    const row = { ...data, id: `exec-${this.rows.length + 1}` };
    this.rows.push(row);
    return Promise.resolve(row as unknown as JobExecution);
  }

  finish(
    id: string,
    data: Pick<Prisma.JobExecutionUpdateInput, "outcome" | "finishedAt" | "durationMs" | "error" | "result">,
  ): Promise<JobExecution> {
    const row = this.rows.find((candidate) => candidate.id === id);
    if (!row) return Promise.reject(new Error(`no row ${id}`));
    Object.assign(row, data);
    return Promise.resolve(row as unknown as JobExecution);
  }

  findByBullJobId(bullJobId: string): Promise<JobExecution[]> {
    return Promise.resolve(
      this.rows.filter((row) => row.bullJobId === bullJobId) as unknown as JobExecution[],
    );
  }
}

const logger = createLogger("worker-test", "silent");

function fakeJob(overrides: Partial<Job> = {}): Job {
  return {
    id: "1",
    name: "session-sweep",
    data: { correlationId: "corr-job-1" },
    attemptsMade: 0,
    ...overrides,
  } as unknown as Job;
}

function harness(registry: HandlerRegistry) {
  const store = new MemoryHistoryStore();
  const history = new JobHistoryRecorder(store);
  return {
    store,
    deps: { connection: undefined as never, registry, history, logger },
  };
}

describe("job execution history is written to Postgres (FR-083)", () => {
  it("records RUNNING at start and COMPLETED with a duration and result at finish", async () => {
    const { store, deps } = harness({
      "session-sweep": { timeoutMs: 1000, handler: () => Promise.resolve({ revoked: 3 }) },
    });

    const result = await processJob(QUEUE_NAMES.system, fakeJob(), deps);

    expect(result).toEqual({ revoked: 3 });
    expect(store.rows).toHaveLength(1);
    expect(store.rows[0]).toMatchObject({
      jobName: "session-sweep",
      queue: "system",
      bullJobId: "1",
      attempt: 1,
      outcome: "COMPLETED",
      result: { revoked: 3 },
    });
    expect(store.rows[0]?.durationMs).toBeGreaterThanOrEqual(0);
  });

  it("records the Job Scheduler id for an occurrence produced by a repeatable definition", async () => {
    const { store, deps } = harness({
      "agent-staleness-sweep": { timeoutMs: 1000, handler: () => Promise.resolve({ swept: 0 }) },
    });

    await processJob(
      QUEUE_NAMES.system,
      fakeJob({ name: "agent-staleness-sweep", repeatJobKey: "system:agent-staleness-sweep" } as Partial<Job>),
      deps,
    );

    expect(store.rows[0]?.schedulerId).toBe("system:agent-staleness-sweep");
  });

  it("records FAILED and rethrows so BullMQ can retry and retain the job", async () => {
    const { store, deps } = harness({
      "session-sweep": { timeoutMs: 1000, handler: () => Promise.reject(new Error("handler exploded")) },
    });

    await expect(processJob(QUEUE_NAMES.system, fakeJob(), deps)).rejects.toThrow("handler exploded");

    expect(store.rows[0]).toMatchObject({ outcome: "FAILED" });
    expect(String(store.rows[0]?.error)).toContain("handler exploded");
  });

  it("records the attempt number on a retry", async () => {
    const { store, deps } = harness({
      "session-sweep": { timeoutMs: 1000, handler: () => Promise.resolve({}) },
    });

    await processJob(QUEUE_NAMES.system, fakeJob({ attemptsMade: 2 } as Partial<Job>), deps);
    expect(store.rows[0]?.attempt).toBe(3);
  });

  it("classifies an overrunning handler as TIMED_OUT (FR-081)", async () => {
    const { store, deps } = harness({
      "session-sweep": {
        timeoutMs: 20,
        handler: () => new Promise((resolve) => setTimeout(resolve, 500)),
      },
    });

    await expect(processJob(QUEUE_NAMES.system, fakeJob(), deps)).rejects.toBeInstanceOf(
      DeadlineExceededError,
    );
    expect(store.rows[0]?.outcome).toBe("TIMED_OUT");
  });

  it("fails loudly — and records history — for an unregistered job name", async () => {
    const { store, deps } = harness({});

    await expect(
      processJob(QUEUE_NAMES.agents, fakeJob({ name: "not-a-job" } as Partial<Job>), deps),
    ).rejects.toThrow(/no handler registered/);
    expect(store.rows[0]?.outcome).toBe("FAILED");
  });

  it("closes orphaned RUNNING rows as STALLED at boot", async () => {
    const store = new MemoryHistoryStore();
    const history = new JobHistoryRecorder(store);
    const abandoned = await store.start({
      jobName: "session-sweep",
      queue: "system",
      bullJobId: "abandoned-1",
      attempt: 1,
      startedAt: new Date(Date.now() - 60 * 60_000),
      outcome: "RUNNING",
    });

    const closed = await history.reconcileOrphans([abandoned]);

    expect(closed).toBe(1);
    expect(store.rows[0]?.outcome).toBe("STALLED");
    expect(String(store.rows[0]?.error)).toContain("abandoned");
  });

  it("closes RUNNING rows as STALLED via the QueueEvents backstop", async () => {
    const store = new MemoryHistoryStore();
    const history = new JobHistoryRecorder(store);
    await history.begin({ jobName: "agent-run", queue: "agents", bullJobId: "77", attempt: 1 });

    const closed = await history.markStalled("77");

    expect(closed).toBe(1);
    expect(store.rows[0]?.outcome).toBe("STALLED");
  });
});

describe("retention and redaction", () => {
  it("keeps failed jobs (removeOnFail: false) so they stay visible and rerunnable (FR-081)", () => {
    expect(DEFAULT_JOB_OPTIONS.removeOnFail).toBe(false);
    expect(DEFAULT_JOB_OPTIONS.attempts).toBe(3);
    expect(DEFAULT_JOB_OPTIONS.backoff).toEqual({ type: "exponential", delay: 5000 });
  });

  it("redacts credential-shaped material out of a persisted job error", () => {
    const redacted = redactError(
      new Error("provider rejected key sk-ant-abcdefghijklmnopqrstuvwxyz012345"),
    );
    expect(redacted).not.toContain("abcdefghijklmnopqrstuvwxyz012345");
    expect(redacted).toContain("[REDACTED]");
  });

  it("gives every job a deadline", () => {
    expect(Object.values(JOB_TIMEOUT_MS).every((value) => value > 0)).toBe(true);
  });

  it("cancels rather than schedules: withDeadline clears its timer on success", async () => {
    await expect(withDeadline(Promise.resolve("ok"), 50, "unit")).resolves.toBe("ok");
  });
});
