/**
 * Wiring invariants for the worker app that are cheaper to assert than to review.
 */
import { readFileSync, readdirSync, statSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import { ALL_QUEUE_NAMES, JOB_NAMES, QUEUE_NAMES } from "@sunil/core";
import { DEFAULT_CONCURRENCY, JOB_TIMEOUT_MS } from "../worker.js";
import { noWorkloadStepFactory } from "../processors/agents.js";

const SRC = join(process.cwd(), "src");

function sources(dir: string, found: string[] = []): string[] {
  for (const entry of readdirSync(dir)) {
    const full = join(dir, entry);
    if (statSync(full).isDirectory()) {
      if (entry === "__tests__") continue;
      sources(full, found);
    } else if (entry.endsWith(".ts")) found.push(full);
  }
  return found;
}

describe("the worker has NO HTTP surface (§3.1)", () => {
  it("starts no server and imports no web framework", () => {
    const all = sources(SRC).map((file) => readFileSync(file, "utf8"));
    for (const source of all) {
      expect(source).not.toMatch(/from\s+["'](express|fastify|koa|hapi|next)["']/);
      expect(source).not.toMatch(/createServer\s*\(/);
      expect(source).not.toMatch(/\.listen\s*\(/);
    }
  });
});

describe("queue and job wiring comes from @sunil/core, not from local strings", () => {
  it("hosts exactly the two Phase 1 queues", () => {
    expect([...ALL_QUEUE_NAMES]).toEqual([QUEUE_NAMES.system, QUEUE_NAMES.agents]);
  });

  it("gives every Phase 1 job name a deadline", () => {
    for (const jobName of Object.values(JOB_NAMES)) {
      expect(JOB_TIMEOUT_MS[jobName]).toBeGreaterThan(0);
    }
  });

  it("keeps concurrency small and explicit", () => {
    expect(DEFAULT_CONCURRENCY).toBeGreaterThan(0);
    expect(DEFAULT_CONCURRENCY).toBeLessThanOrEqual(4);
  });
});

describe("Phase 1 agent runs make no model call, and say so", () => {
  it("uses a step factory whose default performs no LLM call (honest Phase 1 limitation)", async () => {
    const steps = noWorkloadStepFactory({
      id: "0193f2b0-0000-7000-8000-000000000001",
      slug: "probe",
      name: "Probe",
      role: "probe",
      systemInstructions: "instructions",
      toolAllowlist: [],
      providerId: null,
      modelId: null,
      maxDurationSeconds: 60,
      tokenBudget: null,
      costBudgetUsd: null,
      heartbeatIntervalSeconds: 30,
      staleThresholdSeconds: 90,
      enabled: true,
    });

    expect(steps).toHaveLength(1);
    const result = await steps[0]?.({} as never);
    expect(result?.tokensUsed).toBe(0);
    expect(result?.note).toContain("no model call");
  });
});
