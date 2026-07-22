/**
 * Repeatable-job registration and reconciliation (§12.3, ADR-010).
 *
 * `queue.upsertJobScheduler(schedulerId, repeatOpts, template)` with STABLE, CODE-DEFINED ids
 * from `@sunil/core`. Identity is the id, never a hash of the options:
 *
 *   • restart              ⇒ same id ⇒ ONE definition (ET-4 4.7)
 *   • interval changed     ⇒ the SAME definition is updated in place, not duplicated
 *   • id removed from code ⇒ the orphan definition in Redis is reconciled away
 *
 * The legacy `repeat` option is BANNED (§18.3): its repeat keys are derived from the options,
 * so changing a cron string or timezone silently creates a SECOND definition. An ESLint fence
 * in this app makes a `repeat:` job option a lint error — `registrar.test.ts` proves the fence
 * fires, and this file never uses it.
 */
import type { Queue } from "bullmq";
import {
  ALL_SCHEDULER_IDS,
  DEFAULT_JOB_OPTIONS,
  REPEATABLE_DEFINITIONS,
  type QueueName,
  type RepeatableDefinition,
} from "@sunil/core";

export interface RegistrationSummary {
  readonly queue: QueueName;
  /** Scheduler ids upserted on this boot. */
  readonly registered: readonly string[];
  /** Orphan scheduler ids removed because they are no longer defined in code. */
  readonly removed: readonly string[];
  /** Definitions present in Redis after reconciliation. */
  readonly definitions: readonly { id: string; everyMs: number | undefined; next: number | undefined }[];
}

export interface RegistrarLogger {
  info(context: Record<string, unknown>, message: string): void;
  warn(context: Record<string, unknown>, message: string): void;
}

/**
 * Upsert every definition belonging to `queue`, then remove any Job Scheduler on that queue
 * whose id is not in the code-defined set.
 *
 * `definitions` is a parameter so a durability test can drive the SAME stable ids at a shorter
 * interval — which is itself the ADR-010 property under test: the interval is an option, the
 * id is the identity.
 */
export async function registerSchedulers(
  queue: Queue,
  definitions: readonly RepeatableDefinition[] = REPEATABLE_DEFINITIONS,
  logger?: RegistrarLogger,
): Promise<RegistrationSummary> {
  const queueName = queue.name as QueueName;
  const mine = definitions.filter((definition) => definition.queue === queueName);

  for (const definition of mine) {
    await queue.upsertJobScheduler(
      definition.schedulerId,
      { every: definition.everyMs },
      {
        name: definition.jobName,
        data: { schedulerId: definition.schedulerId },
        opts: { ...DEFAULT_JOB_OPTIONS },
      },
    );
    logger?.info(
      { schedulerId: definition.schedulerId, jobName: definition.jobName, everyMs: definition.everyMs },
      "job scheduler upserted (idempotent by id)",
    );
  }

  // Reconciliation: an id removed from code leaves an orphan definition in Redis (ADR-010
  // consequence), so the boot sequence removes anything not defined here.
  const known = new Set<string>(definitions.map((definition) => definition.schedulerId));
  const existing = await queue.getJobSchedulers();
  const removed: string[] = [];

  for (const scheduler of existing) {
    if (!known.has(scheduler.key)) {
      await queue.removeJobScheduler(scheduler.key);
      removed.push(scheduler.key);
      logger?.warn(
        { schedulerId: scheduler.key, queue: queueName },
        "orphan job scheduler removed: its id is no longer defined in code",
      );
    }
  }

  const after = await queue.getJobSchedulers();
  return {
    queue: queueName,
    registered: mine.map((definition) => definition.schedulerId),
    removed,
    definitions: after.map((scheduler) => ({
      id: scheduler.key,
      everyMs: scheduler.every === undefined ? undefined : Number(scheduler.every),
      next: scheduler.next,
    })),
  };
}

/** The queues that carry at least one repeatable definition. */
export function queuesWithDefinitions(
  definitions: readonly RepeatableDefinition[] = REPEATABLE_DEFINITIONS,
): readonly QueueName[] {
  return [...new Set(definitions.map((definition) => definition.queue))];
}

/** Every scheduler id Phase 1 defines — the reconciliation allowlist. */
export const CODE_DEFINED_SCHEDULER_IDS: readonly string[] = ALL_SCHEDULER_IDS;
