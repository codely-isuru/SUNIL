/**
 * Heartbeats (§11.3, FR-073).
 *
 * While an agent job RUNS, the runtime emits `AGENT_HEARTBEAT` every
 * `heartbeatIntervalSeconds` and updates `Agent.lastHeartbeatAt`.
 *
 * THE ONE SANCTIONED IN-PROCESS TIMER (ET-4 4.10): this `setInterval` lives INSIDE an
 * already-running job and is not the durability mechanism for any scheduled work. Staleness
 * detection itself is the durable, out-of-process repeatable job
 * `system:agent-staleness-sweep`, which runs whether or not this process exists.
 *
 * The pump also reads the agent row back each tick: if something out of process has moved the
 * agent out of RUNNING (the staleness sweep marking it STALE/FAILED), the run is halted
 * instead of being left hanging — FR-073's "its job is failed rather than left hanging".
 */
import type { AgentConfig, AgentStatus } from "@sunil/core";
import type { AgentStore } from "./ports.js";
import type { EnvelopeEmitter } from "./envelopes.js";
import { NOOP_AGENT_LOGGER, type AgentLogger } from "./logging.js";

export interface HeartbeatPumpDeps {
  readonly config: AgentConfig;
  readonly taskId: string;
  readonly parentTaskId?: string | null;
  readonly correlationId: string;
  readonly agents: AgentStore;
  readonly emitter: EnvelopeEmitter;
  readonly logger?: AgentLogger;
  readonly now?: () => number;
  /** Called when the agent row is no longer RUNNING — i.e. someone else halted this run. */
  readonly onExternalHalt: (status: AgentStatus) => void;
}

export class HeartbeatPump {
  readonly #deps: HeartbeatPumpDeps;
  readonly #logger: AgentLogger;
  readonly #now: () => number;
  readonly #startedAt: number;
  #timer: ReturnType<typeof setInterval> | undefined;
  #beats = 0;

  constructor(deps: HeartbeatPumpDeps) {
    this.#deps = deps;
    this.#logger = deps.logger ?? NOOP_AGENT_LOGGER;
    this.#now = deps.now ?? Date.now;
    this.#startedAt = this.#now();
  }

  get beats(): number {
    return this.#beats;
  }

  start(): void {
    if (this.#timer) return;
    const intervalMs = this.#deps.config.heartbeatIntervalSeconds * 1000;
    this.#timer = setInterval(() => {
      void this.tick();
    }, intervalMs);
    // Never let the heartbeat alone hold the process open — it is a job-scoped timer.
    this.#timer.unref?.();
  }

  stop(): void {
    if (!this.#timer) return;
    clearInterval(this.#timer);
    this.#timer = undefined;
  }

  /**
   * One beat. Public so tests drive it deterministically instead of waiting on wall clock —
   * and so the runtime can emit an immediate first heartbeat at start.
   */
  async tick(): Promise<void> {
    const at = new Date(this.#now());
    try {
      await this.#deps.emitter.emit({
        type: "AGENT_HEARTBEAT",
        agentId: this.#deps.config.id,
        taskId: this.#deps.taskId,
        parentTaskId: this.#deps.parentTaskId ?? null,
        correlationId: this.#deps.correlationId,
        payload: {
          emittedAt: at,
          elapsedSeconds: Math.floor((this.#now() - this.#startedAt) / 1000),
        },
      });
      await this.#deps.agents.recordHeartbeat(this.#deps.config.id, at);
      this.#beats += 1;

      const row = await this.#deps.agents.findById(this.#deps.config.id);
      if (row && row.status !== "RUNNING") {
        this.#logger.warn(
          { agentId: this.#deps.config.id, status: row.status, taskId: this.#deps.taskId },
          "agent was moved out of RUNNING out of process; halting the run",
        );
        this.#deps.onExternalHalt(row.status);
      }
    } catch (error) {
      // A failed heartbeat must not kill the run: the staleness sweep is the backstop, and
      // that is precisely the case it exists to catch.
      this.#logger.error(
        {
          agentId: this.#deps.config.id,
          taskId: this.#deps.taskId,
          error: error instanceof Error ? error.name : "unknown",
        },
        "heartbeat failed; the out-of-process staleness sweep remains the backstop",
      );
    }
  }
}
