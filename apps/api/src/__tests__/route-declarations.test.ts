/**
 * ET-2 2.1 and ET-3 3.2 — default deny and audit coverage as a NAMED test failure.
 *
 * This is the test §7.4 layer 2 and §9.4 refer to. It walks the routes Fastify actually
 * registered, pairs them with their controller metadata, and fails NAMING any route that:
 *   • carries no access declaration, or more than one;
 *   • is mutating and carries no `@Audited` action.
 *
 * The negative control is the important half. It is not enough for the check to pass on a
 * clean codebase — the check has to FAIL when someone forgets, otherwise it proves nothing.
 * So a deliberately undecorated controller is registered into a real application, and the
 * test asserts (a) the checker names it, and (b) the running guard returns 403 for it.
 */
import { Controller, Get, Post } from "@nestjs/common";
import { afterAll, beforeAll, describe, expect, it } from "vitest";
import { API_CONTROLLERS } from "../app.module.js";
import { API_PREFIX } from "../app.factory.js";
import {
  describeControllerRoutes,
  findDeclarationViolations,
  formatViolations,
} from "../common/route-audit.js";
import { TEST_DSN, call, createTestApp, loginAsOwner, type TestApp } from "./harness.js";

const describeDb = TEST_DSN ? describe : describe.skip;

/** ET-3 3.2's negative control. Registered ONLY inside this test's fixture application. */
@Controller("negative-control")
class UndeclaredController {
  @Get("read")
  read() {
    return { reached: true };
  }

  @Post("mutate")
  mutate() {
    return { reached: true };
  }
}

describe("route declarations — the static half (no database required)", () => {
  it("every §13 route carries exactly one access declaration and every mutation is audited", () => {
    const routes = describeControllerRoutes(API_CONTROLLERS, API_PREFIX);
    const violations = findDeclarationViolations(routes);
    expect(routes.length).toBeGreaterThan(25);
    expect(violations, `\n${formatViolations(violations)}`).toEqual([]);
  });

  it("NEGATIVE CONTROL: names an undeclared route rather than passing silently", () => {
    const routes = describeControllerRoutes([UndeclaredController], API_PREFIX);
    const violations = findDeclarationViolations(routes);

    const undeclared = violations.filter((v) => v.problem.includes("no access declaration"));
    expect(undeclared).toHaveLength(2);
    expect(undeclared.map((v) => v.route).join(" ")).toContain(
      "GET /api/negative-control/read (UndeclaredController.read)",
    );

    const unaudited = violations.filter((v) => v.problem.includes("no @Audited action"));
    expect(unaudited).toHaveLength(1);
    expect(unaudited[0]!.route).toContain("POST /api/negative-control/mutate");
  });
});

describeDb("route declarations — against the running server", () => {
  let ctx: TestApp;
  const registered: { method: string; path: string }[] = [];

  beforeAll(async () => {
    ctx = await createTestApp({
      onRoute: (route) => registered.push(route),
    });
  }, 60_000);

  afterAll(async () => {
    await ctx?.close();
  });

  it("every route Fastify registered has a declared controller handler", () => {
    const interesting = registered.filter(
      (route) => route.method !== "HEAD" && route.method !== "OPTIONS",
    );
    expect(interesting.length).toBeGreaterThan(25);

    const routes = describeControllerRoutes(API_CONTROLLERS, API_PREFIX);
    const violations = findDeclarationViolations(routes, interesting);
    expect(violations, `\n${formatViolations(violations)}`).toEqual([]);
  });
});

describeDb("default deny is enforced at run time, not only at build time", () => {
  let ctx: TestApp;

  beforeAll(async () => {
    ctx = await createTestApp({ extraControllers: [UndeclaredController] });
  }, 60_000);

  afterAll(async () => {
    await ctx?.close();
  });

  it("an undeclared route is 403 for an authenticated OWNER — the strongest principal", async () => {
    const owner = await loginAsOwner(ctx.app);
    const response = await call(ctx.app, {
      method: "GET",
      url: "/api/negative-control/read",
      cookie: owner.cookie,
    });
    expect(response.statusCode).toBe(403);
    expect(response.json()).toEqual({ error: "FORBIDDEN" });
  });

  it("an undeclared route is 403 unauthenticated too, and the handler never runs", async () => {
    const response = await call(ctx.app, { method: "GET", url: "/api/negative-control/read" });
    expect(response.statusCode).toBe(403);
    expect(response.raw).not.toContain("reached");
  });
});
