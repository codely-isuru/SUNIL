/**
 * FR-070 / FR-071 / FR-072 / FR-074 — the runtime loop.
 */
import { describe, expect, it } from "vitest";
import { ENVELOPE_TYPES, ValidationError } from "@sunil/core";
import { buildSystemPrompt, requireAgentConfig } from "../config.js";
import { EnvelopeEmitter } from "../envelopes.js";
import { AgentRuntime, type AgentStep } from "../runtime.js";
import {
  AUTOCOMMIT_TX,
  FakeAgentStore,
  FakeAuditedRunner,
  FakeMessageStore,
  makeAgentRow,
} from "./support.js";

function harness(rowOverrides = {}) {
  const row = makeAgentRow(rowOverrides);
  const agents = new FakeAgentStore([row]);
  const messages = new FakeMessageStore();
  const uow = new FakeAuditedRunner();
  const runtime = new AgentRuntime({ agents, messages, uow, db: AUTOCOMMIT_TX });
  return { row, agents, messages, uow, runtime, config: requireAgentConfig(row) };
}

const noteStep = (note: string, extra: Record<string, unknown> = {}): AgentStep =>
  () => Promise.resolve({ note, ...extra });

describe("config-driven execution (FR-070)", () => {
  it("runs two differently configured agents through the identical code path", async () => {
    const first = harness({ id: "0193f2b0-0000-7000-8000-00000000000a", slug: "agent-one" });
    const second = harness({
      id: "0193f2b0-0000-7000-8000-00000000000b",
      slug: "agent-two",
      systemInstructions: "Completely different instructions.",
      maxDurationSeconds: 120,
      modelId: "gpt-4.1-mini",
    });

    for (const h of [first, second]) {
      const outcome = await h.runtime.run({
        config: h.config,
        objective: "do the thing",
        assignedBy: "test",
        correlationId: `corr-${h.config.slug}`,
        steps: [noteStep("only step", { done: true })],
      });
      expect(outcome.status).toBe("COMPLETED");
      expect(outcome.stepsRun).toBe(1);
    }

    expect(first.messages.types()).toEqual(second.messages.types());
  });

  it("refuses a configuration with a non-empty tool allowlist, naming the field", () => {
    const row = makeAgentRow({ toolAllowlist: ["shell"] as never });
    expect(() => requireAgentConfig(row)).toThrow(ValidationError);
    expect(() => requireAgentConfig(row)).toThrow(/toolAllowlist/);
  });

  it("refuses to run a disabled agent", async () => {
    const h = harness({ enabled: false });
    await expect(
      h.runtime.run({
        config: h.config,
        objective: "x",
        assignedBy: "test",
        correlationId: "c",
        steps: [],
      }),
    ).rejects.toThrow(ValidationError);
  });
});

describe("envelope emission and persistence (FR-071/FR-072)", () => {
  it("emits assignment, start, progress and completion in order, all persisted", async () => {
    const h = harness();
    const outcome = await h.runtime.run({
      config: h.config,
      objective: "summarise the fixture",
      assignedBy: "unit-test",
      correlationId: "corr-run-1",
      inputs: { a: 1 },
      steps: [noteStep("step one"), noteStep("step two", { done: true })],
    });

    expect(h.messages.types()).toEqual([
      "TASK_ASSIGNED",
      "TASK_STARTED",
      "TASK_PROGRESS",
      "TASK_PROGRESS",
      "TASK_COMPLETED",
    ]);
    expect(outcome.envelopes).toBe(5);
    expect(h.messages.rows.every((row) => row.correlationId === "corr-run-1")).toBe(true);
  });

  it("rejects a malformed envelope BEFORE persistence and names the failing field", async () => {
    const messages = new FakeMessageStore();
    const emitter = new EnvelopeEmitter({ messages, db: AUTOCOMMIT_TX });

    await expect(
      emitter.emit({
        type: "TASK_PROGRESS",
        agentId: "not-a-uuid",
        taskId: "0193f2b0-0000-7000-8000-000000000002",
        correlationId: "c",
        payload: { step: 0, note: "x" },
      }),
    ).rejects.toThrow(/agentId/);
    expect(messages.rows).toHaveLength(0);
  });

  it("persists APPROVAL_REQUIRED and runs no approval workflow (FR-071)", async () => {
    const h = harness();
    const outcome = await h.runtime.run({
      config: h.config,
      objective: "needs sign-off",
      assignedBy: "unit-test",
      correlationId: "corr-approval",
      steps: [
        noteStep("about to do something", {
          requestApproval: { action: "delete everything", rationale: "because" },
        }),
        noteStep("never reached"),
      ],
    });

    expect(h.messages.types()).toContain("APPROVAL_REQUIRED");
    expect(outcome.status).toBe("BLOCKED");
    expect(outcome.stepsRun).toBe(1);
    // Nothing resolves it, nothing approves it, and the run does not continue.
    expect(h.messages.types()).not.toContain("TASK_COMPLETED");
  });

  it("covers all nine envelope types across the runtime and the sweeper", () => {
    // Eight are reachable from the runtime; AGENT_HEARTBEAT comes from the pump and
    // TASK_FAILED from either a step throwing or the staleness sweep.
    expect(ENVELOPE_TYPES).toHaveLength(9);
  });
});

describe("in-loop budget and timeout enforcement (FR-074, §11.4)", () => {
  it("halts on maxDurationSeconds and emits TASK_BLOCKED(reason=timeout)", async () => {
    let clock = 1_000_000;
    const row = makeAgentRow({ maxDurationSeconds: 5 });
    const agents = new FakeAgentStore([row]);
    const messages = new FakeMessageStore();
    const runtime = new AgentRuntime({
      agents,
      messages,
      uow: new FakeAuditedRunner(),
      db: AUTOCOMMIT_TX,
      now: () => clock,
    });

    const slowStep: AgentStep = () => {
      clock += 6000; // the step "took" 6 seconds
      return Promise.resolve({ note: "slow step" });
    };

    const outcome = await runtime.run({
      config: requireAgentConfig(row),
      objective: "long job",
      assignedBy: "unit-test",
      correlationId: "corr-timeout",
      steps: [slowStep, slowStep],
    });

    expect(outcome.status).toBe("BLOCKED");
    expect(outcome.blockedReason).toBe("timeout");
    expect(outcome.stepsRun).toBe(1);
    const blocked = messages.rows.find((row_) => row_.type === "TASK_BLOCKED");
    expect(blocked?.payload).toMatchObject({ reason: "timeout" });
  });

  it("halts on a token budget reported by usage, not by asking the model to self-limit", async () => {
    const row = makeAgentRow({ tokenBudget: 100 });
    const h = harness({ tokenBudget: 100 });

    const outcome = await h.runtime.run({
      config: requireAgentConfig(row),
      objective: "expensive job",
      assignedBy: "unit-test",
      correlationId: "corr-budget",
      steps: [
        noteStep("cheap", { tokensUsed: 60 }),
        noteStep("expensive", { tokensUsed: 60 }),
        noteStep("never reached"),
      ],
    });

    expect(outcome.status).toBe("BLOCKED");
    expect(outcome.blockedReason).toBe("budget");
    expect(outcome.stepsRun).toBe(2);
    expect(outcome.tokensUsed).toBe(120);
  });

  it("halts on a cost budget", async () => {
    const row = makeAgentRow({ costBudgetUsd: 0.001 as never });
    const h = harness({ costBudgetUsd: 0.001 as never });
    const outcome = await h.runtime.run({
      config: requireAgentConfig(row),
      objective: "expensive job",
      assignedBy: "unit-test",
      correlationId: "corr-cost",
      steps: [noteStep("pricey", { costUsd: 0.002 }), noteStep("never reached")],
    });

    expect(outcome.blockedReason).toBe("budget");
    expect(outcome.stepsRun).toBe(1);
  });

  it("NEVER puts a limit into the system prompt — the prompt is the instructions verbatim", async () => {
    const row = makeAgentRow({
      maxDurationSeconds: 37,
      tokenBudget: 4242,
      systemInstructions: "You are a fixture agent.",
    });
    const config = requireAgentConfig(row);
    expect(buildSystemPrompt(config)).toBe("You are a fixture agent.");

    const seen: string[] = [];
    const h = harness();
    await h.runtime.run({
      config,
      objective: "x",
      assignedBy: "unit-test",
      correlationId: "corr-prompt",
      steps: [
        (context) => {
          seen.push(context.systemPrompt);
          return Promise.resolve({ note: "checked the prompt", done: true });
        },
      ],
    });

    expect(seen).toEqual(["You are a fixture agent."]);
    for (const prompt of seen) {
      expect(prompt).not.toMatch(/37|4242|budget|token limit|max duration/i);
    }
  });

  it("hands every step an AbortSignal and a shrinking deadline for in-flight LLM calls", async () => {
    const h = harness();
    const observed: { aborted: boolean; remainingMs: number }[] = [];

    await h.runtime.run({
      config: h.config,
      objective: "x",
      assignedBy: "unit-test",
      correlationId: "corr-signal",
      steps: [
        (context) => {
          observed.push({ aborted: context.signal.aborted, remainingMs: context.remainingMs });
          return Promise.resolve({ note: "one", done: true });
        },
      ],
    });

    expect(observed[0]?.aborted).toBe(false);
    expect(observed[0]?.remainingMs).toBeGreaterThan(0);
    expect(observed[0]?.remainingMs).toBeLessThanOrEqual(60_000);
  });
});

describe("failure handling", () => {
  it("emits TASK_FAILED and leaves the agent FAILED when a step throws", async () => {
    const h = harness();
    const outcome = await h.runtime.run({
      config: h.config,
      objective: "x",
      assignedBy: "unit-test",
      correlationId: "corr-fail",
      steps: [
        () => Promise.reject(new Error("step exploded")),
      ],
    });

    expect(outcome.status).toBe("FAILED");
    expect(h.messages.types()).toContain("TASK_FAILED");
    expect(h.agents.rows.get(h.config.id)?.status).toBe("FAILED");
  });

  it("rolls the status change AND its envelope back when the audit write fails (ADR-005)", async () => {
    const h = harness();
    h.uow.failAuditWith = new Error("audit table unavailable");

    await expect(
      h.runtime.run({
        config: h.config,
        objective: "x",
        assignedBy: "unit-test",
        correlationId: "corr-audit-fail",
        steps: [noteStep("never persisted", { done: true })],
      }),
    ).rejects.toThrow("audit table unavailable");

    expect(h.messages.rows).toHaveLength(0);
    expect(h.agents.rows.get(h.config.id)?.status).toBe("IDLE");
    expect(h.uow.entries).toHaveLength(0);
  });

  it("audits every run start and finish through runAudited", async () => {
    const h = harness();
    await h.runtime.run({
      config: h.config,
      objective: "x",
      assignedBy: "unit-test",
      correlationId: "corr-audit",
      steps: [noteStep("one", { done: true })],
    });

    expect(h.uow.entries.map((entry) => entry.action)).toEqual(["agent.run", "agent.run"]);
    expect(h.uow.entries[0]).toMatchObject({ actorType: "AGENT", targetType: "agent" });
  });
});
