import { describe, expect, it } from "vitest";
import { REPEATABLE_DEFINITIONS, SCHEDULER_IDS } from "@sunil/core";
import { prepareSchedulerBootstrap } from "../main.js";

const validEnv = {
  DATABASE_URL: "postgresql://localhost:5432/sunil",
  REDIS_URL: "redis://localhost:6379",
  SUNIL_MASTER_KEY: Buffer.alloc(32, 9).toString("base64"),
} as NodeJS.ProcessEnv;

describe("repeatable-job identity (ADR-010)", () => {
  it("registers stable, code-defined scheduler ids", () => {
    const result = prepareSchedulerBootstrap(validEnv);
    expect(result.schedulerIds).toEqual([
      "system:session-sweep",
      "system:agent-staleness-sweep",
    ]);
    expect(result.definitions).toBe(2);
  });

  it("has no duplicate scheduler id — restart cannot fork a definition", () => {
    const ids = REPEATABLE_DEFINITIONS.map((d) => d.schedulerId);
    expect(new Set(ids).size).toBe(ids.length);
  });

  it("derives identity from the id, never from the repeat options", () => {
    for (const definition of REPEATABLE_DEFINITIONS) {
      expect(Object.values(SCHEDULER_IDS)).toContain(definition.schedulerId);
      expect(definition.everyMs).toBeGreaterThan(0);
      // The legacy `repeat` option is banned; a definition carries an id, not a repeat key.
      expect(definition).not.toHaveProperty("repeat");
    }
  });
});
