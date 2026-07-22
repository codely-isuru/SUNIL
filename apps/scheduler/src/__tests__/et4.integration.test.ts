/**
 * ET-4 — "queue survives restart". The exit test this task exists to make PROVABLE.
 *
 * Risk R-04 states the danger plainly: a mocked or in-process "restart" would pass ET-4 while
 * the real system loses jobs. So nothing here is simulated:
 *
 *   • the WORKER is a real child process (`node apps/worker/dist/main.js`), stopped with a
 *     real SIGTERM and started again;
 *   • REDIS is a real container, stopped and started with `docker stop` / `docker start`
 *     (container id and timestamps are printed as evidence);
 *   • POSTGRES is a real container, restarted for step 4.9;
 *   • the delayed one-off job becomes due DURING the outage window;
 *   • the negative control (4.7) re-registers, and then re-registers with a CHANGED INTERVAL —
 *     the exact case the banned legacy `repeat` option gets wrong.
 *
 * Gated on the three env vars below so `pnpm test` stays green without containers (FR-003):
 *   SUNIL_TEST_REDIS_URL, SUNIL_TEST_DATABASE_URL, SUNIL_TEST_REDIS_CONTAINER
 *   (optional: SUNIL_TEST_POSTGRES_CONTAINER enables step 4.9)
 *
 * The repeatable definitions used here carry the REAL stable scheduler ids from `@sunil/core`
 * at a shortened interval. That is not a shortcut — under ADR-010 the id IS the identity and
 * the interval is just an option, which is what step 4.7b then exploits.
 */
import { execFileSync } from "node:child_process";
import { spawn, type ChildProcess } from "node:child_process";
import { randomUUID } from "node:crypto";
import { join, resolve } from "node:path";
import { afterAll, beforeAll, describe, expect, it } from "vitest";
import { Queue } from "bullmq";
import { Redis } from "ioredis";
import {
  ALL_SCHEDULER_IDS,
  DEFAULT_JOB_OPTIONS,
  JOB_NAMES,
  QUEUE_NAMES,
  REPEATABLE_DEFINITIONS,
  SCHEDULER_IDS,
  type RepeatableDefinition,
} from "@sunil/core";
import { createPrismaClient } from "@sunil/db";
import { registerSchedulers } from "../registrar.js";

const REDIS_URL = process.env["SUNIL_TEST_REDIS_URL"];
const DATABASE_URL = process.env["SUNIL_TEST_DATABASE_URL"];
const REDIS_CONTAINER = process.env["SUNIL_TEST_REDIS_CONTAINER"];
const POSTGRES_CONTAINER = process.env["SUNIL_TEST_POSTGRES_CONTAINER"];

const enabled = Boolean(REDIS_URL && DATABASE_URL && REDIS_CONTAINER);
const describeEt4 = enabled ? describe : describe.skip;

/** Short enough to observe several occurrences; the ids are the real ones. */
const EVERY_MS = 2_000;
const DELAYED_JOB_DELAY_MS = 18_000;
const OUTAGE_MS = 22_000;

const evidence: string[] = [];

function record(line: string): void {
  evidence.push(`[${new Date().toISOString()}] ${line}`);
}

function docker(...args: string[]): string {
  const out = execFileSync("docker", args, { encoding: "utf8" }).trim();
  record(`docker ${args.join(" ")} -> ${out.split("\n")[0] ?? ""}`);
  return out;
}

async function waitFor<T>(
  what: string,
  probe: () => Promise<T | undefined>,
  timeoutMs: number,
  intervalMs = 500,
): Promise<T> {
  const deadline = Date.now() + timeoutMs;
  let last: unknown;
  while (Date.now() < deadline) {
    try {
      const value = await probe();
      if (value !== undefined && value !== null && value !== false) return value;
    } catch (error) {
      last = error;
    }
    await new Promise((r) => setTimeout(r, intervalMs));
  }
  throw new Error(`timed out waiting for ${what}${last ? ` (last error: ${String(last)})` : ""}`);
}

describeEt4("ET-4 — queue survives a REAL restart", () => {
  const repoRoot = resolve(process.cwd(), "..", "..");
  const workerEntry = join(repoRoot, "apps", "worker", "dist", "main.js");
  const workerEnv = {
    ...process.env,
    DATABASE_URL: DATABASE_URL ?? "",
    REDIS_URL: REDIS_URL ?? "",
    // A throwaway 32-byte key: this database holds fixtures only and no secret is stored.
    SUNIL_MASTER_KEY: Buffer.alloc(32, 7).toString("base64"),
  } as NodeJS.ProcessEnv;

  const shortDefinitions: RepeatableDefinition[] = REPEATABLE_DEFINITIONS.map((definition) => ({
    ...definition,
    everyMs: EVERY_MS,
  }));

  let connection: Redis;
  let queue: Queue;
  let prisma: ReturnType<typeof createPrismaClient>;
  let worker: ChildProcess | undefined;

  const startWorkerProcess = async (label: string): Promise<void> => {
    worker = spawn(process.execPath, [workerEntry], { env: workerEnv, stdio: "ignore" });
    record(`worker process started (${label}) pid=${worker.pid ?? "?"}`);
    await new Promise((r) => setTimeout(r, 1500));
  };

  const stopWorkerProcess = async (): Promise<void> => {
    if (!worker) return;
    const pid = worker.pid;
    const exited = new Promise<void>((resolveExit) => worker?.once("exit", () => resolveExit()));
    worker.kill("SIGTERM");
    await Promise.race([exited, new Promise((r) => setTimeout(r, 8000))]);
    if (worker.exitCode === null && worker.signalCode === null) worker.kill("SIGKILL");
    record(`worker process stopped pid=${pid ?? "?"} exitCode=${worker.exitCode ?? "signal"}`);
    worker = undefined;
  };

  /**
   * Every count is scoped to this run's window. The database is long-lived and carries rows
   * from earlier runs; counting those would let the test pass on history it did not create.
   */
  let testStart = new Date();

  const countExecutions = async (schedulerId: string, since: Date = testStart): Promise<number> =>
    prisma.jobExecution.count({ where: { schedulerId, startedAt: { gte: since } } });

  beforeAll(async () => {
    connection = new Redis(REDIS_URL ?? "", { maxRetriesPerRequest: null });
    queue = new Queue(QUEUE_NAMES.system, { connection });
    prisma = createPrismaClient({ datasourceUrl: DATABASE_URL ?? "" });
    await queue.obliterate({ force: true });
    record("queue obliterated; starting from a clean slate");
  }, 60_000);

  afterAll(async () => {
    await stopWorkerProcess();
    try {
      for (const id of ALL_SCHEDULER_IDS) await queue.removeJobScheduler(id);
      await queue.obliterate({ force: true });
    } catch {
      /* best effort */
    }
    await queue.close();
    await connection.quit();
    await prisma.$disconnect();
    // The evidence trail is printed so the QA reviewer can see the real container operations.
    console.log(["", "── ET-4 evidence ──", ...evidence, "───────────────────"].join("\n"));
  }, 60_000);

  it(
    "runs the whole ET-4 sequence against real containers",
    async () => {
      // ── 4.1 register repeatables and observe ≥2 executions ────────────────────────────
      const registered = await registerSchedulers(queue, shortDefinitions);
      expect(registered.registered).toEqual([...ALL_SCHEDULER_IDS]);
      record(`registered schedulers: ${registered.registered.join(", ")}`);

      testStart = new Date();
      await startWorkerProcess("pre-outage");

      const staleness = SCHEDULER_IDS.agentStalenessSweep;
      await waitFor(
        "≥2 pre-restart executions of the repeatable",
        async () => ((await countExecutions(staleness)) >= 2 ? true : undefined),
        45_000,
      );
      const preRestartCount = await countExecutions(staleness);
      expect(preRestartCount).toBeGreaterThanOrEqual(2);
      record(`pre-outage executions of ${staleness}: ${preRestartCount}`);

      const schedulersBefore = await queue.getJobSchedulers();
      const iterationsBefore = Number(
        schedulersBefore.find((scheduler) => scheduler.key === staleness)?.iterationCount ?? 0,
      );
      expect(iterationsBefore).toBeGreaterThanOrEqual(2);

      // ── 4.2 enqueue a delayed one-off job that becomes due DURING the outage ───────────
      const delayedCorrelationId = `et4-delayed-${randomUUID()}`;
      const delayedJob = await queue.add(
        JOB_NAMES.sessionSweep,
        { correlationId: delayedCorrelationId },
        { ...DEFAULT_JOB_OPTIONS, delay: DELAYED_JOB_DELAY_MS },
      );
      const delayedJobId = String(delayedJob.id);
      expect(await queue.getDelayedCount()).toBeGreaterThanOrEqual(1);
      expect(await delayedJob.getState()).toBe("delayed");
      record(`delayed job ${delayedJobId} enqueued, due in ${DELAYED_JOB_DELAY_MS}ms`);

      // ── 4.3 REAL stop: worker process, then the Redis container ───────────────────────
      await stopWorkerProcess();
      const redisIdBefore = docker("inspect", "-f", "{{.Id}} {{.State.StartedAt}}", REDIS_CONTAINER ?? "");
      docker("stop", REDIS_CONTAINER ?? "");
      const stateStopped = docker("inspect", "-f", "{{.State.Status}}", REDIS_CONTAINER ?? "");
      expect(stateStopped).toBe("exited");

      // ── 4.4 wait past the delayed due time and past several repeatable intervals ──────
      record(`outage window: ${OUTAGE_MS}ms with redis DOWN`);
      await new Promise((r) => setTimeout(r, OUTAGE_MS));

      // ── 4.5 start Redis again (same named volume, AOF on disk) ────────────────────────
      docker("start", REDIS_CONTAINER ?? "");
      const redisIdAfter = docker("inspect", "-f", "{{.Id}} {{.State.StartedAt}}", REDIS_CONTAINER ?? "");
      expect(redisIdAfter.split(" ")[0]).toBe(redisIdBefore.split(" ")[0]);
      expect(redisIdAfter).not.toBe(redisIdBefore); // a genuinely new start time
      expect(docker("inspect", "-f", "{{.State.Status}}", REDIS_CONTAINER ?? "")).toBe("running");

      const posture = docker(
        "exec",
        REDIS_CONTAINER ?? "",
        "redis-cli",
        "config",
        "get",
        "maxmemory-policy",
      );
      expect(posture).toContain("noeviction");

      // ── 4.6a the definitions survived, WITHOUT any re-registration ────────────────────
      const survivors = await waitFor(
        "job schedulers readable after the restart",
        async () => {
          const list = await queue.getJobSchedulers();
          return list.length > 0 ? list : undefined;
        },
        30_000,
      );
      expect(survivors.map((scheduler) => scheduler.key).sort()).toEqual([...ALL_SCHEDULER_IDS].sort());
      const iterationsAfter = Number(
        survivors.find((scheduler) => scheduler.key === staleness)?.iterationCount ?? 0,
      );
      // Not reset to zero: the SAME definition survived rather than being recreated.
      expect(iterationsAfter).toBeGreaterThanOrEqual(iterationsBefore);
      record(
        `definitions survived without re-registration; iterationCount ${iterationsBefore} -> ${iterationsAfter}`,
      );

      // The delayed job is still there — it survived in Redis (AOF on a named volume,
      // ADR-002) and is now overdue rather than lost. No worker is running yet.
      const delayedAfter = await queue.getJob(delayedJobId);
      expect(delayedAfter).toBeDefined();
      const delayedState = await delayedAfter?.getState();
      expect(["delayed", "waiting", "prioritized"]).toContain(delayedState);
      expect((await queue.getDelayedCount()) + (await queue.getWaitingCount())).toBeGreaterThanOrEqual(1);
      record(`delayed job survived the outage; state after restart: ${delayedState}`);

      // ── 4.6b restart the worker: the delayed job runs and new occurrences are recorded ─
      const afterRestartMark = new Date();
      await startWorkerProcess("post-outage");

      const delayedExecution = await waitFor(
        "the delayed one-off job to execute after the restart",
        async () => {
          const rows = await prisma.jobExecution.findMany({
            where: { bullJobId: delayedJobId, startedAt: { gte: afterRestartMark } },
          });
          return rows.length > 0 ? rows : undefined;
        },
        45_000,
      );
      expect(delayedExecution[0]?.outcome).toBe("COMPLETED");
      record(`delayed job ${delayedJobId} executed AFTER the restart — no occurrence lost`);

      await waitFor(
        "new repeatable executions after the restart",
        async () =>
          (await countExecutions(staleness, afterRestartMark)) >= 2 ? true : undefined,
        45_000,
      );
      record(
        `post-restart executions of ${staleness}: ${await countExecutions(staleness, afterRestartMark)}`,
      );

      // ── 4.7 NEGATIVE CONTROL: re-registration must not duplicate ──────────────────────
      await registerSchedulers(queue, shortDefinitions);
      await registerSchedulers(queue, shortDefinitions);
      expect(await queue.getJobSchedulersCount()).toBe(ALL_SCHEDULER_IDS.length);

      const afterReRegister = await queue.getJobSchedulers();
      const keys = afterReRegister.map((scheduler) => scheduler.key);
      expect(new Set(keys).size).toBe(keys.length); // exactly one definition per job key
      expect(keys.sort()).toEqual([...ALL_SCHEDULER_IDS].sort());

      // 4.7b the case the banned legacy `repeat` option gets wrong: a CHANGED interval.
      await registerSchedulers(
        queue,
        shortDefinitions.map((definition) => ({ ...definition, everyMs: 3_000 })),
      );
      const afterChange = await queue.getJobSchedulers();
      expect(afterChange).toHaveLength(ALL_SCHEDULER_IDS.length);
      expect(afterChange.every((scheduler) => Number(scheduler.every) === 3_000)).toBe(true);
      record(
        `negative control: ${afterChange.length} definitions after re-registration and an interval change (expected ${ALL_SCHEDULER_IDS.length})`,
      );

      // Redis itself agrees: one repeat-definition key per scheduler id.
      const repeatKeys = await connection.zrange(`bull:${QUEUE_NAMES.system}:repeat`, 0, -1);
      expect(repeatKeys.sort()).toEqual([...ALL_SCHEDULER_IDS].sort());

      // ── 4.8 pre-restart history is still present in Postgres ──────────────────────────
      const preserved = await prisma.jobExecution.count({
        where: { schedulerId: staleness, startedAt: { gte: testStart, lt: afterRestartMark } },
      });
      expect(preserved).toBeGreaterThanOrEqual(preRestartCount);
      record(`pre-restart history rows still readable: ${preserved}`);

      // ── 4.9 restart the WHOLE stack (volumes retained) ────────────────────────────────
      if (POSTGRES_CONTAINER) {
        await stopWorkerProcess();
        const totalBefore = await prisma.jobExecution.count();
        const auditBefore = await prisma.auditLog.count();
        await prisma.$disconnect();

        // A genuine stop → verify exited → start → verify ready. `docker restart` alone
        // returns before the service is actually down, which would let this step "pass"
        // without either container ever having stopped.
        docker("stop", POSTGRES_CONTAINER);
        docker("stop", REDIS_CONTAINER ?? "");
        expect(docker("inspect", "-f", "{{.State.Status}}", POSTGRES_CONTAINER)).toBe("exited");
        expect(docker("inspect", "-f", "{{.State.Status}}", REDIS_CONTAINER ?? "")).toBe("exited");

        docker("start", POSTGRES_CONTAINER);
        docker("start", REDIS_CONTAINER ?? "");
        await waitFor(
          "postgres to report ready after the full-stack restart",
          async () => {
            await Promise.resolve();
            try {
              return docker("exec", POSTGRES_CONTAINER, "pg_isready", "-U", "postgres").includes(
                "accepting connections",
              )
                ? true
                : undefined;
            } catch {
              return undefined;
            }
          },
          60_000,
          1000,
        );

        prisma = createPrismaClient({ datasourceUrl: DATABASE_URL ?? "" });
        const totalAfter = await waitFor(
          "postgres to accept connections after the restart",
          async () => {
            const count = await prisma.jobExecution.count();
            return count > 0 ? count : undefined;
          },
          60_000,
        );
        expect(totalAfter).toBe(totalBefore);
        expect(await prisma.auditLog.count()).toBe(auditBefore);
        record(`full-stack restart: ${totalAfter} execution rows and ${auditBefore} audit rows survived`);

        // And the schedule survived the Redis restart a second time.
        const finalSchedulers = await waitFor(
          "schedulers readable after the full-stack restart",
          async () => {
            const list = await queue.getJobSchedulers();
            return list.length > 0 ? list : undefined;
          },
          30_000,
        );
        expect(finalSchedulers).toHaveLength(ALL_SCHEDULER_IDS.length);
      }
    },
    240_000,
  );
});
