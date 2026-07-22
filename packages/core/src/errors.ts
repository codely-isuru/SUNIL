/**
 * Error taxonomy.
 *
 * Every error crossing a module boundary is one of these. Two properties matter:
 *  - `code` — a stable machine string, safe to log and to map to an audit denial category.
 *  - `httpStatus` — what the API returns. Response BODIES are generic (FR-026): the
 *    `message` here is for logs, never for leaking resource existence to a caller.
 */
import type { DenialReason, ProviderSlug } from "./types.js";

export type ErrorCode =
  | "VALIDATION_FAILED"
  | "UNAUTHENTICATED"
  | "FORBIDDEN"
  | "CSRF_FAILED"
  | "RATE_LIMITED"
  | "LOCKED_OUT"
  | "NOT_FOUND"
  | "CONFLICT"
  | "INVARIANT_VIOLATION"
  | "CONFIGURATION_INVALID"
  | "SECRET_INTEGRITY"
  | "SECRET_NOT_FOUND"
  | "AUDIT_WRITE_FAILED"
  | "CAPABILITY_NOT_SUPPORTED"
  | "PROVIDER_ERROR"
  | "BUDGET_EXCEEDED"
  | "DEADLINE_EXCEEDED"
  | "INTERNAL";

export abstract class SunilError extends Error {
  abstract readonly code: ErrorCode;
  abstract readonly httpStatus: number;
  /** Audit denial category, when this error represents a denied request (§9.1). */
  readonly denialReason?: DenialReason;

  constructor(message: string, options?: { cause?: unknown }) {
    super(message, options);
    this.name = new.target.name;
    Object.setPrototypeOf(this, new.target.prototype);
  }

  /** Generic, non-leaking body shape returned to callers. */
  toPublicBody(): { error: ErrorCode } {
    return { error: this.code };
  }
}

export class ValidationError extends SunilError {
  readonly code = "VALIDATION_FAILED" as const;
  readonly httpStatus = 400;
  override readonly denialReason: DenialReason = "validation";
  /** Field paths only — never the offending values (they may be secret material). */
  readonly fields: readonly string[];

  constructor(message: string, fields: readonly string[] = [], options?: { cause?: unknown }) {
    super(message, options);
    this.fields = fields;
  }
}

export class UnauthenticatedError extends SunilError {
  readonly code = "UNAUTHENTICATED" as const;
  readonly httpStatus = 401;
  override readonly denialReason: DenialReason = "unauthenticated";
}

export class ForbiddenError extends SunilError {
  readonly code = "FORBIDDEN" as const;
  readonly httpStatus = 403;
  override readonly denialReason: DenialReason = "forbidden";
}

export class CsrfError extends SunilError {
  readonly code = "CSRF_FAILED" as const;
  readonly httpStatus = 403;
  override readonly denialReason: DenialReason = "csrf";
}

export class RateLimitedError extends SunilError {
  readonly code = "RATE_LIMITED" as const;
  readonly httpStatus = 429;
  override readonly denialReason: DenialReason = "rate_limited";
  readonly retryAfterSeconds: number;

  constructor(retryAfterSeconds: number, message = "Rate limit exceeded") {
    super(message);
    this.retryAfterSeconds = retryAfterSeconds;
  }
}

export class LockedOutError extends SunilError {
  readonly code = "LOCKED_OUT" as const;
  readonly httpStatus = 429;
  override readonly denialReason: DenialReason = "locked_out";
  readonly retryAfterSeconds: number;

  constructor(retryAfterSeconds: number, message = "Account temporarily locked") {
    super(message);
    this.retryAfterSeconds = retryAfterSeconds;
  }
}

export class NotFoundError extends SunilError {
  readonly code = "NOT_FOUND" as const;
  readonly httpStatus = 404;
}

export class ConflictError extends SunilError {
  readonly code = "CONFLICT" as const;
  readonly httpStatus = 409;
}

/** A domain invariant was violated (e.g. attempting to create a second owner). */
export class InvariantViolationError extends SunilError {
  readonly code = "INVARIANT_VIOLATION" as const;
  readonly httpStatus = 409;
}

/** Thrown at process start by env validation. Names the variable, never its value (FR-004). */
export class ConfigurationError extends SunilError {
  readonly code = "CONFIGURATION_INVALID" as const;
  readonly httpStatus = 500;
  readonly variables: readonly string[];

  constructor(message: string, variables: readonly string[] = []) {
    super(message);
    this.variables = variables;
  }
}

/**
 * Envelope decryption or auth-tag verification failed. Returns NOTHING partial and is
 * audited (§8.2, ET-5 5.9).
 */
export class SecretIntegrityError extends SunilError {
  readonly code = "SECRET_INTEGRITY" as const;
  readonly httpStatus = 500;
  readonly secretName: string;

  constructor(secretName: string, message = "Secret integrity check failed") {
    super(message);
    this.secretName = secretName;
  }
}

export class SecretNotFoundError extends SunilError {
  readonly code = "SECRET_NOT_FOUND" as const;
  readonly httpStatus = 404;
  readonly secretName: string;

  constructor(secretName: string) {
    super("Secret not found");
    this.secretName = secretName;
  }
}

/**
 * The audit insert inside an audited transaction failed, so the whole transaction rolled
 * back and the mutation did NOT happen (ADR-005). The caller sees a generic 500.
 */
export class AuditWriteFailedError extends SunilError {
  readonly code = "AUDIT_WRITE_FAILED" as const;
  readonly httpStatus = 500;

  constructor(message = "Operation not recorded", options?: { cause?: unknown }) {
    super(message, options);
  }
}

/** An undeclared LLM capability was invoked (FR-060). */
export class CapabilityNotSupportedError extends SunilError {
  readonly code = "CAPABILITY_NOT_SUPPORTED" as const;
  readonly httpStatus = 501;
  readonly provider: string;
  readonly capability: string;

  constructor(provider: string, capability: string) {
    super(`Provider ${provider} does not support capability ${capability}`);
    this.provider = provider;
    this.capability = capability;
  }
}

/** LLM provider error classes — mirrored by `usage_records.errorClass` (§10.3). */
export const PROVIDER_ERROR_CLASSES = [
  "auth",
  "rate_limit",
  "server",
  "timeout",
  "connectivity",
  "contract",
] as const;

export type ProviderErrorClass = (typeof PROVIDER_ERROR_CLASSES)[number];

/** Raw transport errors never escape an adapter — they are mapped to this (FR-061/063). */
export class ProviderError extends SunilError {
  readonly code = "PROVIDER_ERROR" as const;
  readonly httpStatus = 502;
  readonly provider: ProviderSlug;
  readonly status?: number;
  readonly errorClass: ProviderErrorClass;
  readonly retryable: boolean;

  constructor(args: {
    provider: ProviderSlug;
    errorClass: ProviderErrorClass;
    retryable: boolean;
    message: string;
    status?: number;
    cause?: unknown;
  }) {
    super(args.message, { cause: args.cause });
    this.provider = args.provider;
    this.errorClass = args.errorClass;
    this.retryable = args.retryable;
    if (args.status !== undefined) this.status = args.status;
  }
}

/** In-loop budget enforcement tripped (§11.4) — never enforced via prompt text. */
export class BudgetExceededError extends SunilError {
  readonly code = "BUDGET_EXCEEDED" as const;
  readonly httpStatus = 409;
  readonly kind: "tokens" | "cost";

  constructor(kind: "tokens" | "cost", message = "Agent budget exhausted") {
    super(message);
    this.kind = kind;
  }
}

/** In-loop timeout enforcement tripped (§11.4). */
export class DeadlineExceededError extends SunilError {
  readonly code = "DEADLINE_EXCEEDED" as const;
  readonly httpStatus = 504;
}

export class InternalError extends SunilError {
  readonly code = "INTERNAL" as const;
  readonly httpStatus = 500;
}

export function isSunilError(value: unknown): value is SunilError {
  return value instanceof SunilError;
}
