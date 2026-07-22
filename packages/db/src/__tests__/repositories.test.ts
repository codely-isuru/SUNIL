/**
 * Query-shape tests for the repository additions.
 *
 * These assert the WHERE clause a repository builds, against a capturing double. The
 * behaviour against real Postgres — the foreign key, the cutoff boundary — is proven in
 * `schema.integration.test.ts`.
 */
import { describe, expect, it } from "vitest";
import type { SunilPrismaClient } from "../client.js";
import { JobExecutionRepository, UsageRepository } from "../repositories/platform.js";

interface Captured {
  findMany: Record<string, unknown>[];
  count: Record<string, unknown>[];
  create: Record<string, unknown>[];
}

function capturingClient(options: { createFails?: () => unknown } = {}) {
  const captured: Captured = { findMany: [], count: [], create: [] };
  let createCalls = 0;

  const model = {
    findMany: (args: Record<string, unknown>) => {
      captured.findMany.push(args);
      return Promise.resolve([]);
    },
    count: (args: Record<string, unknown>) => {
      captured.count.push(args);
      return Promise.resolve(0);
    },
    create: (args: Record<string, unknown>) => {
      captured.create.push(args);
      createCalls += 1;
      if (options.createFails && createCalls === 1) {
        return Promise.reject(options.createFails());
      }
      return Promise.resolve(args["data"]);
    },
  };

  const client = { jobExecution: model, usageRecord: model } as unknown as SunilPrismaClient;
  return { client, captured };
}

describe("JobExecutionRepository.findRunningStartedBefore", () => {
  it("selects only RUNNING rows strictly older than the cutoff", async () => {
    const { client, captured } = capturingClient();
    const cutoff = new Date("2026-07-21T00:00:00.000Z");

    await new JobExecutionRepository(client).findRunningStartedBefore(cutoff);

    expect(captured.findMany[0]?.["where"]).toEqual({
      outcome: "RUNNING",
      startedAt: { lt: cutoff },
    });
    // Oldest first, so a bounded reconciliation pass drains the worst orphans first.
    expect(captured.findMany[0]?.["orderBy"]).toEqual({ startedAt: "asc" });
    expect(captured.findMany[0]?.["take"]).toBe(500);
  });

  it("honours an explicit limit", async () => {
    const { client, captured } = capturingClient();
    await new JobExecutionRepository(client).findRunningStartedBefore(new Date(), 25);
    expect(captured.findMany[0]?.["take"]).toBe(25);
  });
});

describe("JobExecutionRepository.listPaged filtering (FR-085)", () => {
  it("issues no WHERE clause when unfiltered — the existing call signature is unchanged", async () => {
    const { client, captured } = capturingClient();
    await new JobExecutionRepository(client).listPaged({ page: 1, pageSize: 50 });
    expect(captured.findMany[0]?.["where"]).toEqual({});
    expect(captured.count[0]?.["where"]).toEqual({});
  });

  it("filters by queue and outcome", async () => {
    const { client, captured } = capturingClient();
    await new JobExecutionRepository(client).listPaged(
      { page: 2, pageSize: 10 },
      { queue: "system", outcome: "FAILED" },
    );
    expect(captured.findMany[0]?.["where"]).toEqual({ queue: "system", outcome: "FAILED" });
    expect(captured.findMany[0]?.["skip"]).toBe(10);
    expect(captured.findMany[0]?.["take"]).toBe(10);
  });

  it("filters by scheduler id and a start window", async () => {
    const { client, captured } = capturingClient();
    const from = new Date("2026-07-01T00:00:00.000Z");
    const to = new Date("2026-07-02T00:00:00.000Z");

    await new JobExecutionRepository(client).listPaged(
      { page: 1, pageSize: 10 },
      { schedulerId: "system:session-sweep", jobName: "session-sweep", startedFrom: from, startedTo: to },
    );

    expect(captured.findMany[0]?.["where"]).toEqual({
      schedulerId: "system:session-sweep",
      jobName: "session-sweep",
      startedAt: { gte: from, lte: to },
    });
  });

  it("applies the SAME filter to the count, so `total` and `hasMore` are not lies", async () => {
    const { client, captured } = capturingClient();
    await new JobExecutionRepository(client).listPaged(
      { page: 1, pageSize: 10 },
      { queue: "agents" },
    );
    expect(captured.count[0]?.["where"]).toEqual(captured.findMany[0]?.["where"]);
  });
});

describe("UsageRepository scalar and resilient write paths", () => {
  it("recordUnchecked sets agentId as a scalar, with no relation connect", async () => {
    const { client, captured } = capturingClient();
    await new UsageRepository(client).recordUnchecked({
      provider: "anthropic",
      model: "m",
      feature: "agent-run",
      agentId: "018f4a9e-0000-7000-8000-0000000000aa",
      tokensIn: 1,
      tokensOut: 2,
      latencyMs: 3,
    });

    const data = captured.create[0]?.["data"] as Record<string, unknown>;
    expect(data["agentId"]).toBe("018f4a9e-0000-7000-8000-0000000000aa");
    expect(data).not.toHaveProperty("agent");
  });

  it("expresses 'no agent' as an explicit null", async () => {
    const { client, captured } = capturingClient();
    await new UsageRepository(client).recordUnchecked({
      provider: "openai",
      model: "m",
      feature: "smoke-test",
      agentId: null,
      tokensIn: 0,
      tokensOut: 0,
      latencyMs: 1,
    });
    expect((captured.create[0]?.["data"] as Record<string, unknown>)["agentId"]).toBeNull();
  });

  it("degrades agentId to null and still writes the row when the agent has vanished", async () => {
    const { client, captured } = capturingClient({
      createFails: () => Object.assign(new Error("FK violation"), { code: "P2003" }),
    });

    const written = await new UsageRepository(client).recordAllowingMissingAgent({
      provider: "anthropic",
      model: "m",
      feature: "agent-run",
      agentId: "018f4a9e-0000-7000-8000-00000000dead",
      tokensIn: 5,
      tokensOut: 6,
      latencyMs: 7,
    });

    expect(captured.create).toHaveLength(2);
    expect((captured.create[0]?.["data"] as Record<string, unknown>)["agentId"]).toBe(
      "018f4a9e-0000-7000-8000-00000000dead",
    );
    // FR-064's row survives; only the attribution is dropped.
    expect((written as Record<string, unknown>)["agentId"]).toBeNull();
    expect((written as Record<string, unknown>)["tokensIn"]).toBe(5);
  });

  it("does NOT swallow an error that is not a foreign-key violation", async () => {
    const { client } = capturingClient({
      createFails: () => Object.assign(new Error("connection lost"), { code: "P1001" }),
    });

    await expect(
      new UsageRepository(client).recordAllowingMissingAgent({
        provider: "anthropic",
        model: "m",
        feature: "agent-run",
        agentId: "018f4a9e-0000-7000-8000-00000000dead",
        tokensIn: 1,
        tokensOut: 1,
        latencyMs: 1,
      }),
    ).rejects.toThrow("connection lost");
  });

  it("does not retry when there was no agentId to blame", async () => {
    const { client, captured } = capturingClient({
      createFails: () => Object.assign(new Error("FK violation"), { code: "P2003" }),
    });

    await expect(
      new UsageRepository(client).recordAllowingMissingAgent({
        provider: "anthropic",
        model: "m",
        feature: "smoke-test",
        agentId: null,
        tokensIn: 1,
        tokensOut: 1,
        latencyMs: 1,
      }),
    ).rejects.toThrow("FK violation");

    expect(captured.create).toHaveLength(1);
  });
});
