/**
 * The thin HTTP client. One place that knows how to reach `apps/api`, so pointing the portal
 * at the real service is a configuration change rather than an edit to every screen.
 *
 * Written against the PHASE1_ARCHITECTURE §13 contract and ADR-011. Every screen that uses it
 * renders a real loading state and a real error state, because a UI built on the assumption of
 * success is a UI whose failure paths are discovered in production.
 *
 * Rules this file exists to keep in one place:
 *   - **ADR-011 / A1 — same-origin, no CORS.** In the browser every request is a RELATIVE
 *     `/api/...` path that `next.config.mjs` rewrites to the API on the private network, so
 *     `credentials: "same-origin"` is all that is needed to carry the httpOnly session cookie
 *     and no API origin exists in the client bundle. Server components pass `cookie` and the
 *     base URL resolves from `SUNIL_API_INTERNAL_URL` instead. The client keeps NO copy of
 *     anything authentication-related in JavaScript-readable storage (§11.8, FR-105).
 *   - `X-CSRF-Token` on every mutating request (ADR-009 / §6.5, amendment A2: the header
 *     token is the whole control in Phase 1 — there is no `Origin` check). The token comes
 *     from the login / mfa-verify response body or `GET /auth/me`. **It rotates on MFA
 *     elevation**, along with the session token, so a caller must re-read it after
 *     `/auth/mfa/verify` rather than reuse the pre-elevation value. A missing or wrong token
 *     is a 403.
 *   - Failures are reduced to a CATEGORY. The API's message is not surfaced verbatim on the
 *     auth screens: FR-022 / FR-104 require one generic sign-in failure for wrong password,
 *     unknown email, disabled account and expired invitation alike.
 */
import { resolveApiBaseUrl } from "../../config";
import type {
  ApiFailure,
  ApiResult,
  JobsStatusResponse,
  LoginResponse,
  MeResponse,
  MfaVerifyResponse,
  ProviderSummary,
  SessionSummary,
  SystemHealthResponse,
} from "./types";

export interface RequestOptions {
  readonly method?: "GET" | "POST" | "PUT" | "PATCH" | "DELETE";
  readonly body?: unknown;
  readonly csrfToken?: string;
  /** Forwarded by server components so the API sees the caller's session (§14). */
  readonly cookie?: string;
  readonly signal?: AbortSignal;
  /** Defaults to 10s — the §7.1 watchdog for a server that never answers. */
  readonly timeoutMs?: number;
}

const DEFAULT_TIMEOUT_MS = 10_000;

function classify(status: number): ApiFailure["kind"] {
  if (status === 401) return "unauthorized";
  if (status === 403) return "forbidden";
  if (status === 404) return "not_found";
  if (status === 429 || status === 423) return "rate_limited";
  if (status >= 500) return "server";
  return "unknown";
}

export async function apiRequest<T>(path: string, options: RequestOptions = {}): Promise<ApiResult<T>> {
  const method = options.method ?? "GET";
  const url = `${resolveApiBaseUrl()}${path}`;
  const controller = new AbortController();
  const timeout = setTimeout(() => {
    controller.abort();
  }, options.timeoutMs ?? DEFAULT_TIMEOUT_MS);

  const headers: Record<string, string> = { Accept: "application/json" };
  if (options.body !== undefined) headers["Content-Type"] = "application/json";
  if (options.csrfToken) headers["X-CSRF-Token"] = options.csrfToken;
  if (options.cookie) headers["Cookie"] = options.cookie;

  try {
    const response = await fetch(url, {
      method,
      headers,
      credentials: "same-origin",
      cache: "no-store",
      signal: options.signal ?? controller.signal,
      body: options.body === undefined ? undefined : JSON.stringify(options.body),
    });

    if (!response.ok) {
      const retryAfter = response.headers.get("Retry-After");
      const failure: ApiFailure = {
        ok: false,
        kind: classify(response.status),
        status: response.status,
        ...(retryAfter === null ? {} : { retryAfterSeconds: Number.parseInt(retryAfter, 10) }),
      };
      return failure;
    }

    if (response.status === 204) return { ok: true, data: undefined as T };
    const data = (await response.json()) as T;
    return { ok: true, data };
  } catch (error) {
    const aborted = error instanceof Error && error.name === "AbortError";
    return { ok: false, kind: aborted ? "timeout" : "network" };
  } finally {
    clearTimeout(timeout);
  }
}

/* ---------------------------------------------------------------------- */
/* The Phase 1 calls, one per §13 route the portal actually uses.          */
/* ---------------------------------------------------------------------- */

export function login(email: string, password: string): Promise<ApiResult<LoginResponse>> {
  return apiRequest<LoginResponse>("/auth/login", {
    method: "POST",
    body: { email, password },
  });
}

export function verifyMfa(
  payload: { code: string } | { recoveryCode: string },
  csrfToken?: string,
): Promise<ApiResult<MfaVerifyResponse>> {
  return apiRequest<MfaVerifyResponse>("/auth/mfa/verify", {
    method: "POST",
    body: payload,
    ...(csrfToken === undefined ? {} : { csrfToken }),
  });
}

export function acceptInvitation(
  token: string,
  password: string,
): Promise<ApiResult<{ ok: true }>> {
  return apiRequest<{ ok: true }>(`/invitations/${encodeURIComponent(token)}/accept`, {
    method: "POST",
    body: { password },
  });
}

export function logout(csrfToken?: string): Promise<ApiResult<void>> {
  return apiRequest<void>("/auth/logout", {
    method: "POST",
    ...(csrfToken === undefined ? {} : { csrfToken }),
  });
}

export function fetchMe(cookie?: string): Promise<ApiResult<MeResponse>> {
  return apiRequest<MeResponse>("/auth/me", {
    ...(cookie === undefined ? {} : { cookie }),
    timeoutMs: 4000,
  });
}

export function fetchSystemHealth(cookie?: string): Promise<ApiResult<SystemHealthResponse>> {
  return apiRequest<SystemHealthResponse>("/system-health", {
    ...(cookie === undefined ? {} : { cookie }),
    timeoutMs: 6000,
  });
}

export function fetchJobsStatus(): Promise<ApiResult<JobsStatusResponse>> {
  return apiRequest<JobsStatusResponse>("/jobs/status", { timeoutMs: 6000 });
}

export function fetchProviders(): Promise<ApiResult<readonly ProviderSummary[]>> {
  return apiRequest<readonly ProviderSummary[]>("/providers", { timeoutMs: 6000 });
}

export function fetchSessions(): Promise<ApiResult<readonly SessionSummary[]>> {
  return apiRequest<readonly SessionSummary[]>("/auth/sessions", { timeoutMs: 6000 });
}

export function saveSetting(
  key: string,
  value: unknown,
  csrfToken?: string,
): Promise<ApiResult<void>> {
  return apiRequest<void>(`/settings/${encodeURIComponent(key)}`, {
    method: "PUT",
    body: { value },
    ...(csrfToken === undefined ? {} : { csrfToken }),
  });
}
