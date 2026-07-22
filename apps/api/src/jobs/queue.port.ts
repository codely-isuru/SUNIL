/**
 * The API's view of the queues (§12.5).
 *
 * `apps/api` is a PRODUCER and an observer only: it enqueues an agent run and reports queue
 * counts. Processing lives in `apps/worker` and schedule registration in `apps/scheduler`;
 * nothing here consumes a job.
 *
 * Warning §18.3 applies to whoever extends this: repeatable work is registered with
 * `upsertJobScheduler` and a stable id, never the legacy `repeat` option — and that
 * registration belongs to the scheduler app, not to this one.
 */
export interface QueueCounts {
  readonly queue: string;
  readonly waiting: number;
  readonly active: number;
  readonly completed: number;
  readonly failed: number;
  readonly delayed: number;
}

export interface SchedulerSummary {
  readonly id: string;
  readonly name: string | null;
  readonly every: number | null;
  readonly next: number | null;
}

export interface QueueStatus {
  readonly queues: readonly QueueCounts[];
  readonly schedulers: readonly SchedulerSummary[];
}

export interface QueuePort {
  enqueueAgentRun(args: {
    agentId: string;
    taskId: string;
    correlationId: string;
  }): Promise<{ jobId: string }>;
  status(): Promise<QueueStatus>;
  ping(): Promise<boolean>;
  close(): Promise<void>;
}
