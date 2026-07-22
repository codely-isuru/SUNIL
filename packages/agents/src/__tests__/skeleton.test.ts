import { describe, expect, it } from "vitest";
import { ENVELOPE_TYPES, loadAgentConfig } from "@sunil/core";
import { PACKAGE_NAME } from "../index.js";

describe("@sunil/agents skeleton", () => {
  it("is wired into the workspace", () => {
    expect(PACKAGE_NAME).toBe("@sunil/agents");
  });

  it("has all nine envelope contracts available to the runtime (§11.2)", () => {
    expect(ENVELOPE_TYPES).toHaveLength(9);
  });

  it("cannot load an agent with tools in Phase 1 (FR-070)", () => {
    const result = loadAgentConfig({
      id: "018f4a9e-0000-7000-8000-000000000001",
      slug: "probe",
      name: "Probe",
      role: "probe",
      systemInstructions: "probe",
      toolAllowlist: ["shell"],
      maxDurationSeconds: 60,
      heartbeatIntervalSeconds: 30,
      staleThresholdSeconds: 90,
    });
    expect(result.ok).toBe(false);
  });
});
