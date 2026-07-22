/**
 * Cookie mechanics (§6.1, FR-023).
 *
 * Hand-written rather than plugin-based for one boring reason: `@fastify/cookie` is not in
 * the lockfile and Phase 1 installs nothing. The surface needed is small and entirely
 * specified — one cookie, one name, fixed attributes — so a 40-line module is preferable to
 * a dependency negotiation. Values are base64url tokens, so no escaping question arises.
 */

export const SESSION_COOKIE_SECURE_NAME = "__Host-sunil_session";
export const SESSION_COOKIE_INSECURE_NAME = "sunil_session";

/**
 * `__Host-` is only legal with `Secure`, `Path=/` and no `Domain` — exactly the attributes
 * below — so the prefix is used only when the secure flag is on (§6.1).
 */
export function sessionCookieName(secure: boolean): string {
  return secure ? SESSION_COOKIE_SECURE_NAME : SESSION_COOKIE_INSECURE_NAME;
}

export function parseCookies(header: string | undefined): Record<string, string> {
  const out: Record<string, string> = {};
  if (!header) return out;
  for (const part of header.split(";")) {
    const eq = part.indexOf("=");
    if (eq < 0) continue;
    const name = part.slice(0, eq).trim();
    if (!name) continue;
    const value = part.slice(eq + 1).trim();
    out[name] = decodeURIComponent(value);
  }
  return out;
}

export interface CookieAttributes {
  readonly secure: boolean;
  /** Explicit lifetime in seconds — FR-023 requires an explicit expiry, never a session cookie. */
  readonly maxAgeSeconds: number;
}

/**
 * `HttpOnly; SameSite=Lax; Path=/; Max-Age=…` plus `Secure` per the flag — the exact
 * attribute set FR-023 and ET-1 1.2 check for.
 */
export function serializeSessionCookie(
  name: string,
  value: string,
  attributes: CookieAttributes,
): string {
  const parts = [
    `${name}=${encodeURIComponent(value)}`,
    "Path=/",
    "HttpOnly",
    "SameSite=Lax",
    `Max-Age=${Math.max(0, Math.floor(attributes.maxAgeSeconds))}`,
  ];
  if (attributes.secure) parts.push("Secure");
  return parts.join("; ");
}

/** Clearing uses the same attributes with a zero lifetime, so the browser drops the row. */
export function serializeClearedSessionCookie(name: string, secure: boolean): string {
  const parts = [
    `${name}=`,
    "Path=/",
    "HttpOnly",
    "SameSite=Lax",
    "Max-Age=0",
    "Expires=Thu, 01 Jan 1970 00:00:00 GMT",
  ];
  if (secure) parts.push("Secure");
  return parts.join("; ");
}
