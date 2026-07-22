/**
 * The CSRF token issued at login, held across the client-side navigation to `/sign-in/mfa`.
 *
 * WHY THIS EXISTS. `POST /auth/mfa/verify` is a MUTATING request on a `PENDING_MFA` session,
 * so it needs the `X-CSRF-Token` header like any other mutation (ADR-009; amendment A2 makes
 * the header token the whole of the Phase 1 control — there is no `Origin` check). The API
 * therefore returns a `csrfToken` on login even when `mfaRequired` is true, and the MFA screen
 * must send it back.
 *
 * WHY IT IS A MODULE VARIABLE AND NOT STORAGE. §11.8: the client keeps no copy of anything
 * authentication-related in JavaScript-readable storage. `sessionStorage` would survive a
 * reload, which is precisely the property that makes it the wrong place. This value lives in
 * memory for the duration of one soft navigation and is cleared the moment it is used.
 *
 * CONSEQUENCE, HANDLED DELIBERATELY. A hard reload of `/sign-in/mfa` loses the token, so the
 * verify would be rejected with a 403. The MFA screen checks for that case up front and tells
 * the user to sign in again, rather than letting them type a correct code into a request that
 * cannot succeed.
 *
 * NOTE: both the session token and the CSRF secret ROTATE on MFA elevation (§6.2), so nothing
 * downstream may reuse this value afterwards — the shell re-reads the current token from
 * `GET /auth/me` on every request.
 */
let pendingCsrfToken: string | null = null;

export function setPendingCsrfToken(token: string | undefined): void {
  pendingCsrfToken = token ?? null;
}

/** Reads the token. It is cleared explicitly once elevation SUCCEEDS, not on every read. */
export function readPendingCsrfToken(): string | null {
  return pendingCsrfToken;
}

export function clearPendingCsrfToken(): void {
  pendingCsrfToken = null;
}

export function hasPendingCsrfToken(): boolean {
  return pendingCsrfToken !== null;
}
