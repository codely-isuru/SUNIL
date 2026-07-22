import { describe, expect, it } from "vitest";
import { DEFAULT_JOB_OPTIONS, PERMISSIONS, QUEUE_NAMES } from "@sunil/core";
import { prepareWorkerBootstrap } from "../main.js";

const validEnv = {
  DATABASE_URL: "postgresql://localhost:5432/sunil",
  REDIS_URL: "redis://localhost:6379",
  SUNIL_MASTER_KEY: Buffer.alloc(32, 5).toString("base64"),
} as NodeJS.ProcessEnv;

describe("apps/worker consumes the SAME @sunil/core definitions as apps/api (FR-002)", () => {
  it("sees one permission catalogue, not a local copy", () => {
    expect(PERMISSIONS).toHaveLength(21);
  });

  it("hosts exactly the two Phase 1 queues (deviation D-3)", () => {
    expect(prepareWorkerBootstrap(validEnv).queues).toEqual([
      QUEUE_NAMES.system,
      QUEUE_NAMES.agents,
    ]);
  });

  it("retains failed jobs so they stay visible and rerunnable (FR-081)", () => {
    expect(DEFAULT_JOB_OPTIONS.removeOnFail).toBe(false);
    expect(DEFAULT_JOB_OPTIONS.attempts).toBe(3);
    expect(DEFAULT_JOB_OPTIONS.backoff.type).toBe("exponential");
  });
});
