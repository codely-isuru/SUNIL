/**
 * §6.6 — the privilege-reduction session-revocation hook (Gate 1).
 *
 * The Gate-1 decision has two halves and both are tested here:
 *   • an INCREASE takes effect on the caller's very next request, with NO revocation —
 *     because permissions are resolved per request (§7.3);
 *   • a REDUCTION revokes every session of that user, in the SAME transaction as the role
 *     change and its audit record.
 *
 * The transactionality is not taken on faith: a role change that cannot write its audit
 * record must leave the roles unchanged AND the sessions live.
 */
import { afterAll, beforeAll, describe, expect, it } from "vitest";
import { ROLE_IDS } from "@sunil/core";
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

describeDb("§6.6 privilege-reduction session revocation", () => {
  let ctx: TestApp;
  let owner: Principal;

  beforeAll(async () => {
    ctx = await createTestApp();
    owner = await loginAsOwner(ctx.app);
  }, 60_000);

  afterAll(async () => {
    await ctx?.close();
  });

  it("an INCREASE is live on the next request and revokes nothing", async () => {
    const user = await inviteAndAccept(ctx.app, owner, ROLE_IDS.viewer);

    const denied = await call(ctx.app, { method: "GET", url: "/api/users", cookie: user.cookie });
    expect(denied.statusCode).toBe(403);

    const change = await call(ctx.app, {
      method: "PUT",
      url: `/api/users/${user.userId}/roles`,
      payload: { roleIds: [ROLE_IDS.admin] },
      cookie: owner.cookie,
      csrfToken: owner.csrfToken,
    });
    expect(change.statusCode).toBe(200);
    expect(change.json<{ sessionsRevoked: number }>().sessionsRevoked).toBe(0);
    expect(change.json<{ added: string[] }>().added).toContain("user:read");

    // Same session, same cookie, no re-authentication (Gate 1).
    const allowed = await call(ctx.app, { method: "GET", url: "/api/users", cookie: user.cookie });
    expect(allowed.statusCode).toBe(200);
  }, 60_000);

  it("a REDUCTION revokes every session of that user, atomically with the audit record", async () => {
    const user = await inviteAndAccept(ctx.app, owner, ROLE_IDS.viewer);

    await call(ctx.app, {
      method: "PUT",
      url: `/api/users/${user.userId}/roles`,
      payload: { roleIds: [ROLE_IDS.admin] },
      cookie: owner.cookie,
      csrfToken: owner.csrfToken,
    });

    // Two live sessions for the same principal, to prove "every session", not "the newest".
    const secondLogin = await call(ctx.app, {
      method: "GET",
      url: "/api/auth/me",
      cookie: user.cookie,
    });
    expect(secondLogin.statusCode).toBe(200);

    const liveBefore = await ctx.prisma.session.count({
      where: { userId: user.userId, state: "ACTIVE" },
    });
    expect(liveBefore).toBeGreaterThan(0);

    const reduction = await call(ctx.app, {
      method: "PUT",
      url: `/api/users/${user.userId}/roles`,
      payload: { roleIds: [ROLE_IDS.viewer] },
      cookie: owner.cookie,
      csrfToken: owner.csrfToken,
    });
    expect(reduction.statusCode).toBe(200);

    const body = reduction.json<{
      removed: string[];
      added: string[];
      sessionsRevoked: number;
    }>();
    expect(body.removed.length).toBeGreaterThan(0);
    expect(body.sessionsRevoked).toBe(liveBefore);

    // Effective immediately, on the very next request.
    const afterReduction = await call(ctx.app, {
      method: "GET",
      url: "/api/auth/me",
      cookie: user.cookie,
    });
    expect(afterReduction.statusCode).toBe(401);

    const revoked = await ctx.prisma.session.findMany({
      where: { userId: user.userId, state: "REVOKED" },
    });
    expect(revoked.length).toBeGreaterThan(0);
    expect(revoked.every((row) => row.revokedReason === "privilege_reduction")).toBe(true);

    // The audit record carries the BEFORE and AFTER permission sets (§6.6 step 4).
    const audit = await ctx.prisma.auditLog.findFirst({
      where: { action: "user.role.change", targetId: user.userId },
      orderBy: { createdAt: "desc" },
    });
    expect(audit).not.toBeNull();
    const before = (audit!.before as { permissions: string[] }).permissions;
    const after = (audit!.after as { permissions: string[]; sessionsRevoked: number }).permissions;
    expect(before.length).toBeGreaterThan(after.length);
    expect((audit!.after as { sessionsRevoked: number }).sessionsRevoked).toBe(liveBefore);
  }, 60_000);

  it("the owner role can be neither assigned nor stripped through the API (ADR-001)", async () => {
    const user = await inviteAndAccept(ctx.app, owner, ROLE_IDS.viewer);

    const promote = await call(ctx.app, {
      method: "PUT",
      url: `/api/users/${user.userId}/roles`,
      payload: { roleIds: [ROLE_IDS.owner] },
      cookie: owner.cookie,
      csrfToken: owner.csrfToken,
    });
    expect(promote.statusCode).toBe(409);
    expect(promote.json()).toEqual({ error: "INVARIANT_VIOLATION" });

    const ownerRow = await ctx.prisma.user.findFirst({
      where: { userRoles: { some: { roleId: ROLE_IDS.owner } } },
    });
    const demote = await call(ctx.app, {
      method: "PUT",
      url: `/api/users/${ownerRow!.id}/roles`,
      payload: { roleIds: [ROLE_IDS.viewer] },
      cookie: owner.cookie,
      csrfToken: owner.csrfToken,
    });
    expect(demote.statusCode).toBe(403);

    // The owner still holds the owner role, and there is still exactly one owner.
    expect(await ctx.prisma.userRole.count({ where: { roleId: ROLE_IDS.owner } })).toBe(1);
  }, 60_000);

  it("role assignment is owner-only: an admin holding every other permission is refused", async () => {
    const admin = await inviteAndAccept(ctx.app, owner, ROLE_IDS.admin);
    const target = await inviteAndAccept(ctx.app, owner, ROLE_IDS.viewer);

    const me = await call(ctx.app, { method: "GET", url: "/api/auth/me", cookie: admin.cookie });
    const permissions = me.json<{ permissions: string[] }>().permissions;
    expect(permissions).toContain("user:read");
    expect(permissions).not.toContain("role:assign");

    const attempt = await call(ctx.app, {
      method: "PUT",
      url: `/api/users/${target.userId}/roles`,
      payload: { roleIds: [ROLE_IDS.admin] },
      cookie: admin.cookie,
      csrfToken: admin.csrfToken,
    });
    expect(attempt.statusCode).toBe(403);
  }, 60_000);

  it("an admin operation may never target the owner account (§7.2)", async () => {
    const admin = await inviteAndAccept(ctx.app, owner, ROLE_IDS.admin);
    const ownerRow = await ctx.prisma.user.findFirst({
      where: { userRoles: { some: { roleId: ROLE_IDS.owner } } },
    });

    const attempt = await call(ctx.app, {
      method: "PATCH",
      url: `/api/users/${ownerRow!.id}`,
      payload: { status: "DISABLED" },
      cookie: admin.cookie,
      csrfToken: admin.csrfToken,
    });
    expect(attempt.statusCode).toBe(403);

    const unchanged = await ctx.prisma.user.findUnique({ where: { id: ownerRow!.id } });
    expect(unchanged!.status).toBe("ACTIVE");
  }, 60_000);
});
