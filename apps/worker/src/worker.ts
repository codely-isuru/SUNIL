/**
 * The BullMQ worker runtime (§12.1, FR-081).
 *
 * One `Worker` per Phase 1 queue (`system`, `agents`) over a shared Redis connection, plus a
 * `QueueEvents` listener that backstops `STALLED`.
 *
 * Guarantees this file implements:
 *  - a `JobExecution` row in Postgres at start (RUNNING) and at finish (COMPLETED / FAILED /
 *    TIMED_OUT / STALLED) — history survives a Redis wipe (FR-083);
 *  - a handler-level deadline, so an overrunning handler is failed with a TIMEOUT
 *    classification rather than hanging (FR-081);
 *  - failures rethrown so BullMQ applies the configured retry/backoff and, once attempts are
 *    exhausted, RETAINS the job (`removeOnFail: false`) — visible and rerunnable (FR-081);
 *  - graceful shutdown that lets active jobs finish.
 *
 * NO `setInterval`/`setTimeout` schedules work here. The only timer is the per-job deadline
 * below, which cancels work rather than scheduling it (ET-4 4.10).
 */
import { QueueEvents, Worker, type Job } from "bullmq";
import type { Redis } from "ioredis";
import { DeadlineExceededError, JOB_NAMES, type QueueName } from "@sunil/core";
import type { JobHistoryRecorder } from "./job-history.js";
import type { AppLogger } from "./logger.js";

export interface JobContext {
  readonly jobName: string;
  readonly queue: QueueName;
  readonly bullJobId: string;
  readonly attempt: number;
  readonly correlationId: string;
  readonly data: unknown;
  readonly logger: AppLogger;
}

export interface JobHandlerEntry {
  readonly handler: (context: JobContext) => Promise<unknown>;
  /** Handler-level deadline. Code constants: the Phase 1 config inventory is closed (§16). */
  readonly timeoutMs: number;
}

export type HandlerRegistry = Readonly<Record<string, JobHandlerEntry>>;

/** Per-job deadlines. `agent-run` is the outer bound; the agent's own `maxDurationSeconds` halts it first (§11.4). */
export const JOB_TIMEOUT_MS: Readonly<Record<string, number>> = {
  [JOB_NAMES.sessionSweep]: 60_000,
  [JOB_NAMES.agentStalenessSweep]: 60_000,
  [JOB_NAMES.agentRun]: 15 * 60_000,
};

/** Small and deliberate: this is a single-host developer stack (§12.1). */
export const DEFAULT_CONCURRENCY = 2;

export interface QueueWorkerDeps {
  readonly connection: Redis;
  readonly registry: HandlerRegistry;
  readonly history: JobHistoryRecorder;
  readonly logger: AppLogger;
  readonly concurrency?: number;
}

export function createQueueWorker(queue: QueueName, deps: QueueWorkerDeps): Worker {
  const worker = new Worker(
    queue,
    async (job: Job) => processJob(queue, job, deps),
    {
      connection: deps.connection,
      concurrency: deps.concurrency ?? DEFAULT_CONCURRENCY,
    },
  );

  worker.on("failed", (job, error) => {
    deps.logger.error(
      {
        queue,
        jobName: job?.name,
        bullJobId: job?.id,
        attemptsMade: job?.attemptsMade,
        error: error.name,
      },
      "job failed; it is retained and rerunnable",
    );
  });

  worker.on("error", (error) => {
    deps.logger.error({ queue, error: error.name }, "worker error");
  });

  return worker;
}

export async function processJob(queue: QueueName, job: Job, deps: QueueWorkerDeps): Promise<unknown> {
  const bullJobId = String(job.id ?? "unknown");
  const correlationId = correlationIdOf(job, bullJobId);
  const attempt = job.attemptsMade + 1;
  const entry = deps.registry[job.name];

  if (!entry) {
    // An unknown job name is a real failure, recorded and retained — never a silent drop.
    const record = await deps.history.begin({
      jobName: job.name,
      queue,
      bullJobId,
      schedulerId: job.repeatJobKey ?? null,
      attempt,
    });
    const error = new Error(`no handler registered for job '${job.name}'`);
    await deps.history.fail(record.id, record.startedAt, error, "FAILED");
    throw error;
  }

  const record = await deps.history.begin({
    jobName: job.name,
    queue,
    bullJobId,
    // Set by BullMQ for occurrences produced by a Job Scheduler — makes ET-4 queryable.
    schedulerId: job.repeatJobKey ?? null,
    attempt,
  });

  const logger = deps.logger.child({ queue, jobName: job.name, bullJobId, attempt, correlationId });
  logger.debug({}, "job started");

  try {
    const result = await withDeadline(
      entry.handler({
        jobName: job.name,
        queue,
        bullJobId,
        attempt,
        correlationId,
        data: job.data,
        logger,
      }),
      entry.timeoutMs,
      job.name,
    );
    await deps.history.complete(record.id, record.startedAt, result);
    logger.debug({}, "job completed");
    return result;
  } catch (error) {
    const timedOut = error instanceof DeadlineExceededError;
    await deps.history.fail(record.id, record.startedAt, error, timedOut ? "TIMED_OUT" : "FAILED");
    // Rethrow: BullMQ owns retry/backoff and retention (FR-081).
    throw error;
  }
}

/**
 * A handler-level deadline. The timer CANCELS work; it never schedules any, so it is not the
 * `setTimeout`-as-scheduling anti-pattern ET-4 4.10 prohibits.
 */
export async function withDeadline<T>(work: Promise<T>, timeoutMs: number, label: string): Promise<T> {
  let timer: ReturnType<typeof setTimeout> | undefined;
  const deadline = new Promise<never>((_resolve, reject) => {
    timer = setTimeout(
      () => reject(new DeadlineExceededError(`job '${label}' exceeded its ${timeoutMs}ms deadline`)),
      timeoutMs,
    );
  });

  try {
    return await Promise.race([work, deadline]);
  } finally {
    if (timer) clearTimeout(timer);
  }
}

function correlationIdOf(job: Job, fallbackId: string): string {
  const data = job.data as { correlationId?: unknown } | null | undefined;
  return typeof data?.correlationId === "string" && data.correlationId.length > 0
    ? data.correlationId
    : `job:${job.name}:${fallbackId}`;
}

/**
 * `STALLED` is reported by BullMQ out of band (the worker died mid-job and its lock expired),
 * so it cannot be recorded by the processor itself.
 */
export function createStalledBackstop(
  queue: QueueName,
  deps: { connection: Redis; history: JobHistoryRecorder; logger: AppLogger },
): QueueEvents {
  const events = new QueueEvents(queue, { connection: deps.connection.duplicate() });

  events.on("stalled", ({ jobId }) => {
    void deps.history
      .markStalled(jobId)
      .then((closed) => {
        if (closed > 0) {
          deps.logger.warn({ queue, bullJobId: jobId, closed }, "job stalled; history row closed as STALLED");
        }
      })
      .catch((error: unknown) => {
        deps.logger.error(
          { queue, bullJobId: jobId, error: error instanceof Error ? error.name : "unknown" },
          "could not record a stalled job",
        );
      });
  });

  events.on("error", (error) => {
    deps.logger.error({ queue, error: error.name }, "queue events error");
  });

  return events;
}
