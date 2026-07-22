/**
 * `@sunil/scheduler` — the thin producer (§12.3, ADR-010, FR-082).
 *
 * Its ENTIRE job: on boot, upsert the Job Schedulers defined in `@sunil/core` with their
 * stable ids, reconcile away orphans, audit the result, then IDLE.
 *
 * It consumes nothing: no `Worker` is ever constructed here — `main.test.ts` asserts that from
 * the source. It holds no schedule in memory: the definitions live in Redis, so the worker
 * keeps executing due occurrences while this process is stopped (FR-082, ET-4 4.6).
 *
 * Idling is deliberate and timer-free: the process stays alive because the ioredis socket is a
 * referenced handle, NOT because of a `setInterval` keep-alive (ET-4 4.10).
 */
import { Queue } from "bullmq";
import { Redis } from "ioredis";
import pino, { type Logger } from "pino";
import {
  ALL_SCHEDULER_IDS,
  CoreEnvSchema,
  PINO_REDACT_PATHS,
  REDACTED,
  REPEATABLE_DEFINITIONS,
  parseEnv,
  type AuditEntry,
  type RepeatableDefinition,
} from "@sunil/core";
import { AuditService, UnitOfWork, createPrismaClient } from "@sunil/db";
import { queuesWithDefinitions, registerSchedulers, type RegistrationSummary } from "./registrar.js";

/** The scheduler touches no secret material, so it composes the env subset it needs (§16). */
export const SchedulerEnvSchema = CoreEnvSchema.pick({
  DATABASE_URL: true,
  REDIS_URL: true,
  SUNIL_TIMEZONE: true,
});

/** Kept from the scaffold: the smoke check that env parsing and the definitions agree. */
export function prepareSchedulerBootstrap(env: NodeJS.ProcessEnv = process.env): {
  schedulerIds: readonly string[];
  definitions: number;
} {
  parseEnv(CoreEnvSchema, env);
  return { schedulerIds: ALL_SCHEDULER_IDS, definitions: REPEATABLE_DEFINITIONS.length };
}

export function createSchedulerLogger(level: pino.LevelWithSilent = "info"): Logger {
  return pino({
    name: "scheduler",
    level,
    redact: { paths: [...new Set(PINO_REDACT_PATHS)], censor: REDACTED },
    base: { service: "scheduler" },
  });
}

export interface SchedulerHandle {
  readonly summaries: readonly RegistrationSummary[];
  shutdown(signal?: string): Promise<void>;
}

export async function startScheduler(
  options: {
    env?: NodeJS.ProcessEnv;
    definitions?: readonly RepeatableDefinition[];
    logLevel?: pino.LevelWithSilent;
  } = {},
): Promise<SchedulerHandle> {
  const logger = createSchedulerLogger(options.logLevel ?? "info");
  const env = parseEnv(SchedulerEnvSchema, options.env ?? process.env);
  const definitions = options.definitions ?? REPEATABLE_DEFINITIONS;

  const connection = new Redis(env.REDIS_URL, {
    maxRetriesPerRequest: null,
    retryStrategy: (attempt) => {
      const delay = Math.min(attempt * 500, 5000);
      logger.warn({ attempt, delayMs: delay }, "redis unavailable; retrying registration with backoff");
      return delay;
    },
  });
  connection.on("error", (error: Error) => logger.error({ error: error.name }, "redis connection error"));

  const queues = queuesWithDefinitions(definitions).map(
    (name) => new Queue(name, { connection }),
  );

  const summaries: RegistrationSummary[] = [];
  for (const queue of queues) {
    summaries.push(await registerSchedulers(queue, definitions, logger));
  }

  await auditRegistration(env.DATABASE_URL, summaries, logger);

  logger.info(
    {
      registered: summaries.flatMap((summary) => summary.registered),
      removed: summaries.flatMap((summary) => summary.removed),
    },
    "job schedulers registered; the scheduler is now idle and consumes nothing",
  );

  let closed = false;
  const shutdown = async (signal = "manual"): Promise<void> => {
    if (closed) return;
    closed = true;
    logger.info({ signal }, "scheduler shutting down; definitions remain in redis");
    await Promise.allSettled(queues.map((queue) => queue.close()));
    await Promise.allSettled([connection.quit()]);
  };

  return { summaries, shutdown };
}

/**
 * ADR-010 requires reconciliation to be logged AND audited. The Redis-side change is the
 * mutation; the audit row is its record, written through `UnitOfWork.runAudited` like every
 * other security-relevant change.
 *
 * DEVIATION (reported, not silently taken): `AUDIT_ACTIONS` in `@sunil/core` has no
 * `scheduler.*` verb, and this task may not edit `@sunil/core`. `system.bootstrap` is used
 * with `targetType: 'job_scheduler'`, which is accurate — this IS the scheduler's boot
 * sequence — but a dedicated verb would be better and is reported to the architect.
 */
async function auditRegistration(
  databaseUrl: string,
  summaries: readonly RegistrationSummary[],
  logger: Logger,
): Promise<void> {
  const prisma = createPrismaClient({ datasourceUrl: databaseUrl });
  try {
    const audit = new AuditService(prisma, {
      fatal: (context, message) => logger.fatal(context, message),
    });
    const uow = new UnitOfWork(prisma, audit);

    const entry: AuditEntry = {
      actorType: "SYSTEM",
      actorId: null,
      actorLabel: "system:scheduler",
      action: "system.bootstrap",
      targetType: "job_scheduler",
      targetId: null,
      after: {
        registered: summaries.flatMap((summary) => summary.registered),
        removed: summaries.flatMap((summary) => summary.removed),
        definitions: summaries.flatMap((summary) => summary.definitions.map((d) => d.id)),
      },
      outcome: "SUCCESS",
      correlationId: `scheduler-boot:${new Date().toISOString()}`,
    };

    await uow.runAudited(entry, () => Promise.resolve(summaries.length));
  } finally {
    await prisma.$disconnect();
  }
}

async function main(): Promise<void> {
  const handle = await startScheduler();

  for (const signal of ["SIGTERM", "SIGINT"] as const) {
    process.once(signal, () => {
      void handle.shutdown(signal).then(() => process.exit(0));
    });
  }
}

if (process.argv[1] && /main\.(js|ts)$/.test(process.argv[1])) {
  main().catch((error: unknown) => {
    const logger = createSchedulerLogger();
    logger.fatal(
      {
        error: error instanceof Error ? error.name : "unknown",
        message: error instanceof Error ? error.message : "",
      },
      "scheduler failed to start",
    );
    process.exit(1);
  });
}
