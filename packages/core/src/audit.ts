/**
 * Audit contracts — PHASE1_ARCHITECTURE §9.1, ADR-005.
 *
 * There is deliberately NO timestamp field on `AuditEntry`. The audit service generates
 * `createdAt` server-side and the caller has no way to supply one (FR-050). A test asserts
 * this, so re-adding one is a build failure, not a review comment.
 */
import { z } from "./zod.js";
import type { ActorType, AuditOutcome, DenialReason } from "./types.js";

export const ACTOR_TYPES = ["HUMAN", "AGENT", "SYSTEM"] as const;
export const ActorTypeSchema = z.enum(ACTOR_TYPES);

export const AUDIT_OUTCOMES = ["SUCCESS", "FAILURE"] as const;
export const AuditOutcomeSchema = z.enum(AUDIT_OUTCOMES);

/** Categories only — never a human-readable reason that leaks resource existence. */
export const DENIAL_REASONS = [
  "unauthenticated",
  "forbidden",
  "csrf",
  "rate_limited",
  "locked_out",
  "validation",
] as const;
export const DenialReasonSchema = z.enum(DENIAL_REASONS);

const _actorParity: readonly ActorType[] = ACTOR_TYPES;
const _outcomeParity: readonly AuditOutcome[] = AUDIT_OUTCOMES;
const _denialParity: readonly DenialReason[] = DENIAL_REASONS;
void _actorParity;
void _outcomeParity;
void _denialParity;

/**
 * The audit action catalogue. New actions are added HERE, not invented at a call site —
 * the same discipline as the permission catalogue (risk R-08).
 */
export const AUDIT_ACTIONS = [
  // authentication
  "auth.login.success",
  "auth.login.failure",
  "auth.login.lockout",
  "auth.logout",
  "auth.session.revoke",
  "auth.password.change",
  "auth.mfa.enrol",
  "auth.mfa.activate",
  "auth.mfa.verify.success",
  "auth.mfa.verify.failure",
  "auth.mfa.disable",
  "auth.denied",
  // identity
  "user.create",
  "user.update",
  "user.role.change",
  "user.lockout.clear",
  "invitation.create",
  "invitation.accept",
  "invitation.revoke",
  // secrets
  "secret.create",
  "secret.read",
  "secret.rotate",
  "secret.delete",
  // configuration
  "settings.update",
  "provider.update",
  // agents and jobs
  "agent.create",
  "agent.update",
  "agent.run",
  "agent.stale",
  "job.execute",
  // Repeatable-schedule lifecycle (ADR-010). The scheduler's boot sequence is two distinct
  // actions and they audit separately: it upserts every code-defined Job Scheduler, then
  // reconciles away any scheduler id no longer present in the code-defined set. Recording
  // both under one verb would make "a definition disappeared" indistinguishable from
  // "a definition was re-registered" in the log.
  "job.scheduler.register",
  "job.scheduler.reconcile",
  // bootstrap
  "system.bootstrap",
] as const;

export type AuditAction = (typeof AUDIT_ACTIONS)[number];
export const AuditActionSchema = z.enum(AUDIT_ACTIONS);

/**
 * What a mutation records. `before`/`after` are redacted (§9.5) before they are persisted.
 * NOTE the absence of any timestamp field — that is FR-050, not an oversight.
 */
export const AuditEntrySchema = z.object({
  actorType: ActorTypeSchema,
  actorId: z.string().nullish(),
  /** Denormalised display label; survives deletion of the actor row. */
  actorLabel: z.string().min(1).max(320),
  action: AuditActionSchema,
  targetType: z.string().max(100).nullish(),
  targetId: z.string().max(200).nullish(),
  before: z.unknown().nullish(),
  after: z.unknown().nullish(),
  outcome: AuditOutcomeSchema.default("SUCCESS"),
  denialReason: DenialReasonSchema.nullish(),
  correlationId: z.string().min(1).max(128),
  ip: z.string().max(64).nullish(),
  userAgent: z.string().max(1024).nullish(),
});

export type AuditEntry = z.input<typeof AuditEntrySchema>;
export type ParsedAuditEntry = z.output<typeof AuditEntrySchema>;

/** A denial carries no domain mutation, so it is always FAILURE with a category (§9.2). */
export const DenialEntrySchema = AuditEntrySchema.extend({
  outcome: z.literal("FAILURE").default("FAILURE"),
  denialReason: DenialReasonSchema,
});

export type DenialEntry = z.input<typeof DenialEntrySchema>;

export const AuditFilterSchema = z.object({
  actorId: z.string().optional(),
  actorType: ActorTypeSchema.optional(),
  action: AuditActionSchema.optional(),
  targetType: z.string().optional(),
  targetId: z.string().optional(),
  outcome: AuditOutcomeSchema.optional(),
  correlationId: z.string().optional(),
  from: z.coerce.date().optional(),
  to: z.coerce.date().optional(),
});

export type AuditFilter = z.infer<typeof AuditFilterSchema>;

export function isAuditAction(value: string): value is AuditAction {
  return (AUDIT_ACTIONS as readonly string[]).includes(value);
}
