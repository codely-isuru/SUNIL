/**
 * Execution history in POSTGRES (§12.2, FR-083, ET-4 4.8).
 *
 * Redis holds the queue; Postgres holds the record. A `JobExecution` row is written when a job
 * STARTS (`RUNNING`) and updated when it finishes (`COMPLETED` / `FAILED` / `TIMED_OUT`), with
 * a `QueueEvents` listener backstopping `STALLED`. History therefore survives a `FLUSHALL`, a
 * lost Redis volume, or a full container rebuild.
 *
 * NOTE (deliberate, §5.7): `JobExecution` is NOT covered by the append-only client guard —
 * that guard protects `audit_logs`. The RUNNING → COMPLETED update below is legal by design.
 */
import { scrubString, type JobOutcome } from "@sunil/core";
import type { JobExecution, Prisma } from "@sunil/db";

export interface JobHistoryStore {
  start(data: Prisma.JobExecutionCreateInput): Promise<JobExecution>;
  finish(
    id: string,
    data: Pick<
      Prisma.JobExecutionUpdateInput,
      "outcome" | "finishedAt" | "durationMs" | "error" | "result"
    >,
  ): Promise<JobExecution>;
  findByBullJobId(bullJobId: string): Promise<JobExecution[]>;
}

export interface JobStartInfo {
  readonly jobName: string;
  readonly queue: string;
  readonly bullJobId: string;
  /** The Job Scheduler id when the occurrence came from a repeatable definition (ADR-010). */
  readonly schedulerId?: string | null;
  readonly attempt: number;
}

const MAX_ERROR = 4000;

export class JobHistoryRecorder {
  readonly #store: JobHistoryStore;
  readonly #now: () => number;

  constructor(store: JobHistoryStore, now: () => number = Date.now) {
    this.#store = store;
    this.#now = now;
  }

  async begin(info: JobStartInfo): Promise<{ id: string; startedAt: number }> {
    const startedAt = this.#now();
    const row = await this.#store.start({
      jobName: info.jobName,
      queue: info.queue,
      bullJobId: info.bullJobId,
      schedulerId: info.schedulerId ?? null,
      attempt: info.attempt,
      startedAt: new Date(startedAt),
      outcome: "RUNNING",
    });
    return { id: row.id, startedAt };
  }

  async complete(id: string, startedAt: number, result: unknown): Promise<void> {
    const finishedAt = this.#now();
    await this.#store.finish(id, {
      outcome: "COMPLETED",
      finishedAt: new Date(finishedAt),
      durationMs: finishedAt - startedAt,
      // Small results only; a large payload here is an anti-pattern (§5.7).
      result: (result === undefined || result === null
        ? undefined
        : (JSON.parse(JSON.stringify(result)) as Prisma.InputJsonValue)) as Prisma.InputJsonValue,
    });
  }

  async fail(
    id: string,
    startedAt: number,
    error: unknown,
    outcome: Extract<JobOutcome, "FAILED" | "TIMED_OUT" | "STALLED"> = "FAILED",
  ): Promise<void> {
    const finishedAt = this.#now();
    await this.#store.finish(id, {
      outcome,
      finishedAt: new Date(finishedAt),
      durationMs: finishedAt - startedAt,
      error: redactError(error),
    });
  }

  /**
   * Boot-time reconciliation of orphaned `RUNNING` rows.
   *
   * Observed for real during the ET-4 runs: if a worker is stopped in the instant between the
   * RUNNING insert and the finish update, the row stays RUNNING forever — the `QueueEvents`
   * stalled backstop only fires while some worker is alive to hear it. A row older than the
   * LONGEST handler deadline cannot still be legitimately running, so it is closed as
   * STALLED. The cutoff is what makes this safe with a second worker in flight.
   */
  async reconcileOrphans(rows: readonly JobExecution[]): Promise<number> {
    for (const row of rows) {
      const finishedAt = this.#now();
      await this.#store.finish(row.id, {
        outcome: "STALLED",
        finishedAt: new Date(finishedAt),
        durationMs: finishedAt - row.startedAt.getTime(),
        error: "execution abandoned: no worker finished it within the maximum handler deadline",
      });
    }
    return rows.length;
  }

  /** QueueEvents backstop: close out any RUNNING row for a job BullMQ reported as stalled. */
  async markStalled(bullJobId: string): Promise<number> {
    const rows = await this.#store.findByBullJobId(bullJobId);
    const running = rows.filter((row) => row.outcome === "RUNNING");
    for (const row of running) {
      const finishedAt = this.#now();
      await this.#store.finish(row.id, {
        outcome: "STALLED",
        finishedAt: new Date(finishedAt),
        durationMs: finishedAt - row.startedAt.getTime(),
        error: "job stalled: the worker stopped renewing its lock",
      });
    }
    return running.length;
  }
}

/** Errors are redacted before persist — a provider error body can echo a credential. */
export function redactError(error: unknown): string {
  const raw =
    error instanceof Error
      ? `${error.name}: ${error.message}`
      : typeof error === "string"
        ? error
        : "unknown error";
  return scrubString(raw).slice(0, MAX_ERROR);
}
