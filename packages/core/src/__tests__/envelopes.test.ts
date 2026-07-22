import { describe, expect, it } from "vitest";
import {
  AgentEnvelopeSchema,
  ENVELOPE_SCHEMAS,
  ENVELOPE_TYPES,
  parseEnvelope,
} from "../envelopes.js";

const AGENT_ID = "018f4a9e-0000-7000-8000-000000000001";
const TASK_ID = "018f4a9e-0000-7000-8000-000000000002";

const base = {
  agentId: AGENT_ID,
  taskId: TASK_ID,
  correlationId: "corr-1",
};

const FIXTURES: Record<string, Record<string, unknown>> = {
  TASK_ASSIGNED: {
    ...base,
    type: "TASK_ASSIGNED",
    payload: { objective: "Summarise inbox", assignedBy: "owner@example.test" },
  },
  TASK_STARTED: {
    ...base,
    type: "TASK_STARTED",
    payload: { startedAt: "2026-01-01T00:00:00.000Z" },
  },
  TASK_PROGRESS: {
    ...base,
    type: "TASK_PROGRESS",
    payload: { step: 1, note: "reading" },
  },
  INFORMATION_REQUIRED: {
    ...base,
    type: "INFORMATION_REQUIRED",
    payload: { question: "Which mailbox?" },
  },
  APPROVAL_REQUIRED: {
    ...base,
    type: "APPROVAL_REQUIRED",
    payload: { action: "send email", rationale: "reply drafted" },
  },
  TASK_BLOCKED: {
    ...base,
    type: "TASK_BLOCKED",
    payload: { reason: "budget", detail: "token budget exhausted" },
  },
  TASK_COMPLETED: {
    ...base,
    type: "TASK_COMPLETED",
    payload: { summary: "done", durationMs: 1200 },
  },
  TASK_FAILED: {
    ...base,
    type: "TASK_FAILED",
    payload: { errorClass: "timeout", message: "deadline exceeded", retryable: true },
  },
  AGENT_HEARTBEAT: {
    ...base,
    type: "AGENT_HEARTBEAT",
    payload: { emittedAt: "2026-01-01T00:00:30.000Z", elapsedSeconds: 30 },
  },
};

describe("message envelope contracts (§11.2)", () => {
  it("defines exactly nine envelope types", () => {
    expect(ENVELOPE_TYPES).toHaveLength(9);
    expect(Object.keys(ENVELOPE_SCHEMAS).sort()).toEqual([...ENVELOPE_TYPES].sort());
  });

  it.each(ENVELOPE_TYPES)("accepts a valid %s envelope", (type) => {
    const result = parseEnvelope(FIXTURES[type]);
    expect(result.ok, JSON.stringify(result)).toBe(true);
  });

  it("rejects an unknown envelope type", () => {
    const result = parseEnvelope({ ...base, type: "TASK_YOLO", payload: {} });
    expect(result.ok).toBe(false);
  });

  it("names the failing field rather than failing silently", () => {
    const result = parseEnvelope({
      ...base,
      type: "TASK_PROGRESS",
      payload: { step: -1, note: "" },
    });
    expect(result.ok).toBe(false);
    if (result.ok) return;
    expect(result.issues.join("\n")).toMatch(/payload\.step/);
  });

  it("rejects a malformed agentId before persist", () => {
    const result = parseEnvelope({ ...FIXTURES["TASK_STARTED"], agentId: "not-a-uuid" });
    expect(result.ok).toBe(false);
    if (result.ok) return;
    expect(result.issues.join("\n")).toMatch(/agentId/);
  });

  it("persists APPROVAL_REQUIRED as a plain envelope — there is no approval workflow", () => {
    const parsed = AgentEnvelopeSchema.parse(FIXTURES["APPROVAL_REQUIRED"]);
    expect(parsed.type).toBe("APPROVAL_REQUIRED");
    expect(Object.keys(parsed)).not.toContain("approvedBy");
    expect(Object.keys(parsed)).not.toContain("approvalState");
  });

  it("carries no prompt or completion text field on any envelope", () => {
    for (const type of ENVELOPE_TYPES) {
      const parsed = AgentEnvelopeSchema.parse(FIXTURES[type]);
      const keys = Object.keys(parsed);
      expect(keys).not.toContain("prompt");
      expect(keys).not.toContain("completion");
    }
  });
});
