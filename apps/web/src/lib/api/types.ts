/**
 * The API surface this portal consumes, transcribed from PHASE1_ARCHITECTURE §13.
 *
 * **`apps/api` does not exist yet** — it is being built concurrently (T3). Nothing here is
 * invented: every route, field and status below is named in §13. Where §13 does not specify a
 * shape, this file does NOT guess — see `SystemHealthResponse`, whose `deps` map §13 defines as
 * `{postgres, redis}` booleans and nothing more. The screens render every other dependency in
 * the UNKNOWN state rather than fabricating a value for it (NFR-019).
 *
 * `apps/web` talks to `apps/api` over HTTP, never by import (dependency-cruiser enforces it).
 */
import type { RoleSummary, UserSummary } from "@sunil/core/types";

/** `POST /auth/login` → `200 {user, mfaRequired, csrfToken?}` + cookie. */
export interface LoginResponse {
  readonly user: UserSummary;
  readonly mfaRequired: boolean;
  readonly csrfToken?: string;
}

/** `POST /auth/mfa/verify` → `200 {user, csrfToken}` + rotated cookie. */
export interface MfaVerifyResponse {
  readonly user: UserSummary;
  readonly csrfToken: string;
}

/** `GET /auth/me` → `{user, roles, permissions, csrfToken}`. */
export interface MeResponse {
  readonly user: UserSummary;
  readonly roles: readonly RoleSummary[];
  readonly permissions: readonly string[];
  readonly csrfToken: string;
}

/**
 * `GET /system-health` → `200 {status, deps: {postgres: 'up'|'down', redis: 'up'|'down'}}`.
 * "booleans only, no versions/connection detail (FR-091)" — and that constraint is a UI
 * constraint too: no host names, no connection strings, no version strings on screen.
 *
 * The route is public, and `/api/health` is an identical alias. The AS-BUILT healthy value is
 * the literal `"ok"` (confirmed against T3's finished API:
 * `{"status":"ok","deps":{"postgres":"up","redis":"up"}}`); `healthy` / `degraded` /
 * `unhealthy` are kept because §13 words the field that way, and an unrecognised value is
 * rendered as UNKNOWN rather than assumed good.
 */
export type DependencyState = "up" | "down";
export type HealthStatus = "ok" | "healthy" | "degraded" | "unhealthy";

export interface SystemHealthResponse {
  readonly status: HealthStatus;
  readonly deps: Readonly<Record<string, DependencyState>>;
}

/** `GET /jobs/status` (§12.5, FR-085), permission `job:read`. */
export interface JobsStatusResponse {
  readonly counts: {
    readonly waiting: number;
    readonly active: number;
    readonly completed: number;
    readonly failed: number;
    readonly delayed: number;
  };
  readonly repeatableKeys: readonly string[];
}

/** `GET /providers`, permission `provider:read`. */
export interface ProviderSummary {
  readonly id: string;
  readonly slug: string;
  readonly enabled: boolean;
  readonly defaultModel: string | null;
  /** A REFERENCE to a secret, never a secret (FR-042, FR-105). */
  readonly credentialName: string | null;
  /** §10.5 — the labelling mechanism behind FR-065. */
  readonly verification: "UNCONFIGURED" | "MOCK_VERIFIED" | "LIVE_VERIFIED";
}

/** `GET /auth/sessions` (self-service). */
export interface SessionSummary {
  readonly id: string;
  readonly device: string;
  readonly ip: string;
  readonly lastSeenAt: string;
  readonly current: boolean;
}

/** The error categories the UI distinguishes. Nothing here discloses account existence. */
export type ApiFailureKind =
  | "unauthorized"
  | "forbidden"
  | "rate_limited"
  | "not_found"
  | "server"
  | "network"
  | "timeout"
  | "unknown";

export interface ApiFailure {
  readonly ok: false;
  readonly kind: ApiFailureKind;
  /** HTTP status, when there was one. */
  readonly status?: number;
  /** `Retry-After` in seconds, for the FR-029 lockout message. */
  readonly retryAfterSeconds?: number;
}

export interface ApiSuccess<T> {
  readonly ok: true;
  readonly data: T;
}

export type ApiResult<T> = ApiSuccess<T> | ApiFailure;
