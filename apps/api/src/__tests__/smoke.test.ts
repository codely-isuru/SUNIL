/**
 * Boot smoke test. Not an exit test — it exists so a wiring failure surfaces as one obvious
 * red line rather than as eleven confusing ones in the behavioural suites.
 */
import { afterAll, beforeAll, describe, expect, it } from "vitest";
import type { TestApp } from "./harness.js";
import { TEST_DSN, call, createTestApp, loginAsOwner } from "./harness.js";

const describeDb = TEST_DSN ? describe : describe.skip;

describeDb("API boots and serves", () => {
  let ctx: TestApp;

  beforeAll(async () => {
    ctx = await createTestApp();
  }, 60_000);

  afterAll(async () => {
    await ctx?.close();
  });

  it("serves health with booleans only (FR-091)", async () => {
    const response = await call(ctx.app, { method: "GET", url: "/api/system-health" });
    expect(response.statusCode).toBe(200);
    expect(response.json()).toEqual({ status: "ok", deps: { postgres: "up", redis: "up" } });
  });

  it("sets the §6.7 security headers on every response", async () => {
    const response = await call(ctx.app, { method: "GET", url: "/api/system-health" });
    expect(response.headers["content-security-policy"]).toContain("frame-ancestors 'none'");
    expect(response.headers["x-content-type-options"]).toBe("nosniff");
    expect(response.headers["referrer-policy"]).toBe("same-origin");
  });

  it("logs the bootstrapped owner in and resolves all 21 permissions", async () => {
    const owner = await loginAsOwner(ctx.app);
    const me = await call(ctx.app, { method: "GET", url: "/api/auth/me", cookie: owner.cookie });
    expect(me.statusCode).toBe(200);
    expect(me.json<{ permissions: string[] }>().permissions).toHaveLength(21);
  });
});
