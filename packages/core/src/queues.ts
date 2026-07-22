/**
 * Queue topology and repeatable-job identity (§12, ADR-010).
 *
 * Warning §18.3: the legacy BullMQ `repeat` option is BANNED in this codebase. Repeatable
 * work is registered with `queue.upsertJobScheduler(<stable id>, …)` using the ids below.
 * Option-derived repeat keys silently duplicate a definition when an option changes; a
 * stable, code-defined id cannot.
 */

/**
 * Phase 1 creates exactly two queues (deviation D-3). `integrations:sync`, `workflows`,
 * `notifications` and `briefs` are added by the phase that consumes them.
 */
export const QUEUE_NAMES = {
  system: "system",
  agents: "agents",
} as const;

export type QueueName = (typeof QUEUE_NAMES)[keyof typeof QUEUE_NAMES];

export const ALL_QUEUE_NAMES: readonly QueueName[] = [QUEUE_NAMES.system, QUEUE_NAMES.agents];

/** Stable Job Scheduler ids. Identity is this string — never a hash of the options. */
export const SCHEDULER_IDS = {
  sessionSweep: "system:session-sweep",
  agentStalenessSweep: "system:agent-staleness-sweep",
} as const;

export type SchedulerId = (typeof SCHEDULER_IDS)[keyof typeof SCHEDULER_IDS];

export const ALL_SCHEDULER_IDS: readonly SchedulerId[] = [
  SCHEDULER_IDS.sessionSweep,
  SCHEDULER_IDS.agentStalenessSweep,
];

export const JOB_NAMES = {
  sessionSweep: "session-sweep",
  agentStalenessSweep: "agent-staleness-sweep",
  agentRun: "agent-run",
} as const;

export type JobName = (typeof JOB_NAMES)[keyof typeof JOB_NAMES];

export const JOB_OUTCOMES = [
  "RUNNING",
  "COMPLETED",
  "FAILED",
  "TIMED_OUT",
  "STALLED",
] as const;

/**
 * Default job options for both queues (§12.1). Failed jobs are RETAINED so they stay
 * visible and rerunnable (FR-081) — do not add `removeOnFail`.
 */
export const DEFAULT_JOB_OPTIONS = {
  attempts: 3,
  backoff: { type: "exponential" as const, delay: 5000 },
  removeOnComplete: { age: 24 * 3600, count: 1000 },
  removeOnFail: false as const,
};

/**
 * Repeatable definitions, in code. The scheduler upserts exactly this set on boot and
 * reconciles away any scheduler id no longer present here (ADR-010 consequence).
 */
export interface RepeatableDefinition {
  readonly schedulerId: SchedulerId;
  readonly queue: QueueName;
  readonly jobName: JobName;
  readonly everyMs: number;
}

export const REPEATABLE_DEFINITIONS: readonly RepeatableDefinition[] = [
  {
    schedulerId: SCHEDULER_IDS.sessionSweep,
    queue: QUEUE_NAMES.system,
    jobName: JOB_NAMES.sessionSweep,
    everyMs: 5 * 60_000,
  },
  {
    schedulerId: SCHEDULER_IDS.agentStalenessSweep,
    queue: QUEUE_NAMES.system,
    jobName: JOB_NAMES.agentStalenessSweep,
    everyMs: 60_000,
  },
];
