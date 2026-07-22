/**
 * Agent configuration hydration (§11.1, FR-070).
 *
 * "An agent is a configuration record, not code." This module turns an `Agent` ROW into a
 * validated `AgentConfig` using `loadAgentConfig` from `@sunil/core` — the schema, including
 * the Phase 1 rule that `toolAllowlist` must be EMPTY, lives there and is not re-implemented,
 * relaxed or overridden here.
 *
 * Validation failure names the offending field and returns nothing: no partially configured
 * agent ever runs.
 */
import { ValidationError, loadAgentConfig, type AgentConfig } from "@sunil/core";
import type { Agent } from "@sunil/db";

/**
 * `Decimal` and `Json` columns arrive as Prisma runtime types; normalise them to plain JSON
 * before validation so the schema sees exactly what it declares.
 */
export function agentRowToConfigInput(row: Agent): Record<string, unknown> {
  return {
    id: row.id,
    slug: row.slug,
    name: row.name,
    role: row.role,
    systemInstructions: row.systemInstructions,
    toolAllowlist: row.toolAllowlist ?? [],
    providerId: row.providerId,
    modelId: row.modelId,
    maxDurationSeconds: row.maxDurationSeconds,
    tokenBudget: row.tokenBudget,
    costBudgetUsd: row.costBudgetUsd === null ? null : Number(row.costBudgetUsd),
    heartbeatIntervalSeconds: row.heartbeatIntervalSeconds,
    staleThresholdSeconds: row.staleThresholdSeconds,
    enabled: row.enabled,
  };
}

/** Non-throwing form — mirrors `loadAgentConfig`'s discriminated result. */
export function loadAgentConfigFromRow(
  row: Agent,
): { ok: true; config: AgentConfig } | { ok: false; issues: string[] } {
  return loadAgentConfig(agentRowToConfigInput(row));
}

/**
 * Throwing form for the execution path: a `ValidationError` naming the invalid FIELD PATHS
 * (never the values, which could be sensitive).
 */
export function requireAgentConfig(row: Agent): AgentConfig {
  const result = loadAgentConfigFromRow(row);
  if (result.ok) return result.config;

  throw new ValidationError(
    `agent '${row.slug}' has an invalid configuration: ${result.issues.join("; ")}`,
    result.issues.map((issue) => issue.split(":")[0] ?? "<root>"),
  );
}

/**
 * The system prompt handed to a provider. It is the configured instructions VERBATIM.
 *
 * FR-074 / §11.4: budget and timeout limits are NEVER appended here as control text. The
 * model is not asked to self-limit; the runtime loop halts it. `runtime.test.ts` asserts that
 * this function adds nothing.
 */
export function buildSystemPrompt(config: AgentConfig): string {
  return config.systemInstructions;
}
