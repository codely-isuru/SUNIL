/**
 * Out-of-process stale-agent detection (§11.3, FR-073).
 *
 * A SILENT AGENT MUST BE DETECTABLE AS FAILED. Heartbeats are emitted by a timer inside a
 * running job, so they stop when the process dies — which is exactly why detection cannot
 * live there. This sweeper is invoked by the DURABLE repeatable job
 * `system:agent-staleness-sweep` (every 60 s, defined in `@sunil/core`), which runs in the
 * worker whether or not the agent's process, or the scheduler, still exists.
 *
 * For each agent with `status = RUNNING` and `lastHeartbeatAt < now − staleThresholdSeconds`
 * (the threshold is per-agent CONFIGURATION), one audited transaction:
 *   status → FAILED (via STALE), currentTaskId cleared
 *   + a `TASK_FAILED` envelope
 *   + an `agent.stale` audit record
 * They commit together or not at all.
 */
import { randomUUID } from "node:crypto";
import type { AuditEntry } from "@sunil/core";
import type { Agent } from "@sunil/db";
import type { AgentStore, AuditedRunner } from "./ports.js";
import type { EnvelopeEmitter } from "./envelopes.js";
import { NOOP_AGENT_LOGGER, type AgentLogger } from "./logging.js";

export interface StaleAgentSweeperDeps {
  readonly agents: AgentStore;
  readonly emitter: EnvelopeEmitter;
  readonly uow: AuditedRunner;
  readonly logger?: AgentLogger;
  readonly now?: () => number;
}

export interface StaleSweepResult {
  readonly checkedAt: string;
  readonly sweptAgentIds: readonly string[];
}

export class StaleAgentSweeper {
  readonly #deps: StaleAgentSweeperDeps;
  readonly #logger: AgentLogger;
  readonly #now: () => number;

  constructor(deps: StaleAgentSweeperDeps) {
    this.#deps = deps;
    this.#logger = deps.logger ?? NOOP_AGENT_LOGGER;
    this.#now = deps.now ?? Date.now;
  }

  async sweep(correlationId: string): Promise<StaleSweepResult> {
    const at = new Date(this.#now());
    const stale = await this.#deps.agents.findStale(at);
    const swept: string[] = [];

    for (const agent of stale) {
      try {
        await this.#failAgent(agent, at, correlationId);
        swept.push(agent.id);
        this.#logger.warn(
          {
            agentId: agent.id,
            slug: agent.slug,
            taskId: agent.currentTaskId,
            staleThresholdSeconds: agent.staleThresholdSeconds,
            correlationId,
          },
          "agent exceeded its stale threshold; marked FAILED",
        );
      } catch (error) {
        // One bad agent must not abandon the rest of the sweep.
        this.#logger.error(
          {
            agentId: agent.id,
            correlationId,
            error: error instanceof Error ? error.name : "unknown",
          },
          "could not mark a stale agent FAILED; it will be retried on the next sweep",
        );
      }
    }

    return { checkedAt: at.toISOString(), sweptAgentIds: swept };
  }

  async #failAgent(agent: Agent, at: Date, correlationId: string): Promise<void> {
    // A run that never recorded a task id still needs a task-scoped envelope.
    const taskId = agent.currentTaskId ?? randomUUID();
    const lastBeat = agent.lastHeartbeatAt ? agent.lastHeartbeatAt.toISOString() : null;

    const entry: AuditEntry = {
      actorType: "SYSTEM",
      actorId: null,
      actorLabel: "system:agent-staleness-sweep",
      action: "agent.stale",
      targetType: "agent",
      targetId: agent.id,
      before: { status: agent.status, lastHeartbeatAt: lastBeat },
      after: {
        status: "FAILED",
        transition: "RUNNING→STALE→FAILED",
        staleThresholdSeconds: agent.staleThresholdSeconds,
        detectedAt: at.toISOString(),
      },
      outcome: "FAILURE",
      correlationId,
    };

    await this.#deps.uow.runAudited(entry, async (tx) => {
      await this.#deps.agents.update(tx, agent.id, { status: "FAILED", currentTaskId: null });
      await this.#deps.emitter.emit(
        {
          type: "TASK_FAILED",
          agentId: agent.id,
          taskId,
          parentTaskId: null,
          correlationId,
          payload: {
            errorClass: "stale",
            message: `no heartbeat since ${lastBeat ?? "never"}; exceeded staleThresholdSeconds=${agent.staleThresholdSeconds}`,
            retryable: true,
          },
        },
        tx,
      );
    });
  }
}
