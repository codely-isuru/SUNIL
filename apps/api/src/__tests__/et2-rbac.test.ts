/**
 * ET-2 — RBAC guards (PHASE1_REQUIREMENTS §5, steps 2.1–2.6).
 *
 * 2.1 lives in `route-declarations.test.ts` (the enumeration test, §7.4 layer 2). This file
 * covers 2.2–2.6 by driving EVERY permission-guarded route in the §13 surface as three
 * different principals.
 *
 * The route table below is not a hand-maintained convenience: a test in here asserts that it
 * covers exactly the set of permission-declared routes the application actually registers,
 * so adding a guarded route without adding it to this table fails the suite by name.
 */
import { afterAll, beforeAll, describe, expect, it } from "vitest";
import { ROLE_IDS, type PermissionKey } from "@sunil/core";
import { API_CONTROLLERS } from "../app.module.js";
import { API_PREFIX } from "../app.factory.js";
import { describeControllerRoutes } from "../common/route-audit.js";
import {
  TEST_DSN,
  call,
  createTestApp,
  inviteAndAccept,
  loginAsOwner,
  type Principal,
  type TestApp,
} from "./harness.js";

const describeDb = TEST_DSN ? describe : describe.skip;

interface GuardedCall {
  readonly method: "GET" | "POST" | "PUT" | "PATCH" | "DELETE";
  /** The route PATTERN, matching the controller metadata. */
  readonly pattern: string;
  readonly permission: PermissionKey;
  /** Concrete URL builder — ids come from fixtures created by the owner. */
  readonly url: (f: Fixtures) => string;
  readonly payload?: (f: Fixtures) => unknown;
}

interface Fixtures {
  readonly targetUserId: string;
  readonly invitationId: string;
  readonly secretId: string;
  readonly providerId: string;
  readonly agentId: string;
  readonly settingKey: string;
}

const GUARDED_CALLS: readonly GuardedCall[] = [
  { method: "GET", pattern: "/api/users", permission: "user:read", url: () => "/api/users" },
  { method: "GET", pattern: "/api/users/:id", permission: "user:read", url: (f) => `/api/users/${f.targetUserId}` },
  {
    method: "PATCH",
    pattern: "/api/users/:id",
    permission: "user:update",
    url: (f) => `/api/users/${f.targetUserId}`,
    payload: () => ({ displayName: "Renamed By Test" }),
  },
  {
    method: "POST",
    pattern: "/api/users/:id/lockout/clear",
    permission: "user:update",
    url: (f) => `/api/users/${f.targetUserId}/lockout/clear`,
  },
  {
    method: "PUT",
    pattern: "/api/users/:id/roles",
    permission: "role:assign",
    url: (f) => `/api/users/${f.targetUserId}/roles`,
    payload: () => ({ roleIds: [ROLE_IDS.viewer] }),
  },
  {
    method: "GET",
    pattern: "/api/users/:id/sessions",
    permission: "session:read",
    url: (f) => `/api/users/${f.targetUserId}/sessions`,
  },
  {
    method: "POST",
    pattern: "/api/users/:id/sessions/revoke",
    permission: "session:revoke",
    url: (f) => `/api/users/${f.targetUserId}/sessions/revoke`,
  },
  {
    method: "POST",
    pattern: "/api/invitations",
    permission: "user:invite",
    url: () => "/api/invitations",
    payload: () => ({ email: `rbac-${Date.now()}@sunil.test`, roleId: ROLE_IDS.viewer }),
  },
  { method: "GET", pattern: "/api/invitations", permission: "user:invite", url: () => "/api/invitations" },
  {
    method: "DELETE",
    pattern: "/api/invitations/:id",
    permission: "user:invite",
    url: (f) => `/api/invitations/${f.invitationId}`,
  },
  { method: "GET", pattern: "/api/roles", permission: "role:read", url: () => "/api/roles" },
  { method: "GET", pattern: "/api/permissions", permission: "role:read", url: () => "/api/permissions" },
  {
    method: "POST",
    pattern: "/api/secrets",
    permission: "secret:create",
    url: () => "/api/secrets",
    payload: () => ({ name: `rbac-secret-${Date.now()}`, value: "rbac-value", description: "" }),
  },
  { method: "GET", pattern: "/api/secrets", permission: "secret:read", url: () => "/api/secrets" },
  { method: "GET", pattern: "/api/secrets/:id", permission: "secret:read", url: (f) => `/api/secrets/${f.secretId}` },
  {
    method: "POST",
    pattern: "/api/secrets/:id/rotate",
    permission: "secret:rotate",
    url: (f) => `/api/secrets/${f.secretId}/rotate`,
    payload: () => ({ value: "rotated-by-rbac-test" }),
  },
  {
    method: "DELETE",
    pattern: "/api/secrets/:id",
    permission: "secret:delete",
    url: (f) => `/api/secrets/${f.secretId}`,
  },
  { method: "GET", pattern: "/api/settings", permission: "settings:read", url: () => "/api/settings" },
  {
    method: "PATCH",
    pattern: "/api/settings/:key",
    permission: "settings:write",
    url: (f) => `/api/settings/${f.settingKey}`,
    payload: () => ({ value: "SUNIL" }),
  },
  { method: "GET", pattern: "/api/providers", permission: "provider:read", url: () => "/api/providers" },
  {
    method: "PATCH",
    pattern: "/api/providers/:id",
    permission: "provider:write",
    url: (f) => `/api/providers/${f.providerId}`,
    payload: () => ({ enabled: false }),
  },
  { method: "GET", pattern: "/api/agents", permission: "agent:read", url: () => "/api/agents" },
  {
    method: "GET",
    pattern: "/api/agents/:id/activity",
    permission: "agent:read",
    url: (f) => `/api/agents/${f.agentId}/activity`,
  },
  {
    method: "POST",
    pattern: "/api/agents",
    permission: "agent:write",
    url: () => "/api/agents",
    payload: () => ({
      slug: `rbac-agent-${Date.now()}`,
      name: "RBAC Agent",
      role: "fixture",
      systemInstructions: "none",
      maxDurationSeconds: 60,
      heartbeatIntervalSeconds: 30,
      staleThresholdSeconds: 90,
    }),
  },
  {
    method: "PATCH",
    pattern: "/api/agents/:id",
    permission: "agent:write",
    url: (f) => `/api/agents/${f.agentId}`,
    payload: () => ({ name: "Renamed Agent" }),
  },
  {
    method: "POST",
    pattern: "/api/agents/:id/run",
    permission: "agent:write",
    url: (f) => `/api/agents/${f.agentId}/run`,
  },
  { method: "GET", pattern: "/api/audit", permission: "audit:read", url: () => "/api/audit" },
  { method: "GET", pattern: "/api/usage", permission: "usage:read", url: () => "/api/usage" },
  { method: "GET", pattern: "/api/jobs/status", permission: "job:read", url: () => "/api/jobs/status" },
  { method: "GET", pattern: "/api/jobs/history", permission: "job:read", url: () => "/api/jobs/history" },
];

describe("ET-2 2.x — the guarded-route table is complete", () => {
  it("covers exactly the permission-declared routes the application registers", () => {
    const declared = describeControllerRoutes(API_CONTROLLERS, API_PREFIX)
      .filter((route) => route.declarations[0]?.kind === "permission")
      .map((route) => `${route.method} ${route.path}`)
      .sort();
    const covered = [...new Set(GUARDED_CALLS.map((c) => `${c.method} ${c.pattern}`))].sort();

    const missing = declared.filter((route) => !covered.includes(route));
    expect(missing, `guarded routes missing from the ET-2 table:\n  ${missing.join("\n  ")}`).toEqual([]);
    expect(covered.filter((route) => !declared.includes(route))).toEqual([]);
  });
});

describeDb("ET-2 — RBAC guards", () => {
  let ctx: TestApp;
  let owner: Principal;
  let viewer: Principal;
  let fixtures: Fixtures;

  beforeAll(async () => {
    ctx = await createTestApp();
    owner = await loginAsOwner(ctx.app);
    viewer = await inviteAndAccept(ctx.app, owner, ROLE_IDS.viewer);

    const target = await inviteAndAccept(ctx.app, owner, ROLE_IDS.viewer);

    const invitation = await call(ctx.app, {
      method: "POST",
      url: "/api/invitations",
      payload: { email: `fixture-${Date.now()}@sunil.test`, roleId: ROLE_IDS.viewer },
      cookie: owner.cookie,
      csrfToken: owner.csrfToken,
    });

    const secret = await call(ctx.app, {
      method: "POST",
      url: "/api/secrets",
      payload: { name: "et2-fixture-secret", value: "et2-fixture-value", description: "" },
      cookie: owner.cookie,
      csrfToken: owner.csrfToken,
    });

    const providers = await call(ctx.app, {
      method: "GET",
      url: "/api/providers",
      cookie: owner.cookie,
    });

    const agent = await call(ctx.app, {
      method: "POST",
      url: "/api/agents",
      payload: {
        slug: "et2-fixture-agent",
        name: "Fixture",
        role: "fixture",
        systemInstructions: "none",
        maxDurationSeconds: 60,
        heartbeatIntervalSeconds: 30,
        staleThresholdSeconds: 90,
      },
      cookie: owner.cookie,
      csrfToken: owner.csrfToken,
    });

    fixtures = {
      targetUserId: target.userId,
      invitationId: invitation.json<{ id: string }>().id,
      secretId: secret.json<{ id: string }>().id,
      providerId: providers.json<{ items: { id: string }[] }>().items[0]!.id,
      agentId: agent.json<{ id: string }>().id,
      settingKey: "platform.displayName",
    };
  }, 90_000);

  afterAll(async () => {
    await ctx?.close();
  });

  // ── 2.2 / 2.6 ──────────────────────────────────────────────────────────────
  it("2.2 a viewer is 403 on every route requiring a permission it lacks, with zero state change", async () => {
    const stateBefore = await snapshot(ctx);
    const failures: string[] = [];

    for (const guarded of GUARDED_CALLS) {
      // The viewer legitimately holds `audit:read`; everything else must be refused.
      if (guarded.permission === "audit:read") continue;

      const response = await call(ctx.app, {
        method: guarded.method,
        url: guarded.url(fixtures),
        ...(guarded.payload ? { payload: guarded.payload(fixtures) } : {}),
        cookie: viewer.cookie,
        csrfToken: viewer.csrfToken,
      });

      if (response.statusCode !== 403) {
        failures.push(`${guarded.method} ${guarded.pattern} → ${response.statusCode} ${response.raw}`);
      }
      // FR-026: a denial reveals nothing about the resource beyond the status code.
      if (response.statusCode === 403) {
        expect(response.json()).toEqual({ error: "FORBIDDEN" });
      }
    }

    expect(failures, `viewer was not refused on:\n  ${failures.join("\n  ")}`).toEqual([]);
    expect(await snapshot(ctx)).toEqual(stateBefore);
  }, 90_000);

  it("2.6 hiding a nav item is not the control — the API refuses the viewer directly", async () => {
    const response = await call(ctx.app, {
      method: "GET",
      url: "/api/users",
      cookie: viewer.cookie,
    });
    expect(response.statusCode).toBe(403);

    const me = await call(ctx.app, { method: "GET", url: "/api/auth/me", cookie: viewer.cookie });
    // The portal filters nav from this array; the API enforces independently.
    expect(me.json<{ permissions: string[] }>().permissions).not.toContain("user:read");
  });

  // ── 2.3 ────────────────────────────────────────────────────────────────────
  it("2.3 the owner reaches every one of them — no call fails for an authorisation reason", async () => {
    const failures: string[] = [];

    for (const guarded of GUARDED_CALLS) {
      const response = await call(ctx.app, {
        method: guarded.method,
        url: guarded.url(fixtures),
        ...(guarded.payload ? { payload: guarded.payload(fixtures) } : {}),
        cookie: owner.cookie,
        csrfToken: owner.csrfToken,
      });

      if (response.statusCode === 401 || response.statusCode === 403) {
        failures.push(`${guarded.method} ${guarded.pattern} → ${response.statusCode} ${response.raw}`);
      }
    }

    expect(failures, `owner was refused on:\n  ${failures.join("\n  ")}`).toEqual([]);
  }, 90_000);

  // ── 2.4 ────────────────────────────────────────────────────────────────────
  it("2.4 every non-public route is 401 unauthenticated", async () => {
    const failures: string[] = [];

    const nonPublic = describeControllerRoutes(API_CONTROLLERS, API_PREFIX).filter(
      (route) => route.declarations[0]?.kind !== "public",
    );

    for (const route of nonPublic) {
      const url = route.path
        .replace(":id", fixtures.targetUserId)
        .replace(":key", fixtures.settingKey);
      const response = await call(ctx.app, {
        method: route.method as "GET",
        url,
        payload: route.method === "GET" || route.method === "DELETE" ? undefined : {},
      });
      if (response.statusCode !== 401) {
        failures.push(`${route.method} ${route.path} → ${response.statusCode} ${response.raw}`);
      }
    }

    expect(nonPublic.length).toBeGreaterThan(25);
    expect(failures, `not 401 unauthenticated:\n  ${failures.join("\n  ")}`).toEqual([]);
  }, 90_000);

  // ── 2.5 ────────────────────────────────────────────────────────────────────
  it("2.5 granting the permission in the DATABASE changes behaviour with no code change or redeploy", async () => {
    const denied = await call(ctx.app, { method: "GET", url: "/api/users", cookie: viewer.cookie });
    expect(denied.statusCode).toBe(403);

    const permission = await ctx.prisma.permission.findUnique({ where: { key: "user:read" } });
    await ctx.prisma.rolePermission.create({
      data: { roleId: ROLE_IDS.viewer, permissionId: permission!.id },
    });

    // Same process, same code, same session — permissions are resolved per request (§7.3).
    const allowed = await call(ctx.app, { method: "GET", url: "/api/users", cookie: viewer.cookie });
    expect(allowed.statusCode).toBe(200);

    await ctx.prisma.rolePermission.delete({
      where: { roleId_permissionId: { roleId: ROLE_IDS.viewer, permissionId: permission!.id } },
    });

    const deniedAgain = await call(ctx.app, {
      method: "GET",
      url: "/api/users",
      cookie: viewer.cookie,
    });
    expect(deniedAgain.statusCode).toBe(403);
  }, 60_000);
});

/** A coarse state fingerprint — enough to prove "zero state changes" for ET-2 2.2. */
async function snapshot(ctx: TestApp) {
  const [users, invitations, secrets, agents, settings, sessions] = await Promise.all([
    ctx.prisma.user.count(),
    ctx.prisma.invitation.count(),
    ctx.prisma.secret.count(),
    ctx.prisma.agent.count(),
    ctx.prisma.systemSetting.count(),
    ctx.prisma.session.count({ where: { state: "REVOKED" } }),
  ]);
  return { users, invitations, secrets, agents, settings, revokedSessions: sessions };
}
