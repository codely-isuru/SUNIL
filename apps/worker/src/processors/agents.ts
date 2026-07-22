/**
 * `agents` queue processor (§11.3 — "agent execution is a BullMQ job on the `agents` queue").
 *
 * The processor is deliberately thin: validate the job payload, hydrate the agent CONFIG from
 * its row, and hand it to `AgentRuntime.run`. There is no agent-specific branch here — a
 * second agent with different configuration runs through the same call (FR-070).
 *
 * PHASE 1 LIMITATION (honest, not hidden): the steps a run executes come from an injected
 * `stepFactory`, and the default factory performs NO LLM CALL. `SecretStore`'s envelope
 * implementation is DI-provided on the API side (§8.1) and is not available to this process,
 * and re-implementing envelope decryption here to reach a provider would be worse than having
 * no provider. The seam is one function: supply a `stepFactory` that closes over an
 * `LLMProvider` from `@sunil/llm` and agent runs make real completions with no other change.
 */
import { ValidationError, z } from "@sunil/core";
import type { AgentConfig } from "@sunil/core";
import type { AgentRepository } from "@sunil/db";
import { requireAgentConfig, type AgentRunOutcome, type AgentRuntime, type AgentStep } from "@sunil/agents";
import type { AppLogger } from "../logger.js";

export const AgentRunJobDataSchema = z.object({
  agentId: z.uuid(),
  objective: z.string().min(1).max(4000),
  assignedBy: z.string().min(1).max(200),
  correlationId: z.string().min(1).max(128),
  taskId: z.uuid().optional(),
  parentTaskId: z.uuid().nullish(),
  inputs: z.record(z.string(), z.unknown()).default({}),
});

export type AgentRunJobData = z.input<typeof AgentRunJobDataSchema>;

/** Builds the steps a run executes. The injection point for a real provider call. */
export type AgentStepFactory = (config: AgentConfig) => readonly AgentStep[];

/**
 * The Phase 1 default: one step that records that the runtime executed, consuming no tokens.
 * It exercises the loop, the envelopes, the heartbeats and the guards without inventing a
 * workload the phase does not have.
 */
export const noWorkloadStepFactory: AgentStepFactory = (config) => [
  () =>
    Promise.resolve({
      note: `runtime executed for agent '${config.slug}'; Phase 1 performs no model call`,
      tokensUsed: 0,
      costUsd: 0,
      percentComplete: 100,
      done: true,
    }),
];

export interface AgentRunDeps {
  readonly runtime: AgentRuntime;
  readonly agents: AgentRepository;
  readonly logger: AppLogger;
  readonly stepFactory?: AgentStepFactory;
}

export async function runAgentJob(deps: AgentRunDeps, data: unknown): Promise<AgentRunOutcome> {
  const parsed = AgentRunJobDataSchema.safeParse(data);
  if (!parsed.success) {
    throw new ValidationError(
      "agent-run job payload failed validation",
      parsed.error.issues.map((issue) => issue.path.join(".") || "<root>"),
    );
  }
  const payload = parsed.data;

  const row = await deps.agents.findById(payload.agentId);
  if (!row) throw new ValidationError("agent-run job references an unknown agent", ["agentId"]);

  // Validation failure names the field and no partially configured agent runs (FR-070).
  const config: AgentConfig = requireAgentConfig(row);
  const steps = (deps.stepFactory ?? noWorkloadStepFactory)(config);

  const outcome = await deps.runtime.run({
    config,
    objective: payload.objective,
    assignedBy: payload.assignedBy,
    correlationId: payload.correlationId,
    ...(payload.taskId ? { taskId: payload.taskId } : {}),
    parentTaskId: payload.parentTaskId ?? null,
    inputs: payload.inputs,
    steps,
  });

  deps.logger.info(
    {
      agentId: config.id,
      taskId: outcome.taskId,
      status: outcome.status,
      correlationId: payload.correlationId,
    },
    "agent run finished",
  );

  return outcome;
}
