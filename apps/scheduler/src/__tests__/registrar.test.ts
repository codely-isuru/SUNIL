/**
 * ADR-010 / FR-082 — repeatable-job identity, against a REAL Redis.
 *
 * Skipped unless `SUNIL_TEST_REDIS_URL` points at one, so `pnpm test` stays green on a machine
 * with no containers (FR-003). The acceptance run sets it.
 *
 * Run locally:
 *   docker run -d --name sunil-t4-redis -p 56380:6379 -v sunil-t4-redisdata:/data \
 *     redis:7.4-alpine redis-server --appendonly yes --appendfsync everysec \
 *     --maxmemory-policy noeviction
 *   SUNIL_TEST_REDIS_URL=redis://127.0.0.1:56380 pnpm --filter @sunil/scheduler test
 */
import { readFileSync, readdirSync, statSync } from "node:fs";
import { join } from "node:path";
import { afterAll, beforeAll, describe, expect, it } from "vitest";
import { Queue } from "bullmq";
import { Redis } from "ioredis";
import {
  ALL_SCHEDULER_IDS,
  QUEUE_NAMES,
  REPEATABLE_DEFINITIONS,
  SCHEDULER_IDS,
  type RepeatableDefinition,
} from "@sunil/core";
import { CODE_DEFINED_SCHEDULER_IDS, queuesWithDefinitions, registerSchedulers } from "../registrar.js";

const REDIS_URL = process.env["SUNIL_TEST_REDIS_URL"];
const describeRedis = REDIS_URL ? describe : describe.skip;

describe("code-defined identity (no broker needed)", () => {
  it("registers exactly the two Phase 1 scheduler ids from @sunil/core", () => {
    expect(CODE_DEFINED_SCHEDULER_IDS).toEqual([...ALL_SCHEDULER_IDS]);
    expect(ALL_SCHEDULER_IDS).toEqual([
      SCHEDULER_IDS.sessionSweep,
      SCHEDULER_IDS.agentStalenessSweep,
    ]);
  });

  it("puts every Phase 1 repeatable on the `system` queue", () => {
    expect(queuesWithDefinitions()).toEqual([QUEUE_NAMES.system]);
  });

  it("never uses the banned legacy `repeat` option anywhere in this app (§18.3)", () => {
    const srcRoot = join(process.cwd(), "src");
    const files: string[] = [];
    const walk = (dir: string): void => {
      for (const entry of readdirSync(dir)) {
        const full = join(dir, entry);
        if (statSync(full).isDirectory()) walk(full);
        else if (entry.endsWith(".ts")) files.push(full);
      }
    };
    walk(srcRoot);

    const offenders = files.filter((file) => {
      const source = readFileSync(file, "utf8").replace(/\/\*[\s\S]*?\*\//g, "");
      // A `repeat:` job option — the option-derived key that silently duplicates definitions.
      return /\brepeat\s*:\s*\{/.test(source);
    });
    expect(offenders).toEqual([]);
  });
});

describeRedis("upsertJobScheduler against real Redis", () => {
  const connection = new Redis(REDIS_URL ?? "", { maxRetriesPerRequest: null });
  const queue = new Queue(QUEUE_NAMES.system, { connection });

  const shorten = (everyMs: number): RepeatableDefinition[] =>
    REPEATABLE_DEFINITIONS.map((definition) => ({ ...definition, everyMs }));

  beforeAll(async () => {
    await queue.obliterate({ force: true });
  });

  afterAll(async () => {
    for (const id of ALL_SCHEDULER_IDS) await queue.removeJobScheduler(id);
    await queue.obliterate({ force: true });
    await queue.close();
    await connection.quit();
  });

  it("creates one definition per code-defined id", async () => {
    const summary = await registerSchedulers(queue, shorten(60_000));

    expect(summary.registered).toEqual([...ALL_SCHEDULER_IDS]);
    expect(await queue.getJobSchedulersCount()).toBe(2);
    expect((await queue.getJobSchedulers()).map((scheduler) => scheduler.key).sort()).toEqual(
      [...ALL_SCHEDULER_IDS].sort(),
    );
  });

  it("is idempotent: re-registering does NOT create a second definition (ET-4 4.7)", async () => {
    await registerSchedulers(queue, shorten(60_000));
    await registerSchedulers(queue, shorten(60_000));

    expect(await queue.getJobSchedulersCount()).toBe(2);
  });

  it("UPDATES a definition in place when the interval changes, instead of duplicating it", async () => {
    // This is precisely what the legacy `repeat` option gets wrong: its key is derived from
    // the options, so a changed interval yields a SECOND definition.
    await registerSchedulers(queue, shorten(45_000));
    const changed = await queue.getJobSchedulers();

    expect(await queue.getJobSchedulersCount()).toBe(2);
    expect(changed.map((scheduler) => Number(scheduler.every))).toEqual([45_000, 45_000]);
  });

  it("reconciles away an id that is no longer defined in code (ADR-010 consequence)", async () => {
    await queue.upsertJobScheduler(
      "system:removed-in-a-later-release",
      { every: 60_000 },
      { name: "session-sweep" },
    );
    expect(await queue.getJobSchedulersCount()).toBe(3);

    const summary = await registerSchedulers(queue, shorten(60_000));

    expect(summary.removed).toEqual(["system:removed-in-a-later-release"]);
    expect(await queue.getJobSchedulersCount()).toBe(2);
  });
});
