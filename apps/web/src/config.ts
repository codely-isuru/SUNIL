/**
 * `@sunil/web` configuration.
 *
 * This app holds NO secrets of any kind (§14, FR-105). If you find yourself reading
 * `SUNIL_MASTER_KEY`, a database URL or a provider key in this workspace, stop — the API is
 * the only process that may see those, and `SecretStore.get` is not importable here by design
 * (§8.4 fence 4, enforced by dependency-cruiser).
 *
 * ADR-011 / amendment A1 — SAME-ORIGIN, NO CORS.
 *
 *   - The BROWSER always fetches relative `/api/...` paths. Same origin, so no CORS, no
 *     credentialed cross-origin semantics, and `connect-src 'self'` in the CSP.
 *     `next.config.mjs` rewrites those paths to the API on the private network.
 *   - The SERVER (server components, route handlers) fetches `SUNIL_API_INTERNAL_URL`
 *     directly, forwarding the incoming session cookie.
 *   - There is NO public API-URL variable. A1 removed it from the configuration inventory
 *     (§16), and no API origin belongs in the client bundle. Nothing in this workspace may
 *     reintroduce a `NEXT_PUBLIC_*` API origin — that is what a cross-origin client would
 *     need, and adding one is forbidden as a drive-by change (a test enforces its absence).
 *
 * Other architectural constraints for this workspace, restated where they are easy to check:
 *   - Next 15 App Router. Middleware redirects unauthenticated visitors to the sign-in page
 *     (FR-101) — and the API enforces independently. The UI is never the control.
 *   - Nav filtering uses the `permissions` array from `GET /api/auth/me`. Hidden ≠ protected
 *     (ET-2 2.6).
 *   - Dark theme only, tokens from `@sunil/ui`. No brand colour literal outside the token
 *     definitions. No `dangerouslySetInnerHTML` (FR-031).
 *   - Nothing may state or imply that a Phase 2–7 capability exists (NFR-019).
 */

/** ADR-011 default for host-run dev; Compose sets `http://api:3001`. Server-side only. */
const DEFAULT_INTERNAL_API_ORIGIN = "http://localhost:3001";

/** Every Phase 1 route is under `/api` (PHASE1_ARCHITECTURE §13). */
export const API_BASE_PATH = "/api";

export interface WebConfig {
  /** Server-side only origin, e.g. `http://api:3001`. Never sent to the browser. */
  readonly internalApiOrigin: string;
  /** What server-side code prefixes onto a route path. */
  readonly serverApiBaseUrl: string;
  /** What browser code prefixes onto a route path — relative, always. */
  readonly clientApiBaseUrl: string;
}

/**
 * Strict read — throws when the internal origin is missing. Use at a boundary where a
 * misconfiguration should be loud, never inside a render path.
 */
export function readWebConfig(env: Record<string, string | undefined> = process.env): WebConfig {
  const internalApiOrigin = env["SUNIL_API_INTERNAL_URL"];
  if (!internalApiOrigin) {
    throw new Error("SUNIL_API_INTERNAL_URL is not set");
  }
  return {
    internalApiOrigin,
    serverApiBaseUrl: `${internalApiOrigin.replace(/\/$/, "")}${API_BASE_PATH}`,
    clientApiBaseUrl: API_BASE_PATH,
  };
}

/**
 * The base URL to prefix onto an API route path.
 *
 * In the browser this is ALWAYS the relative `/api` — there is deliberately no branch that
 * could put an absolute origin into a client-side request. On the server it resolves
 * `SUNIL_API_INTERNAL_URL`, tolerantly: a missing value must not blank the page, it must make
 * the request fail so the screen shows its ERROR state, which is a state the four-state
 * contract already requires us to have built.
 */
export function resolveApiBaseUrl(override?: string): string {
  if (typeof window !== "undefined") return API_BASE_PATH;
  const origin = override ?? process.env.SUNIL_API_INTERNAL_URL ?? DEFAULT_INTERNAL_API_ORIGIN;
  return `${origin.replace(/\/$/, "")}${API_BASE_PATH}`;
}
