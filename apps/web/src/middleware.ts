/**
 * Edge middleware: security headers (PHASE1_ARCHITECTURE §6.7) and the unauthenticated
 * redirect (FR-101).
 *
 * **The UI is never the control.** This redirect exists so an unauthenticated visitor is not
 * shown an application frame; it is not what protects anything. Every protected route is
 * enforced independently by the API against the session cookie (ET-2 step 2.6). Nothing in
 * this file may be read as an authorisation decision — it only decides which page to render,
 * and it does so from the PRESENCE of a cookie, never from its contents, which it cannot
 * validate and must not try to.
 */
import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";

/** §6.1 — `__Host-` prefixed when `SUNIL_COOKIE_SECURE=true`, plain for local HTTP dev. */
const SESSION_COOKIES = ["__Host-sunil_session", "sunil_session"];

/**
 * Routes that must render without a session.
 *
 * `/dev` is the four-state component gallery. It is listed here so it is reachable while
 * developing, and it is NOT a hole in anything: the page itself calls `notFound()` when
 * `NODE_ENV === "production"`, so in a production build the route is a 404 regardless of who
 * asks. It renders fixtures and touches no API.
 */
const PUBLIC_PREFIXES = ["/sign-in", "/invite", "/login", "/mfa", "/dev"];

function isPublic(pathname: string): boolean {
  return PUBLIC_PREFIXES.some(
    (prefix) => pathname === prefix || pathname.startsWith(`${prefix}/`),
  );
}

function hasSessionCookie(request: NextRequest): boolean {
  return SESSION_COOKIES.some((name) => request.cookies.has(name));
}

function nonce(): string {
  const bytes = new Uint8Array(16);
  crypto.getRandomValues(bytes);
  let binary = "";
  for (const byte of bytes) binary += String.fromCharCode(byte);
  return btoa(binary);
}

function contentSecurityPolicy(scriptNonce: string): string {
  return [
    "default-src 'self'",
    // 'strict-dynamic' is deliberately absent: Next's own bootstrap scripts are nonced, and
    // adding it would let any script they load run unnoticed.
    `script-src 'self' 'nonce-${scriptNonce}'`,
    // §6.7 specifies 'unsafe-inline' for styles. React sets inline `style` attributes for the
    // presence box size and the busy-button width freeze; both are numeric layout values, never
    // interpolated content, and no `<style>` element is emitted by application code.
    "style-src 'self' 'unsafe-inline'",
    "img-src 'self' data:",
    // Fonts are self-hosted, so no third-party origin appears here (DESIGN_TOKENS.md §7.1).
    "font-src 'self'",
    // ADR-011 / amendment A1: the browser only ever calls relative `/api/...` paths, which
    // `next.config.mjs` proxies. There is no second origin to allow, and adding one back
    // would re-open the cross-origin surface the ruling closed.
    "connect-src 'self'",
    "frame-ancestors 'none'",
    "object-src 'none'",
    "base-uri 'none'",
    "form-action 'self'",
  ].join("; ");
}

export function middleware(request: NextRequest): NextResponse {
  const scriptNonce = nonce();
  const csp = contentSecurityPolicy(scriptNonce);

  const requestHeaders = new Headers(request.headers);
  requestHeaders.set("x-nonce", scriptNonce);
  // Next reads the CSP from the REQUEST headers to nonce the scripts it injects.
  requestHeaders.set("Content-Security-Policy", csp);

  const { pathname } = request.nextUrl;
  const response =
    isPublic(pathname) || hasSessionCookie(request)
      ? NextResponse.next({ request: { headers: requestHeaders } })
      : NextResponse.redirect(new URL("/sign-in", request.url));

  response.headers.set("Content-Security-Policy", csp);
  response.headers.set("X-Content-Type-Options", "nosniff");
  response.headers.set("Referrer-Policy", "same-origin");
  response.headers.set("X-Frame-Options", "DENY");
  return response;
}

export const config = {
  /**
   * Everything except Next's own static output, the favicon, and `/api/*`.
   *
   * `/api/*` is EXCLUDED deliberately. Under ADR-011 those paths are the rewrite proxy to
   * `apps/api`, and they must pass straight through: `POST /api/auth/login` is called by an
   * unauthenticated visitor by definition, so redirecting cookie-less API calls to `/sign-in`
   * would break sign-in itself and turn every unauthenticated API response into an HTML
   * redirect. The API sets its own §6.7 headers on its own responses and enforces its own
   * authentication and authorisation — this middleware only decides which PAGE to render.
   */
  matcher: ["/((?!api/|_next/static|_next/image|favicon.ico).*)"],
};
