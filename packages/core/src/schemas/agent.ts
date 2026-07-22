/**
 * Agent configuration contract (§11.1).
 *
 * `toolAllowlist` MUST be empty in Phase 1 (FR-070). That is enforced by this schema, so a
 * non-empty list fails to load and no partially configured agent runs. Relaxing it is a
 * Phase 2 change to this file, reviewed as such — not a call-site override.
 */
import { z } from "../zod.js";
import { UuidSchema } from "./common.js";

export const AGENT_STATUSES = ["IDLE", "RUNNING", "STALE", "FAILED", "DISABLED"] as const;
export const AgentStatusSchema = z.enum(AGENT_STATUSES);

export const AgentSlugSchema = z
  .string()
  .trim()
  .min(1)
  .max(100)
  .regex(/^[a-z0-9][a-z0-9-]*$/, { message: "must be lowercase kebab-case" });

/** Phase 1: the allowlist exists in the schema but may only ever be empty. */
export const ToolAllowlistSchema = z
  .array(z.string())
  .max(0, { message: "tool use is Phase 2; the allowlist must be empty in Phase 1 (FR-070)" })
  .default([]);

export const AgentConfigSchema = z.object({
  id: UuidSchema,
  slug: AgentSlugSchema,
  name: z.string().trim().min(1).max(200),
  role: z.string().trim().min(1).max(500),
  systemInstructions: z.string().min(1).max(50_000),
  toolAllowlist: ToolAllowlistSchema,
  providerId: UuidSchema.nullish(),
  modelId: z.string().trim().min(1).max(200).nullish(),
  maxDurationSeconds: z.number().int().positive().max(86_400),
  tokenBudget: z.number().int().positive().nullish(),
  costBudgetUsd: z.number().nonnegative().nullish(),
  heartbeatIntervalSeconds: z.number().int().positive().max(3600),
  staleThresholdSeconds: z.number().int().positive().max(86_400),
  enabled: z.boolean().default(true),
});

export type AgentConfig = z.infer<typeof AgentConfigSchema>;

export const AgentCreateSchema = AgentConfigSchema.omit({ id: true }).partial({
  toolAllowlist: true,
  enabled: true,
});

export const AgentUpdateSchema = AgentCreateSchema.partial().refine(
  (value) => Object.keys(value).length > 0,
  { message: "at least one field must be supplied" },
);

/**
 * Load and validate an agent configuration. On failure the offending field is named and
 * NOTHING partially configured is returned (§11.1).
 */
export function loadAgentConfig(
  input: unknown,
): { ok: true; config: AgentConfig } | { ok: false; issues: string[] } {
  const result = AgentConfigSchema.safeParse(input);
  if (result.success) return { ok: true, config: result.data };
  return {
    ok: false,
    issues: result.error.issues.map(
      (issue) => `${issue.path.join(".") || "<root>"}: ${issue.message}`,
    ),
  };
}
