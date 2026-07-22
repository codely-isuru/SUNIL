/**
 * Pure domain types — NO runtime code, NO Zod, NO server dependencies.
 *
 * This module is one of the two paths `packages/ui` is permitted to import from
 * `@sunil/core` (PHASE1_ARCHITECTURE §3.2; the other is `./tokens`). Keep it free of
 * anything that would drag server schemas into a client bundle.
 */

/** Presentation-safe user projection. Never carries `passwordHash`. */
export interface UserSummary {
  readonly id: string;
  readonly email: string;
  readonly displayName: string;
  readonly status: UserStatus;
  readonly timezone: string;
  readonly mfaEnabled: boolean;
  readonly createdAt: string;
}

export interface RoleSummary {
  readonly id: string;
  readonly slug: RoleSlug;
  readonly name: string;
  readonly description: string;
  readonly isSystem: boolean;
}

/** Generic pagination envelope used by every list endpoint. */
export interface Paged<T> {
  readonly items: readonly T[];
  readonly page: number;
  readonly pageSize: number;
  readonly total: number;
  readonly hasMore: boolean;
}

export interface PageRequest {
  readonly page: number;
  readonly pageSize: number;
}

export type UserStatus = "ACTIVE" | "DISABLED";
export type SessionState = "PENDING_MFA" | "ACTIVE" | "REVOKED";
export type MfaStatus = "PENDING" | "ACTIVE";
export type ProviderVerification = "UNCONFIGURED" | "MOCK_VERIFIED" | "LIVE_VERIFIED";
export type ActorType = "HUMAN" | "AGENT" | "SYSTEM";
export type AuditOutcome = "SUCCESS" | "FAILURE";
export type AgentStatus = "IDLE" | "RUNNING" | "STALE" | "FAILED" | "DISABLED";
export type JobOutcome = "RUNNING" | "COMPLETED" | "FAILED" | "TIMED_OUT" | "STALLED";
export type RoleSlug = "owner" | "admin" | "viewer" | "agent";
export type ProviderSlug = "anthropic" | "openai" | "ollama";

/** Categories only — a denial never leaks *which* check failed in detail (FR-026). */
export type DenialReason =
  | "unauthenticated"
  | "forbidden"
  | "csrf"
  | "rate_limited"
  | "locked_out"
  | "validation";

export type EnvelopeType =
  | "TASK_ASSIGNED"
  | "TASK_STARTED"
  | "TASK_PROGRESS"
  | "INFORMATION_REQUIRED"
  | "APPROVAL_REQUIRED"
  | "TASK_BLOCKED"
  | "TASK_COMPLETED"
  | "TASK_FAILED"
  | "AGENT_HEARTBEAT";

/** Anything carrying request/job correlation for NFR-012 traceability. */
export interface Correlated {
  readonly correlationId: string;
}

/** JSON value type used for audit before/after payloads and settings values. */
export type JsonPrimitive = string | number | boolean | null;
export type JsonValue = JsonPrimitive | JsonValue[] | { [key: string]: JsonValue };
