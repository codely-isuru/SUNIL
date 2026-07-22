/**
 * Middleware: the CSP (PHASE1_ARCHITECTURE §6.7) and the unauthenticated redirect (FR-101).
 *
 * The CSP assertions are the mechanical half of the font decision: if anybody ever
 * reintroduces the prototype's Google Fonts link, `font-src 'self'` makes it fail to load and
 * this test makes it fail to merge.
 */
import { describe, expect, it } from "vitest";
import { NextRequest } from "next/server";
import { config, middleware } from "../middleware";

function request(path: string, cookie?: string): NextRequest {
  return new NextRequest(new URL(`http://localhost:3000${path}`), {
    headers: cookie === undefined ? undefined : { cookie },
  });
}

function csp(path: string, cookie?: string): string {
  return middleware(request(path, cookie)).headers.get("Content-Security-Policy") ?? "";
}

describe("security headers (§6.7)", () => {
  const policy = csp("/sign-in");

  it("sets the directives the architecture specifies", () => {
    expect(policy).toContain("default-src 'self'");
    expect(policy).toContain("style-src 'self' 'unsafe-inline'");
    expect(policy).toContain("img-src 'self' data:");
    expect(policy).toContain("frame-ancestors 'none'");
    expect(policy).toContain("object-src 'none'");
    expect(policy).toContain("base-uri 'none'");
  });

  it("nonces scripts, with a fresh nonce per request", () => {
    expect(policy).toMatch(/script-src 'self' 'nonce-[A-Za-z0-9+/=]+'/);
    expect(csp("/sign-in")).not.toBe(csp("/sign-in"));
  });

  it("allows fonts from 'self' ONLY — the prototype's CDN link cannot ship", () => {
    expect(policy).toContain("font-src 'self'");
    expect(policy).not.toContain("fonts.googleapis.com");
    expect(policy).not.toContain("fonts.gstatic.com");
  });

  it("permits XHR to 'self' ONLY — ADR-011 leaves no second origin to allow", () => {
    expect(policy).toContain("connect-src 'self';");
    expect(policy).not.toMatch(/connect-src 'self' https?:/);
    // A public API origin in the CSP would be the first symptom of A1 being undone.
    expect(policy).not.toContain(":3001");
  });

  it("sets the other headers §6.7 names", () => {
    const response = middleware(request("/sign-in"));
    expect(response.headers.get("X-Content-Type-Options")).toBe("nosniff");
    expect(response.headers.get("Referrer-Policy")).toBe("same-origin");
  });
});

describe("unauthenticated redirect (FR-101)", () => {
  it("redirects a visitor with no session cookie away from a protected route", () => {
    const response = middleware(request("/"));
    expect(response.status).toBe(307);
    expect(response.headers.get("location")).toBe("http://localhost:3000/sign-in");
  });

  it("also protects settings and system health", () => {
    for (const path of ["/settings", "/system-health"]) {
      expect(middleware(request(path)).headers.get("location")).toBe(
        "http://localhost:3000/sign-in",
      );
    }
  });

  it("lets the auth routes render without a session", () => {
    for (const path of ["/sign-in", "/sign-in/mfa", "/invite/abc123"]) {
      expect(middleware(request(path)).headers.get("location")).toBeNull();
    }
  });

  it("accepts either cookie name from §6.1", () => {
    expect(middleware(request("/", "sunil_session=x")).headers.get("location")).toBeNull();
    expect(
      middleware(request("/", "__Host-sunil_session=x")).headers.get("location"),
    ).toBeNull();
  });

  it("does not run on /api/* at all — those are the ADR-011 proxy paths", () => {
    // Found by running the built app: with `/api/*` inside the matcher, a cookie-less
    // `POST /api/auth/login` was answered with a 307 to /sign-in, which breaks sign-in itself
    // and turns every unauthenticated API response into an HTML redirect.
    expect(config.matcher).toHaveLength(1);
    // Next anchors a matcher to the whole path, so the reconstruction is anchored too.
    const matches = new RegExp(`^${config.matcher[0] ?? ""}$`);
    expect(matches.test("/api/auth/login")).toBe(false);
    expect(matches.test("/api/system-health")).toBe(false);
    expect(matches.test("/settings")).toBe(true);
    expect(matches.test("/sign-in")).toBe(true);
  });

  it("decides on the PRESENCE of a cookie only — it never inspects the value", () => {
    // The middleware cannot validate a session token and must not pretend to: the API
    // enforces independently (ET-2 2.6). A junk value still renders the shell, and the API
    // then rejects every request it makes.
    expect(middleware(request("/", "sunil_session=not-a-real-token")).status).toBe(200);
  });
});
