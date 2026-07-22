/**
 * Unit tests for the pieces whose behaviour is worth pinning independently of a running
 * server: cookie serialisation, UUIDv7 shape, the security-header set, the counter-window
 * policy, configuration hard-fails, and KEK rotation.
 *
 * No database required — these run everywhere, including a machine with no containers.
 */
import { describe, expect, it } from "vitest";
import { ConfigurationError } from "@sunil/core";
import { ApiConfig } from "../config/api-config.js";
import {
  parseCookies,
  serializeClearedSessionCookie,
  serializeSessionCookie,
  sessionCookieName,
} from "../common/cookies.js";
import { constantTimeEquals, randomRecoveryCode, randomToken, sha256Hex } from "../common/crypto.js";
import { uuidv7 } from "../common/uuid.js";
import { securityHeaders } from "../common/security-headers.js";
import { InMemoryCounterStore } from "../ratelimit/counter-store.js";
import { assertNoSecretValue } from "../interceptors/secret-serialisation.interceptor.js";
import { SecretValue } from "@sunil/core";

const validEnv = {
  DATABASE_URL: "postgresql://localhost:5432/sunil",
  REDIS_URL: "redis://localhost:6379",
  SUNIL_MASTER_KEY: Buffer.alloc(32, 3).toString("base64"),
} as NodeJS.ProcessEnv;

describe("cookies (§6.1, FR-023)", () => {
  it("carries HttpOnly, SameSite=Lax, Path and an explicit Max-Age", () => {
    const cookie = serializeSessionCookie("sunil_session", "abc", {
      secure: false,
      maxAgeSeconds: 3600,
    });
    expect(cookie).toBe("sunil_session=abc; Path=/; HttpOnly; SameSite=Lax; Max-Age=3600");
  });

  it("adds Secure and uses the __Host- prefix only when the secure flag is on", () => {
    expect(sessionCookieName(true)).toBe("__Host-sunil_session");
    expect(sessionCookieName(false)).toBe("sunil_session");
    const cookie = serializeSessionCookie(sessionCookieName(true), "abc", {
      secure: true,
      maxAgeSeconds: 60,
    });
    expect(cookie).toContain("Secure");
    // The `__Host-` prefix is only legal with Secure + Path=/ + no Domain.
    expect(cookie).toContain("Path=/");
    expect(cookie).not.toContain("Domain=");
  });

  it("clears with a zero lifetime and a past expiry", () => {
    const cleared = serializeClearedSessionCookie("sunil_session", false);
    expect(cleared).toContain("Max-Age=0");
    expect(cleared).toContain("Expires=Thu, 01 Jan 1970");
  });

  it("parses a cookie header, tolerating whitespace and missing values", () => {
    expect(parseCookies("a=1; b=2;  c=3")).toEqual({ a: "1", b: "2", c: "3" });
    expect(parseCookies(undefined)).toEqual({});
    expect(parseCookies("novalue")).toEqual({});
  });

  it("never exposes a negative Max-Age", () => {
    const cookie = serializeSessionCookie("s", "v", { secure: false, maxAgeSeconds: -500 });
    expect(cookie).toContain("Max-Age=0");
  });
});

describe("crypto helpers (ADR-003)", () => {
  it("issues 256-bit base64url tokens that never repeat", () => {
    const tokens = new Set(Array.from({ length: 200 }, () => randomToken(32)));
    expect(tokens.size).toBe(200);
    for (const token of tokens) expect(token).toMatch(/^[A-Za-z0-9_-]{43}$/);
  });

  it("compares in constant time and without a length oracle", () => {
    expect(constantTimeEquals("abc", "abc")).toBe(true);
    expect(constantTimeEquals("abc", "abd")).toBe(false);
    // Different lengths must return false, not throw.
    expect(constantTimeEquals("a", "aaaaaaaaaaaaaaaaaaaa")).toBe(false);
  });

  it("hashes deterministically to 64 hex characters", () => {
    expect(sha256Hex("x")).toHaveLength(64);
    expect(sha256Hex("x")).toBe(sha256Hex("x"));
    expect(sha256Hex("x")).not.toBe(sha256Hex("y"));
  });

  it("issues 10-character base32 recovery codes matching the core schema", () => {
    for (let i = 0; i < 50; i += 1) {
      expect(randomRecoveryCode()).toMatch(/^[A-Z2-7]{10}$/);
    }
  });
});

describe("uuidv7 (§5.1)", () => {
  it("produces well-formed, version-7, variant-10 identifiers", () => {
    const id = uuidv7();
    expect(id).toMatch(/^[0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/);
  });

  it("is time-ordered, which is why append-heavy tables index well", () => {
    const early = uuidv7(1_700_000_000_000);
    const late = uuidv7(1_800_000_000_000);
    expect(early < late).toBe(true);
  });

  it("does not collide within a millisecond", () => {
    const now = Date.now();
    const ids = new Set(Array.from({ length: 500 }, () => uuidv7(now)));
    expect(ids.size).toBe(500);
  });
});

describe("security headers (§6.7, FR-031)", () => {
  it("sets a restrictive CSP plus the standard hardening headers", () => {
    const headers = securityHeaders({ secure: false });
    expect(headers["Content-Security-Policy"]).toContain("default-src 'none'");
    expect(headers["Content-Security-Policy"]).toContain("frame-ancestors 'none'");
    expect(headers["Content-Security-Policy"]).toContain("object-src 'none'");
    expect(headers["Content-Security-Policy"]).toContain("base-uri 'none'");
    expect(headers["X-Content-Type-Options"]).toBe("nosniff");
    expect(headers["Referrer-Policy"]).toBe("same-origin");
    expect(headers["Cache-Control"]).toBe("no-store");
  });

  it("adds HSTS only when the deployment is actually over HTTPS", () => {
    expect(securityHeaders({ secure: false })["Strict-Transport-Security"]).toBeUndefined();
    expect(securityHeaders({ secure: true })["Strict-Transport-Security"]).toContain("max-age=");
  });
});

describe("counter windows (§6.3)", () => {
  it("counts within a fixed window and reports its remaining TTL", async () => {
    const store = new InMemoryCounterStore();
    expect((await store.increment("k", 60)).count).toBe(1);
    expect((await store.increment("k", 60)).count).toBe(2);
    expect((await store.increment("k", 60)).ttlSeconds).toBeLessThanOrEqual(60);
    expect((await store.increment("other", 60)).count).toBe(1);
  });

  it("expires a marker and reports null once it is gone", async () => {
    const store = new InMemoryCounterStore();
    await store.setMarker("lock", 1);
    expect(await store.ttl("lock")).toBeGreaterThan(0);
    await store.delete("lock");
    expect(await store.ttl("lock")).toBeNull();
  });
});

describe("configuration (§16, FR-004, FR-023)", () => {
  it("fails fast naming the missing variable, and prints no value", () => {
    try {
      ApiConfig.load({} as NodeJS.ProcessEnv);
      throw new Error("expected a ConfigurationError");
    } catch (error) {
      expect(error).toBeInstanceOf(ConfigurationError);
      expect((error as ConfigurationError).variables).toContain("DATABASE_URL");
      expect((error as ConfigurationError).message).not.toContain("postgresql://");
    }
  });

  it("refuses a master key that is not exactly 32 bytes", () => {
    expect(() =>
      ApiConfig.load({ ...validEnv, SUNIL_MASTER_KEY: Buffer.alloc(16).toString("base64") }),
    ).toThrow(ConfigurationError);
  });

  it("hard-fails a production profile with cookies explicitly insecure", () => {
    expect(() =>
      ApiConfig.load({ ...validEnv, NODE_ENV: "production", SUNIL_COOKIE_SECURE: "false" }),
    ).toThrow(ConfigurationError);
  });

  it("defaults the production cookie policy to secure — permissive-by-omission is impossible", () => {
    const config = ApiConfig.load({ ...validEnv, NODE_ENV: "production" });
    expect(config.cookieSecure).toBe(true);
    expect(config.cookieName).toBe("__Host-sunil_session");
  });

  it("never serialises key material or a DSN", () => {
    const config = ApiConfig.load(validEnv);
    const serialised = JSON.stringify(config);
    expect(serialised).not.toContain(validEnv["SUNIL_MASTER_KEY"]!);
    expect(serialised).not.toContain("postgresql://");
    expect(serialised).not.toContain("redis://");
    expect(String(config)).toBe("ApiConfig(development)");
    // …but the accessors still work for the code that legitimately needs them.
    expect(config.masterKey()).toHaveLength(32);
  });

  it("carries the Gate-1 threshold defaults", () => {
    const config = ApiConfig.load(validEnv);
    expect(config.authMaxFailures).toBe(5);
    expect(config.authFailureWindowMinutes).toBe(15);
    expect(config.authLockoutMinutes).toBe(15);
    expect(config.rateSessionPerMinute).toBe(100);
    expect(config.rateAuthIpPerMinute).toBe(20);
    expect(config.sessionIdleHours).toBe(8);
    expect(config.sessionAbsoluteHours).toBe(24);
    expect(config.inviteTtlHours).toBe(72);
  });
});

describe("the serialisation guard (§8.4)", () => {
  it("throws when a SecretValue appears anywhere in a response object", () => {
    expect(() => assertNoSecretValue({ ok: true })).not.toThrow();
    expect(() => assertNoSecretValue({ a: new SecretValue("n", "v") })).toThrow(/SecretValue/);
    expect(() => assertNoSecretValue([{ b: [{ c: new SecretValue("n", "v") }] }])).toThrow(
      /SecretValue/,
    );
  });

  it("survives a cyclic response object without hanging", () => {
    const cyclic: Record<string, unknown> = { name: "loop" };
    cyclic["self"] = cyclic;
    expect(() => assertNoSecretValue(cyclic)).not.toThrow();
  });
});
