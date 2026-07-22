/**
 * `@sunil/agents` — the agent runtime skeleton (§11).
 *
 * An agent is a CONFIGURATION RECORD, not code: one loop runs every agent (FR-070). Envelopes
 * are the nine Zod types from `@sunil/core`, persisted to Postgres (FR-072). Heartbeats make a
 * running agent observable and the out-of-process staleness sweep makes a SILENT one
 * detectable as failed (FR-073). Budgets and timeouts are enforced IN THE LOOP, never as
 * prompt text (FR-074).
 *
 * Scope fence (§18.9): no chat, tasks, memory retrieval, routing or approval workflow.
 * `APPROVAL_REQUIRED` persists and nothing else happens (FR-071).
 */
export const PACKAGE_NAME = "@sunil/agents" as const;

export {
  agentRowToConfigInput,
  buildSystemPrompt,
  loadAgentConfigFromRow,
  requireAgentConfig,
} from "./config.js";

export { EnvelopeEmitter, toCreateInput } from "./envelopes.js";
export type { EnvelopeEmitterDeps } from "./envelopes.js";

export { RunGuard } from "./budget.js";
export type { HaltDecision } from "./budget.js";

export { HeartbeatPump } from "./heartbeat.js";
export type { HeartbeatPumpDeps } from "./heartbeat.js";

export { AgentRuntime } from "./runtime.js";
export type {
  AgentRunOutcome,
  AgentRunRequest,
  AgentRunStatus,
  AgentRuntimeDeps,
  AgentStep,
  AgentStepContext,
  AgentStepResult,
} from "./runtime.js";

export { StaleAgentSweeper } from "./staleness.js";
export type { StaleAgentSweeperDeps, StaleSweepResult } from "./staleness.js";

export type { AgentMessageStore, AgentStore, AuditedRunner } from "./ports.js";

export { NOOP_AGENT_LOGGER } from "./logging.js";
export type { AgentLogger } from "./logging.js";
