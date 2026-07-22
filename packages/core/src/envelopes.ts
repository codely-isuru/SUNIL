/**
 * The nine agent message-envelope contracts (PHASE1_ARCHITECTURE §5.6/§11.2).
 *
 * Every emission goes through `runtime.emit(envelope)` → validate HERE → persist an
 * `agent_messages` row in Postgres (FR-072 — never in memory). A malformed envelope is
 * rejected before persist with the failing field named.
 *
 * `APPROVAL_REQUIRED` persists and NOTHING else happens: there is no approval workflow in
 * Phase 1 (FR-071). Do not add one here — it is Phase 2 and will be rejected at review.
 */
import { z } from "./zod.js";
import type { EnvelopeType } from "./types.js";

export const ENVELOPE_TYPES = [
  "TASK_ASSIGNED",
  "TASK_STARTED",
  "TASK_PROGRESS",
  "INFORMATION_REQUIRED",
  "APPROVAL_REQUIRED",
  "TASK_BLOCKED",
  "TASK_COMPLETED",
  "TASK_FAILED",
  "AGENT_HEARTBEAT",
] as const;

export const EnvelopeTypeSchema = z.enum(ENVELOPE_TYPES);

/** Compile-time proof that the Zod enum and the plain union cannot drift apart. */
const _envelopeTypeParity: readonly EnvelopeType[] = ENVELOPE_TYPES;
void _envelopeTypeParity;

/** Fields every envelope carries, regardless of type. */
const envelopeBase = {
  agentId: z.uuid(),
  taskId: z.uuid(),
  parentTaskId: z.uuid().nullish(),
  correlationId: z.string().min(1).max(128),
  tokensUsed: z.number().int().nonnegative().nullish(),
  estimatedCostUsd: z.number().nonnegative().nullish(),
};

/** Why a run halted. Enforcement is in the runtime loop, never in prompt text (FR-074). */
export const BLOCKED_REASONS = ["timeout", "budget", "dependency", "error"] as const;
export const BlockedReasonSchema = z.enum(BLOCKED_REASONS);
export type BlockedReason = (typeof BLOCKED_REASONS)[number];

export const TaskAssignedEnvelopeSchema = z.object({
  ...envelopeBase,
  type: z.literal("TASK_ASSIGNED"),
  payload: z.object({
    objective: z.string().min(1).max(4000),
    assignedBy: z.string().min(1).max(200),
    inputs: z.record(z.string(), z.unknown()).default({}),
  }),
});

export const TaskStartedEnvelopeSchema = z.object({
  ...envelopeBase,
  type: z.literal("TASK_STARTED"),
  payload: z.object({
    startedAt: z.coerce.date(),
    model: z.string().min(1).max(200).nullish(),
  }),
});

export const TaskProgressEnvelopeSchema = z.object({
  ...envelopeBase,
  type: z.literal("TASK_PROGRESS"),
  payload: z.object({
    step: z.number().int().nonnegative(),
    note: z.string().min(1).max(4000),
    percentComplete: z.number().min(0).max(100).nullish(),
  }),
});

export const InformationRequiredEnvelopeSchema = z.object({
  ...envelopeBase,
  type: z.literal("INFORMATION_REQUIRED"),
  payload: z.object({
    question: z.string().min(1).max(4000),
    fields: z.array(z.string().min(1).max(200)).default([]),
  }),
});

/** Persisted only. No approval workflow exists in Phase 1 (FR-071). */
export const ApprovalRequiredEnvelopeSchema = z.object({
  ...envelopeBase,
  type: z.literal("APPROVAL_REQUIRED"),
  payload: z.object({
    action: z.string().min(1).max(400),
    rationale: z.string().min(1).max(4000),
    riskNote: z.string().max(4000).nullish(),
  }),
});

export const TaskBlockedEnvelopeSchema = z.object({
  ...envelopeBase,
  type: z.literal("TASK_BLOCKED"),
  payload: z.object({
    reason: BlockedReasonSchema,
    detail: z.string().min(1).max(4000),
  }),
});

export const TaskCompletedEnvelopeSchema = z.object({
  ...envelopeBase,
  type: z.literal("TASK_COMPLETED"),
  payload: z.object({
    summary: z.string().min(1).max(8000),
    outputs: z.record(z.string(), z.unknown()).default({}),
    durationMs: z.number().int().nonnegative(),
  }),
});

export const TaskFailedEnvelopeSchema = z.object({
  ...envelopeBase,
  type: z.literal("TASK_FAILED"),
  payload: z.object({
    errorClass: z.string().min(1).max(100),
    /** Redacted before persist (§9.5). Never carries prompt or completion text. */
    message: z.string().min(1).max(4000),
    retryable: z.boolean(),
  }),
});

export const AgentHeartbeatEnvelopeSchema = z.object({
  ...envelopeBase,
  type: z.literal("AGENT_HEARTBEAT"),
  payload: z.object({
    emittedAt: z.coerce.date(),
    elapsedSeconds: z.number().int().nonnegative(),
  }),
});

/** The discriminated union every emission is validated against. */
export const AgentEnvelopeSchema = z.discriminatedUnion("type", [
  TaskAssignedEnvelopeSchema,
  TaskStartedEnvelopeSchema,
  TaskProgressEnvelopeSchema,
  InformationRequiredEnvelopeSchema,
  ApprovalRequiredEnvelopeSchema,
  TaskBlockedEnvelopeSchema,
  TaskCompletedEnvelopeSchema,
  TaskFailedEnvelopeSchema,
  AgentHeartbeatEnvelopeSchema,
]);

export type AgentEnvelope = z.infer<typeof AgentEnvelopeSchema>;
export type TaskAssignedEnvelope = z.infer<typeof TaskAssignedEnvelopeSchema>;
export type TaskStartedEnvelope = z.infer<typeof TaskStartedEnvelopeSchema>;
export type TaskProgressEnvelope = z.infer<typeof TaskProgressEnvelopeSchema>;
export type InformationRequiredEnvelope = z.infer<typeof InformationRequiredEnvelopeSchema>;
export type ApprovalRequiredEnvelope = z.infer<typeof ApprovalRequiredEnvelopeSchema>;
export type TaskBlockedEnvelope = z.infer<typeof TaskBlockedEnvelopeSchema>;
export type TaskCompletedEnvelope = z.infer<typeof TaskCompletedEnvelopeSchema>;
export type TaskFailedEnvelope = z.infer<typeof TaskFailedEnvelopeSchema>;
export type AgentHeartbeatEnvelope = z.infer<typeof AgentHeartbeatEnvelopeSchema>;

/** Per-type schema lookup, used by the runtime and by tests to prove all nine exist. */
export const ENVELOPE_SCHEMAS = {
  TASK_ASSIGNED: TaskAssignedEnvelopeSchema,
  TASK_STARTED: TaskStartedEnvelopeSchema,
  TASK_PROGRESS: TaskProgressEnvelopeSchema,
  INFORMATION_REQUIRED: InformationRequiredEnvelopeSchema,
  APPROVAL_REQUIRED: ApprovalRequiredEnvelopeSchema,
  TASK_BLOCKED: TaskBlockedEnvelopeSchema,
  TASK_COMPLETED: TaskCompletedEnvelopeSchema,
  TASK_FAILED: TaskFailedEnvelopeSchema,
  AGENT_HEARTBEAT: AgentHeartbeatEnvelopeSchema,
} as const;

/**
 * Validate an envelope, naming the failing field. Returns a discriminated result rather
 * than throwing so the caller can log the field and drop the envelope pre-persist.
 */
export function parseEnvelope(
  input: unknown,
): { ok: true; envelope: AgentEnvelope } | { ok: false; issues: string[] } {
  const result = AgentEnvelopeSchema.safeParse(input);
  if (result.success) return { ok: true, envelope: result.data };
  return {
    ok: false,
    issues: result.error.issues.map(
      (issue) => `${issue.path.join(".") || "<root>"}: ${issue.message}`,
    ),
  };
}
