/**
 * The agent runtime skeleton (§11).
 *
 * ONE code path runs every agent (FR-070): identity, instructions, provider/model, duration
 * and budgets all arrive as configuration, so a second agent with different configuration
 * runs through this exact loop with no agent-specific branch.
 *
 * The loop, in order:
 *   audited RUNNING transition + TASK_ASSIGNED + TASK_STARTED
 *   → start heartbeats (§11.3)
 *   → for each step: guard check → step → accumulate usage → TASK_PROGRESS → guard check
 *   → audited terminal transition + TASK_COMPLETED | TASK_BLOCKED | TASK_FAILED
 *
 * Scope fence (§18.9): no chat, no task management, no memory retrieval, no routing and no
 * approval workflow. `APPROVAL_REQUIRED` is persisted and nothing else happens (FR-071).
 */
import { randomUUID } from "node:crypto";
import {
  ValidationError,
  isSunilError,
  type AgentConfig,
  type AuditEntry,
  type BlockedReason,
} from "@sunil/core";
import type { TransactionClient } from "@sunil/db";
import type { AgentMessageStore, AgentStore, AuditedRunner } from "./ports.js";
import { RunGuard } from "./budget.js";
import { buildSystemPrompt } from "./config.js";
import { EnvelopeEmitter } from "./envelopes.js";
import { HeartbeatPump } from "./heartbeat.js";
import { NOOP_AGENT_LOGGER, type AgentLogger } from "./logging.js";

export interface AgentRuntimeDeps {
  readonly agents: AgentStore;
  readonly messages: AgentMessageStore;
  readonly uow: AuditedRunner;
  /** Write target for envelopes emitted outside an audited transaction. */
  readonly db: TransactionClient;
  readonly logger?: AgentLogger;
  readonly now?: () => number;
}

export interface AgentStepContext {
  readonly config: AgentConfig;
  readonly taskId: string;
  readonly correlationId: string;
  /** 0-based index of this step. */
  readonly step: number;
  /** Aborted when the guard halts the run — carry it into every provider call (§11.4). */
  readonly signal: AbortSignal;
  /** The configured instructions VERBATIM. No limit text is added (FR-074). */
  readonly systemPrompt: string;
  /** Milliseconds left before `maxDurationSeconds` — pass as the provider `timeoutMs`. */
  readonly remainingMs: number;
  readonly tokensUsedSoFar: number;
  readonly costUsdSoFar: number;
}

export interface AgentStepResult {
  /** Progress note persisted with `TASK_PROGRESS`. Never prompt or completion text. */
  readonly note: string;
  readonly tokensUsed?: number;
  readonly costUsd?: number;
  readonly percentComplete?: number;
  readonly outputs?: Record<string, unknown>;
  /** Emits `INFORMATION_REQUIRED` and halts the run (nothing resolves it in Phase 1). */
  readonly requestInformation?: { question: string; fields?: string[] };
  /** Emits `APPROVAL_REQUIRED` and halts. NO approval workflow runs (FR-071). */
  readonly requestApproval?: { action: string; rationale: string; riskNote?: string };
  /** Step-declared halt, e.g. a missing dependency. */
  readonly blocked?: { reason: Extract<BlockedReason, "dependency" | "error">; detail: string };
  /** Last step of the run. */
  readonly done?: boolean;
}

export type AgentStep = (context: AgentStepContext) => Promise<AgentStepResult>;

export interface AgentRunRequest {
  readonly config: AgentConfig;
  readonly objective: string;
  readonly assignedBy: string;
  readonly correlationId: string;
  readonly taskId?: string;
  readonly parentTaskId?: string | null;
  readonly inputs?: Record<string, unknown>;
  readonly steps: readonly AgentStep[];
}

export type AgentRunStatus = "COMPLETED" | "BLOCKED" | "FAILED";

export interface AgentRunOutcome {
  readonly taskId: string;
  readonly status: AgentRunStatus;
  readonly blockedReason?: BlockedReason;
  readonly detail?: string;
  readonly stepsRun: number;
  readonly tokensUsed: number;
  readonly costUsd: number;
  readonly envelopes: number;
  readonly durationMs: number;
}

export class AgentRuntime {
  readonly #deps: AgentRuntimeDeps;
  readonly #logger: AgentLogger;
  readonly #now: () => number;
  readonly emitter: EnvelopeEmitter;

  constructor(deps: AgentRuntimeDeps) {
    this.#deps = deps;
    this.#logger = deps.logger ?? NOOP_AGENT_LOGGER;
    this.#now = deps.now ?? Date.now;
    this.emitter = new EnvelopeEmitter({
      messages: deps.messages,
      db: deps.db,
      ...(deps.logger ? { logger: deps.logger } : {}),
    });
  }

  async run(request: AgentRunRequest): Promise<AgentRunOutcome> {
    const { config } = request;
    if (!config.enabled) {
      throw new ValidationError(`agent '${config.slug}' is disabled and cannot run`, ["enabled"]);
    }

    const taskId = request.taskId ?? randomUUID();
    const parentTaskId = request.parentTaskId ?? null;
    const base = {
      agentId: config.id,
      taskId,
      parentTaskId,
      correlationId: request.correlationId,
    };

    const guard = new RunGuard(config, this.#now);
    const startedAt = this.#now();
    let externalHalt: string | undefined;

    // ── Start: status, assignment and start envelopes commit together with their audit row.
    await this.#deps.uow.runAudited(
      this.#auditEntry(config, request.correlationId, "start", {
        status: "RUNNING",
        taskId,
      }),
      async (tx) => {
        await this.#deps.agents.update(tx, config.id, {
          status: "RUNNING",
          currentTaskId: taskId,
          lastHeartbeatAt: new Date(this.#now()),
        });
        await this.emitter.emit(
          {
            ...base,
            type: "TASK_ASSIGNED",
            payload: {
              objective: request.objective,
              assignedBy: request.assignedBy,
              inputs: request.inputs ?? {},
            },
          },
          tx,
        );
        await this.emitter.emit(
          {
            ...base,
            type: "TASK_STARTED",
            payload: { startedAt: new Date(startedAt), model: config.modelId ?? null },
          },
          tx,
        );
      },
    );

    const pump = new HeartbeatPump({
      config,
      taskId,
      parentTaskId,
      correlationId: request.correlationId,
      agents: this.#deps.agents,
      emitter: this.emitter,
      ...(this.#deps.logger ? { logger: this.#deps.logger } : {}),
      now: this.#now,
      onExternalHalt: (status) => {
        externalHalt = status;
        guard.abort(new Error(`agent moved to ${status} out of process`));
      },
    });
    pump.start();

    let stepsRun = 0;
    let terminal: { status: AgentRunStatus; reason?: BlockedReason; detail?: string } | undefined;
    const outputs: Record<string, unknown> = {};

    try {
      for (const [index, step] of request.steps.entries()) {
        // §11.4 — the check runs BEFORE and AFTER every step, in the loop, never in a prompt.
        const before = guard.check();
        if (before.halt) {
          terminal = { status: "BLOCKED", ...(before.reason ? { reason: before.reason } : {}), ...(before.detail ? { detail: before.detail } : {}) };
          break;
        }
        if (externalHalt) break;

        const result = await step({
          config,
          taskId,
          correlationId: request.correlationId,
          step: index,
          signal: guard.signal,
          systemPrompt: buildSystemPrompt(config),
          remainingMs: guard.remainingMs(),
          tokensUsedSoFar: guard.tokensUsed,
          costUsdSoFar: guard.costUsd,
        });
        stepsRun += 1;
        guard.addUsage(result.tokensUsed ?? 0, result.costUsd ?? 0);
        Object.assign(outputs, result.outputs ?? {});

        await this.emitter.emit({
          ...base,
          type: "TASK_PROGRESS",
          tokensUsed: result.tokensUsed ?? null,
          estimatedCostUsd: result.costUsd ?? null,
          payload: {
            step: index,
            note: result.note,
            percentComplete: result.percentComplete ?? null,
          },
        });

        if (result.requestInformation) {
          await this.emitter.emit({
            ...base,
            type: "INFORMATION_REQUIRED",
            payload: {
              question: result.requestInformation.question,
              fields: result.requestInformation.fields ?? [],
            },
          });
          terminal = { status: "BLOCKED", reason: "dependency", detail: "information required" };
          break;
        }

        if (result.requestApproval) {
          // FR-071: persisted, and nothing else happens until Phase 2.
          await this.emitter.emit({
            ...base,
            type: "APPROVAL_REQUIRED",
            payload: {
              action: result.requestApproval.action,
              rationale: result.requestApproval.rationale,
              riskNote: result.requestApproval.riskNote ?? null,
            },
          });
          terminal = { status: "BLOCKED", reason: "dependency", detail: "approval required" };
          break;
        }

        if (result.blocked) {
          terminal = { status: "BLOCKED", reason: result.blocked.reason, detail: result.blocked.detail };
          break;
        }

        const after = guard.check();
        if (after.halt) {
          terminal = { status: "BLOCKED", ...(after.reason ? { reason: after.reason } : {}), ...(after.detail ? { detail: after.detail } : {}) };
          break;
        }

        if (result.done) break;
      }

      if (!terminal && externalHalt) {
        terminal = {
          status: "FAILED",
          detail: `agent moved to ${externalHalt} out of process`,
        };
      }
      terminal ??= { status: "COMPLETED" };
    } catch (error) {
      terminal = {
        status: "FAILED",
        detail: isSunilError(error) ? error.code : error instanceof Error ? error.name : "unknown",
      };
      this.#logger.error(
        {
          agentId: config.id,
          taskId,
          correlationId: request.correlationId,
          error: error instanceof Error ? error.name : "unknown",
        },
        "agent step threw; the run is failing",
      );
    } finally {
      pump.stop();
    }

    const durationMs = this.#now() - startedAt;
    await this.#finish(request, config, base, terminal, { durationMs, outputs, guard, error: undefined });

    return {
      taskId,
      status: terminal.status,
      ...(terminal.reason ? { blockedReason: terminal.reason } : {}),
      ...(terminal.detail ? { detail: terminal.detail } : {}),
      stepsRun,
      tokensUsed: guard.tokensUsed,
      costUsd: guard.costUsd,
      envelopes: this.emitter.emitted,
      durationMs,
    };
  }

  /** Terminal envelope + status transition + audit record, in one transaction. */
  async #finish(
    request: AgentRunRequest,
    config: AgentConfig,
    base: { agentId: string; taskId: string; parentTaskId: string | null; correlationId: string },
    terminal: { status: AgentRunStatus; reason?: BlockedReason; detail?: string },
    context: {
      durationMs: number;
      outputs: Record<string, unknown>;
      guard: RunGuard;
      error: unknown;
    },
  ): Promise<void> {
    const status = terminal.status === "FAILED" ? "FAILED" : "IDLE";

    await this.#deps.uow.runAudited(
      this.#auditEntry(config, request.correlationId, "finish", {
        status,
        taskId: base.taskId,
        outcome: terminal.status,
        blockedReason: terminal.reason ?? null,
        tokensUsed: context.guard.tokensUsed,
        estimatedCostUsd: context.guard.costUsd,
      }),
      async (tx) => {
        await this.#deps.agents.update(tx, config.id, { status, currentTaskId: null });

        const envelope = {
          ...base,
          tokensUsed: context.guard.tokensUsed,
          estimatedCostUsd: context.guard.costUsd,
        };

        if (terminal.status === "COMPLETED") {
          await this.emitter.emit(
            {
              ...envelope,
              type: "TASK_COMPLETED",
              payload: {
                summary: `Completed ${request.steps.length} configured step(s).`,
                outputs: context.outputs,
                durationMs: context.durationMs,
              },
            },
            tx,
          );
        } else if (terminal.status === "BLOCKED") {
          await this.emitter.emit(
            {
              ...envelope,
              type: "TASK_BLOCKED",
              payload: {
                reason: terminal.reason ?? "error",
                detail: terminal.detail ?? "run halted",
              },
            },
            tx,
          );
        } else {
          await this.emitter.emit(
            {
              ...envelope,
              type: "TASK_FAILED",
              payload: {
                errorClass: terminal.detail ?? "unknown",
                message: terminal.detail ?? "agent run failed",
                retryable: false,
              },
            },
            tx,
          );
        }
      },
    );
  }

  #auditEntry(
    config: AgentConfig,
    correlationId: string,
    phase: "start" | "finish",
    after: Record<string, unknown>,
  ): AuditEntry {
    return {
      actorType: "AGENT",
      actorId: config.id,
      actorLabel: config.slug,
      action: "agent.run",
      targetType: "agent",
      targetId: config.id,
      before: { phase },
      after,
      outcome: after["outcome"] === "FAILED" ? "FAILURE" : "SUCCESS",
      correlationId,
    };
  }
}
