/**
 * FR-073 — a running agent heartbeats; a SILENT agent is detectable as failed.
 */
import { describe, expect, it } from "vitest";
import { requireAgentConfig } from "../config.js";
import { EnvelopeEmitter } from "../envelopes.js";
import { HeartbeatPump } from "../heartbeat.js";
import { StaleAgentSweeper } from "../staleness.js";
import {
  AUTOCOMMIT_TX,
  FakeAgentStore,
  FakeAuditedRunner,
  FakeMessageStore,
  makeAgentRow,
} from "./support.js";

describe("heartbeats (§11.3)", () => {
  it("persists an AGENT_HEARTBEAT envelope and updates lastHeartbeatAt", async () => {
    const row = makeAgentRow({ status: "RUNNING", heartbeatIntervalSeconds: 1 });
    const agents = new FakeAgentStore([row]);
    const messages = new FakeMessageStore();
    const emitter = new EnvelopeEmitter({ messages, db: AUTOCOMMIT_TX });
    let clock = 1_700_000_000_000;

    const pump = new HeartbeatPump({
      config: requireAgentConfig(row),
      taskId: "0193f2b0-0000-7000-8000-0000000000ff",
      correlationId: "corr-heartbeat",
      agents,
      emitter,
      now: () => clock,
      onExternalHalt: () => undefined,
    });

    await pump.tick();
    clock += 30_000;
    await pump.tick();

    expect(messages.types()).toEqual(["AGENT_HEARTBEAT", "AGENT_HEARTBEAT"]);
    expect(agents.heartbeats).toHaveLength(2);
    expect(agents.rows.get(row.id)?.lastHeartbeatAt?.getTime()).toBe(clock);
    expect(messages.rows[1]?.payload).toMatchObject({ elapsedSeconds: 30 });
    expect(pump.beats).toBe(2);
  });

  it("halts the run when the agent is moved out of RUNNING out of process", async () => {
    const row = makeAgentRow({ status: "FAILED" });
    const agents = new FakeAgentStore([row]);
    const messages = new FakeMessageStore();
    const halted: string[] = [];

    const pump = new HeartbeatPump({
      config: requireAgentConfig(row),
      taskId: "0193f2b0-0000-7000-8000-0000000000fe",
      correlationId: "corr-external-halt",
      agents,
      emitter: new EnvelopeEmitter({ messages, db: AUTOCOMMIT_TX }),
      onExternalHalt: (status) => halted.push(status),
    });

    await pump.tick();

    expect(halted).toEqual(["FAILED"]);
  });

  it("uses configuration for the interval, not a constant, and never holds the process open", () => {
    const row = makeAgentRow({ heartbeatIntervalSeconds: 7 });
    const config = requireAgentConfig(row);
    expect(config.heartbeatIntervalSeconds).toBe(7);
    expect(config.staleThresholdSeconds).toBe(90);

    const pump = new HeartbeatPump({
      config,
      taskId: "0193f2b0-0000-7000-8000-0000000000fd",
      correlationId: "c",
      agents: new FakeAgentStore([row]),
      emitter: new EnvelopeEmitter({ messages: new FakeMessageStore(), db: AUTOCOMMIT_TX }),
      onExternalHalt: () => undefined,
    });
    pump.start();
    pump.stop();
    expect(pump.beats).toBe(0);
  });
});

describe("out-of-process staleness sweep (FR-073)", () => {
  const NOW = new Date("2026-01-01T12:00:00.000Z").getTime();

  function sweeperFor(rows: ReturnType<typeof makeAgentRow>[]) {
    const agents = new FakeAgentStore(rows);
    const messages = new FakeMessageStore();
    const uow = new FakeAuditedRunner();
    const emitter = new EnvelopeEmitter({ messages, db: AUTOCOMMIT_TX });
    return {
      agents,
      messages,
      uow,
      sweeper: new StaleAgentSweeper({ agents, emitter, uow, now: () => NOW }),
    };
  }

  it("marks a silent RUNNING agent FAILED, emits TASK_FAILED and audits it", async () => {
    const silent = makeAgentRow({
      id: "0193f2b0-0000-7000-8000-0000000000aa",
      status: "RUNNING",
      currentTaskId: "0193f2b0-0000-7000-8000-0000000000ab",
      staleThresholdSeconds: 90,
      lastHeartbeatAt: new Date(NOW - 120_000),
    });
    const { agents, messages, uow, sweeper } = sweeperFor([silent]);

    const result = await sweeper.sweep("corr-sweep");

    expect(result.sweptAgentIds).toEqual([silent.id]);
    expect(agents.rows.get(silent.id)?.status).toBe("FAILED");
    expect(agents.rows.get(silent.id)?.currentTaskId).toBeNull();
    expect(messages.types()).toEqual(["TASK_FAILED"]);
    expect(uow.entries[0]).toMatchObject({
      action: "agent.stale",
      actorType: "SYSTEM",
      targetId: silent.id,
      outcome: "FAILURE",
    });
  });

  it("leaves a healthy agent and an idle agent alone", async () => {
    const healthy = makeAgentRow({
      id: "0193f2b0-0000-7000-8000-0000000000ac",
      status: "RUNNING",
      lastHeartbeatAt: new Date(NOW - 10_000),
    });
    const idle = makeAgentRow({
      id: "0193f2b0-0000-7000-8000-0000000000ad",
      status: "IDLE",
      lastHeartbeatAt: new Date(NOW - 10_000_000),
    });
    const { agents, sweeper } = sweeperFor([healthy, idle]);

    const result = await sweeper.sweep("corr-sweep-2");

    expect(result.sweptAgentIds).toEqual([]);
    expect(agents.rows.get(healthy.id)?.status).toBe("RUNNING");
    expect(agents.rows.get(idle.id)?.status).toBe("IDLE");
  });

  it("uses each agent's OWN configured threshold", async () => {
    const patient = makeAgentRow({
      id: "0193f2b0-0000-7000-8000-0000000000ae",
      status: "RUNNING",
      staleThresholdSeconds: 600,
      lastHeartbeatAt: new Date(NOW - 120_000),
    });
    const impatient = makeAgentRow({
      id: "0193f2b0-0000-7000-8000-0000000000af",
      status: "RUNNING",
      staleThresholdSeconds: 30,
      lastHeartbeatAt: new Date(NOW - 120_000),
    });
    const { sweeper } = sweeperFor([patient, impatient]);

    const result = await sweeper.sweep("corr-sweep-3");
    expect(result.sweptAgentIds).toEqual([impatient.id]);
  });

  it("rolls back the whole transition when the audit write fails, and keeps sweeping", async () => {
    const silent = makeAgentRow({
      id: "0193f2b0-0000-7000-8000-0000000000ba",
      status: "RUNNING",
      staleThresholdSeconds: 30,
      lastHeartbeatAt: new Date(NOW - 120_000),
    });
    const { agents, messages, uow, sweeper } = sweeperFor([silent]);
    uow.failAuditWith = new Error("audit unavailable");

    const result = await sweeper.sweep("corr-sweep-4");

    expect(result.sweptAgentIds).toEqual([]);
    expect(agents.rows.get(silent.id)?.status).toBe("RUNNING");
    expect(messages.rows).toHaveLength(0);
  });
});
