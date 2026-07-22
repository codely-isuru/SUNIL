/**
 * The API client — PHASE1_ARCHITECTURE §13, §6.5, FR-022, FR-105.
 *
 * `fetch` is stubbed, so these assert the CONTRACT the client keeps: same-origin relative
 * paths (ADR-011 / amendment A1), the session cookie carried without cross-origin semantics,
 * the CSRF header on mutations, failures reduced to a category, and a timeout that produces
 * the §7.1 watchdog state rather than hanging.
 */
import { readFileSync, readdirSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { afterEach, describe, expect, it, vi } from "vitest";
import {
  apiRequest,
  fetchSystemHealth,
  login,
  saveSetting,
  verifyMfa,
} from "../lib/api/client";
import { resolveApiBaseUrl } from "../config";

interface Call {
  url: string;
  init: RequestInit;
}

function stubFetch(response: Response | (() => Promise<Response>)): Call[] {
  const calls: Call[] = [];
  vi.stubGlobal("fetch", async (url: string, init: RequestInit) => {
    calls.push({ url: String(url), init });
    return typeof response === "function" ? response() : response;
  });
  return calls;
}

function json(body: unknown, status = 200, headers: Record<string, string> = {}): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json", ...headers },
  });
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("ADR-011 / amendment A1 — same-origin, no CORS", () => {
  it("resolves the SERVER base URL from SUNIL_API_INTERNAL_URL", () => {
    expect(resolveApiBaseUrl("http://api:3001")).toBe("http://api:3001/api");
    expect(resolveApiBaseUrl("http://localhost:3001/")).toBe("http://localhost:3001/api");
  });

  it("resolves the BROWSER base URL to the relative /api path — never an origin", () => {
    vi.stubGlobal("window", {});
    try {
      expect(resolveApiBaseUrl()).toBe("/api");
      // Even an explicit override cannot put an absolute origin into a client request.
      expect(resolveApiBaseUrl("http://api:3001")).toBe("/api");
    } finally {
      vi.unstubAllGlobals();
    }
  });

  it("sends same-origin credentials, not cross-origin ones", async () => {
    const calls = stubFetch(json({ status: "ok", deps: {} }));
    await fetchSystemHealth();
    expect(calls[0]?.init.credentials).toBe("same-origin");
    expect(calls[0]?.url).toContain("/api/system-health");
  });

  it("mentions NEXT_PUBLIC_API_URL nowhere — it was removed from the inventory by A1", () => {
    const root = resolve(dirname(fileURLToPath(import.meta.url)), "..", "..");
    const offenders: string[] = [];
    const walk = (dir: string): void => {
      for (const entry of readdirSync(dir, { withFileTypes: true })) {
        if (["node_modules", ".next", ".turbo", ".vitest", "dist"].includes(entry.name)) continue;
        const full = join(dir, entry.name);
        if (full === fileURLToPath(import.meta.url)) continue; // this file names what it forbids
        if (entry.isDirectory()) walk(full);
        else if (/\.(ts|tsx|mjs|json)$/.test(entry.name)) {
          if (readFileSync(full, "utf8").includes("NEXT_PUBLIC_API_URL")) offenders.push(full);
        }
      }
    };
    walk(root);
    expect(offenders).toEqual([]);
  });
});

describe("request shape", () => {
  it("sends X-CSRF-Token on mutations and never on reads (ADR-009 / A2)", async () => {
    const calls = stubFetch(json({}));
    await saveSetting("regional.timezone", "Australia/Hobart", "csrf-value");
    await fetchSystemHealth();
    const headers = calls[0]?.init.headers as Record<string, string>;
    expect(calls[0]?.init.method).toBe("PUT");
    expect(headers["X-CSRF-Token"]).toBe("csrf-value");
    expect((calls[1]?.init.headers as Record<string, string>)["X-CSRF-Token"]).toBeUndefined();
  });

  it("carries the CSRF token on the MFA verify, which mutates a PENDING_MFA session", async () => {
    const calls = stubFetch(json({ user: {}, csrfToken: "rotated" }));
    await verifyMfa({ code: "123456" }, "pre-elevation-token");
    expect((calls[0]?.init.headers as Record<string, string>)["X-CSRF-Token"]).toBe(
      "pre-elevation-token",
    );
  });

  it("never caches an authenticated response", async () => {
    const calls = stubFetch(json({}));
    await fetchSystemHealth();
    expect(calls[0]?.init.cache).toBe("no-store");
  });

  it("puts nothing sensitive in the URL", async () => {
    const calls = stubFetch(json({ user: {}, mfaRequired: false }));
    await login("owner@example.test", "correct horse battery staple");
    expect(calls[0]?.url).not.toContain("owner@example.test");
    expect(calls[0]?.url).not.toContain("correct");
    expect(calls[0]?.init.body).toContain("owner@example.test");
  });
});

describe("failure categorisation (FR-022, FR-029)", () => {
  it("maps 401 to unauthorized — the caller renders ONE generic message", async () => {
    stubFetch(json({ message: "user not found" }, 401));
    const result = await login("a@b.test", "x");
    expect(result.ok).toBe(false);
    if (!result.ok) {
      expect(result.kind).toBe("unauthorized");
      // The server's wording is never surfaced: it is an account-existence oracle.
      expect(JSON.stringify(result)).not.toContain("user not found");
    }
  });

  it("maps 429 to rate_limited and keeps Retry-After for the lockout message", async () => {
    stubFetch(json({}, 429, { "Retry-After": "600" }));
    const result = await login("a@b.test", "x");
    expect(result.ok).toBe(false);
    if (!result.ok) {
      expect(result.kind).toBe("rate_limited");
      expect(result.retryAfterSeconds).toBe(600);
    }
  });

  it("maps 403 to forbidden, so a panel can say 'you lack this permission'", async () => {
    stubFetch(json({}, 403));
    const result = await verifyMfa({ code: "123456" });
    expect(result.ok).toBe(false);
    if (!result.ok) expect(result.kind).toBe("forbidden");
  });

  it("maps 5xx to server", async () => {
    stubFetch(json({}, 503));
    const result = await fetchSystemHealth();
    expect(result.ok).toBe(false);
    if (!result.ok) expect(result.kind).toBe("server");
  });

  it("maps a dead network to network — the state the portal is in today", async () => {
    vi.stubGlobal("fetch", async () => {
      throw new TypeError("fetch failed");
    });
    const result = await fetchSystemHealth();
    expect(result.ok).toBe(false);
    if (!result.ok) expect(result.kind).toBe("network");
  });

  it("maps an abort to timeout, which drives the §7.1 watchdog copy", async () => {
    vi.stubGlobal("fetch", async () => {
      const error = new Error("aborted");
      error.name = "AbortError";
      throw error;
    });
    const result = await apiRequest("/anything", { timeoutMs: 5 });
    expect(result.ok).toBe(false);
    if (!result.ok) expect(result.kind).toBe("timeout");
  });
});

describe("success", () => {
  it("returns the parsed body", async () => {
    stubFetch(json({ status: "degraded", deps: { postgres: "up", redis: "down" } }));
    const result = await fetchSystemHealth();
    expect(result.ok).toBe(true);
    if (result.ok) {
      expect(result.data.status).toBe("degraded");
      expect(result.data.deps["redis"]).toBe("down");
    }
  });

  it("tolerates a 204 with no body", async () => {
    stubFetch(new Response(null, { status: 204 }));
    const result = await saveSetting("appearance.motion", "reduce");
    expect(result.ok).toBe(true);
  });
});
