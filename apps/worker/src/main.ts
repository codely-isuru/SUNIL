/**
 * `@sunil/worker` — hosts the BullMQ processors for both Phase 1 queues. NO HTTP surface.
 *
 * Wiring only: queue names, job names and job options all come from `@sunil/core`; the
 * behaviour lives in `./processors`, `./worker.ts` and `@sunil/agents`.
 *
 * NON-NEGOTIABLES honoured here:
 *  - exactly two queues, `system` and `agents` (deviation D-3);
 *  - `JobExecution` rows in Postgres at start and finish (FR-083);
 *  - failed jobs retained, visible and rerunnable (FR-081);
 *  - security-relevant state changes go through `UnitOfWork.runAudited`;
 *  - no `setInterval`/`setTimeout` as a scheduling mechanism (ET-4 4.10);
 *  - `noeviction` on Redis is load-bearing and is asserted at boot, not assumed (§18.4).
 */
import {
  ALL_QUEUE_NAMES,
  CoreEnvSchema,
  JOB_NAMES,
  QUEUE_NAMES,
  parseEnv,
  type QueueName,
} from "@sunil/core";
import {
  AgentMessageRepository,
  AgentRepository,
  AuditService,
  JobExecutionRepository,
  SessionRepository,
  UnitOfWork,
  createPrismaClient,
} from "@sunil/db";
import { AgentRuntime, StaleAgentSweeper } from "@sunil/agents";
import { JobHistoryRecorder } from "./job-history.js";
import { createLogger, type AppLogger } from "./logger.js";
import { createRedisConnection, verifyPersistencePosture } from "./redis.js";
import { runAgentJob } from "./processors/agents.js";
import { runAgentStalenessSweep, runSessionSweep } from "./processors/system.js";
import {
  DEFAULT_CONCURRENCY,
  JOB_TIMEOUT_MS,
  createQueueWorker,
  createStalledBackstop,
  type HandlerRegistry,
} from "./worker.js";

/** Kept from the scaffold: the smoke check that env parsing and the queue list agree. */
export function prepareWorkerBootstrap(env: NodeJS.ProcessEnv = process.env): {
  queues: readonly string[];
} {
  parseEnv(CoreEnvSchema, env);
  return { queues: ALL_QUEUE_NAMES };
}

export interface WorkerHandle {
  readonly logger: AppLogger;
  shutdown(signal?: string): Promise<void>;
}

export async function startWorker(
  options: { env?: NodeJS.ProcessEnv; concurrency?: number; logLevel?: "info" | "debug" | "warn" | "error" | "silent" } = {},
): Promise<WorkerHandle> {
  const logger = createLogger("worker", options.logLevel ?? "info");
  const env = parseEnv(CoreEnvSchema, options.env ?? process.env);

  const prisma = createPrismaClient({ datasourceUrl: env.DATABASE_URL });
  const audit = new AuditService(prisma, {
    fatal: (context, message) => logger.fatal(context, message),
  });
  const uow = new UnitOfWork(prisma, audit);

  const agents = new AgentRepository(prisma);
  const messages = new AgentMessageRepository(prisma);
  const sessions = new SessionRepository(prisma);
  const jobs = new JobExecutionRepository(prisma);

  const runtime = new AgentRuntime({
    agents,
    messages,
    uow,
    db: prisma,
    logger: {
      debug: (context, message) => logger.debug(context, message),
      info: (context, message) => logger.info(context, message),
      warn: (context, message) => logger.warn(context, message),
      error: (context, message) => logger.error(context, message),
    },
  });
  const sweeper = new StaleAgentSweeper({ agents, emitter: runtime.emitter, uow });

  const connection = createRedisConnection(env.REDIS_URL, logger);
  await verifyPersistencePosture(connection, logger);

  const history = new JobHistoryRecorder(jobs);

  // Close out executions abandoned by a previous worker that died mid-job. Only rows older
  // than the longest handler deadline are touched, so a concurrent worker's in-flight job is
  // never mislabelled. (A `findRunningOlderThan` method on `JobExecutionRepository` would be a
  // better home for this query; `@sunil/db` is outside this task's ownership — reported.)
  const orphanCutoff = new Date(Date.now() - Math.max(...Object.values(JOB_TIMEOUT_MS)));
  const orphans = await prisma.jobExecution.findMany({
    where: { outcome: "RUNNING", startedAt: { lt: orphanCutoff } },
  });
  if (orphans.length > 0) {
    const closed = await history.reconcileOrphans(orphans);
    logger.warn(
      { closed, cutoff: orphanCutoff.toISOString() },
      "closed abandoned RUNNING job executions as STALLED at boot",
    );
  }

  const systemRegistry: HandlerRegistry = {
    [JOB_NAMES.sessionSweep]: {
      timeoutMs: JOB_TIMEOUT_MS[JOB_NAMES.sessionSweep] ?? 60_000,
      handler: (context) =>
        runSessionSweep({ prisma, sessions, uow, logger: context.logger }, context.correlationId),
    },
    [JOB_NAMES.agentStalenessSweep]: {
      timeoutMs: JOB_TIMEOUT_MS[JOB_NAMES.agentStalenessSweep] ?? 60_000,
      handler: (context) =>
        runAgentStalenessSweep({ sweeper, logger: context.logger }, context.correlationId),
    },
  };

  const agentRegistry: HandlerRegistry = {
    [JOB_NAMES.agentRun]: {
      timeoutMs: JOB_TIMEOUT_MS[JOB_NAMES.agentRun] ?? 900_000,
      handler: (context) => runAgentJob({ runtime, agents, logger: context.logger }, context.data),
    },
  };

  const registries: Record<QueueName, HandlerRegistry> = {
    [QUEUE_NAMES.system]: systemRegistry,
    [QUEUE_NAMES.agents]: agentRegistry,
  };

  const workers = ALL_QUEUE_NAMES.map((queue) =>
    createQueueWorker(queue, {
      connection,
      registry: registries[queue],
      history,
      logger,
      concurrency: options.concurrency ?? DEFAULT_CONCURRENCY,
    }),
  );

  const backstops = ALL_QUEUE_NAMES.map((queue) =>
    createStalledBackstop(queue, { connection, history, logger }),
  );

  logger.info(
    { queues: ALL_QUEUE_NAMES, concurrency: options.concurrency ?? DEFAULT_CONCURRENCY },
    "worker started",
  );

  let closed = false;
  const shutdown = async (signal = "manual"): Promise<void> => {
    if (closed) return;
    closed = true;
    logger.info({ signal }, "worker shutting down; active jobs will be allowed to finish");
    // `close()` waits for in-flight jobs, so nothing is abandoned mid-flight.
    await Promise.allSettled(workers.map((worker) => worker.close()));
    await Promise.allSettled(backstops.map((events) => events.close()));
    await Promise.allSettled([connection.quit(), prisma.$disconnect()]);
    logger.info({ signal }, "worker stopped");
  };

  return { logger, shutdown };
}

/** `node dist/main.js` entry point. */
async function main(): Promise<void> {
  const handle = await startWorker();

  for (const signal of ["SIGTERM", "SIGINT"] as const) {
    process.once(signal, () => {
      void handle.shutdown(signal).then(() => process.exit(0));
    });
  }
}

// Run only when executed directly, so tests can import `startWorker` without booting twice.
if (process.argv[1] && /main\.(js|ts)$/.test(process.argv[1])) {
  main().catch((error: unknown) => {
    const logger = createLogger("worker");
    logger.fatal(
      { error: error instanceof Error ? error.name : "unknown", message: error instanceof Error ? error.message : "" },
      "worker failed to start",
    );
    process.exit(1);
  });
}
