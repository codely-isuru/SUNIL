/**
 * ET-3 — Audit writes (PHASE1_REQUIREMENTS §5, steps 3.1–3.8).
 *
 * 3.1 is the expensive one and the important one: EVERY mutating route in the §13 surface is
 * exercised successfully, each with its own correlation id, and each must produce at least
 * one audit record carrying that id. The step table is checked against the enumerated route
 * set, so a new mutating route that nobody exercised fails this suite by name.
 *
 * 3.2 (the negative control) lives in `route-declarations.test.ts`, which is where the
 * coverage checker itself is proved to fail on an unaudited route.
 */
import { Writable } from "node:stream";
import { randomUUID } from "node:crypto";
import { afterAll, beforeAll, describe, expect, it } from "vitest";
import { ROLE_IDS } from "@sunil/core";
import { Secret, TOTP } from "otpauth";
import { API_CONTROLLERS } from "../app.module.js";
import { API_PREFIX } from "../app.factory.js";
import { describeControllerRoutes } from "../common/route-audit.js";
import { TOKENS } from "../tokens.js";
import type { AuditedUnitOfWork } from "../audit/audited-unit-of-work.js";
import {
  OWNER_EMAIL,
  OWNER_PASSWORD,
  TEST_DSN,
  call,
  createTestApp,
  inviteAndAccept,
  loginAsOwner,
  setCookieValue,
  type InjectResult,
  type Principal,
  type TestApp,
} from "./harness.js";

const describeDb = TEST_DSN ? describe : describe.skip;

function totp(base32: string, email: string, at = Date.now()): string {
  return new TOTP({
    issuer: "SUNIL",
    label: email,
    algorithm: "SHA1",
    digits: 6,
    period: 30,
    secret: Secret.fromBase32(base32),
  }).generate({ timestamp: at });
}

describeDb("ET-3 — audit writes", () => {
  let ctx: TestApp;
  let owner: Principal;

  beforeAll(async () => {
    ctx = await createTestApp();
    owner = await loginAsOwner(ctx.app);
  }, 60_000);

  afterAll(async () => {
    await ctx?.close();
  });

  // ── 3.1 ────────────────────────────────────────────────────────────────────
  it("3.1 every mutating route, exercised successfully, produces an audit record for its correlation id", async () => {
    const exercised: string[] = [];

    /** Run one mutating call under a fresh correlation id and assert it was recorded. */
    async function step(
      pattern: string,
      request: {
        method: "POST" | "PUT" | "PATCH" | "DELETE";
        url: string;
        payload?: unknown;
        cookie?: string;
        csrfToken?: string;
        expect?: number[];
      },
    ): Promise<InjectResult> {
      const correlationId = `et3-${randomUUID()}`;
      const response = await call(ctx.app, {
        method: request.method,
        url: request.url,
        ...(request.payload === undefined ? {} : { payload: request.payload }),
        ...(request.cookie ? { cookie: request.cookie } : {}),
        ...(request.csrfToken ? { csrfToken: request.csrfToken } : {}),
        headers: { "x-correlation-id": correlationId },
      });

      const accepted = request.expect ?? [200, 201, 202];
      expect(accepted, `${pattern} → ${response.statusCode} ${response.raw}`).toContain(
        response.statusCode,
      );

      const records = await ctx.prisma.auditLog.findMany({ where: { correlationId } });
      expect(records.length, `${pattern} produced no audit record`).toBeGreaterThan(0);
      expect(records.every((row) => row.createdAt instanceof Date)).toBe(true);

      exercised.push(`${request.method} ${pattern}`);
      return response;
    }

    // ---- identity / invitations ------------------------------------------------
    const loginResponse = await step("/api/auth/login", {
      method: "POST",
      url: "/api/auth/login",
      payload: { email: OWNER_EMAIL, password: OWNER_PASSWORD },
    });
    const ownerCookie = setCookieValue(loginResponse);
    const ownerCsrf = loginResponse.json<{ csrfToken: string }>().csrfToken;
    const asOwner = { cookie: ownerCookie, csrfToken: ownerCsrf };

    const inviteA = await step("/api/invitations", {
      method: "POST",
      url: "/api/invitations",
      payload: { email: `et3-accept-${Date.now()}@sunil.test`, roleId: ROLE_IDS.viewer },
      ...asOwner,
      expect: [201],
    });
    const acceptToken = inviteA.json<{ token: string }>().token;

    await step("/api/invitations/:token/accept", {
      method: "POST",
      url: `/api/invitations/${acceptToken}/accept`,
      payload: { password: "et3-accepted-passphrase-1" },
      expect: [201],
    });

    const inviteB = await step("/api/invitations", {
      method: "POST",
      url: "/api/invitations",
      payload: { email: `et3-revoke-${Date.now()}@sunil.test`, roleId: ROLE_IDS.viewer },
      ...asOwner,
      expect: [201],
    });
    await step("/api/invitations/:id", {
      method: "DELETE",
      url: `/api/invitations/${inviteB.json<{ id: string }>().id}`,
      ...asOwner,
    });

    const target = await inviteAndAccept(ctx.app, owner, ROLE_IDS.viewer, "et3-target-passphrase-1");

    await step("/api/users/:id", {
      method: "PATCH",
      url: `/api/users/${target.userId}`,
      payload: { displayName: "ET-3 Target" },
      ...asOwner,
    });
    await step("/api/users/:id/lockout/clear", {
      method: "POST",
      url: `/api/users/${target.userId}/lockout/clear`,
      ...asOwner,
    });
    await step("/api/users/:id/roles", {
      method: "PUT",
      url: `/api/users/${target.userId}/roles`,
      payload: { roleIds: [ROLE_IDS.viewer] },
      ...asOwner,
    });
    await step("/api/users/:id/sessions/revoke", {
      method: "POST",
      url: `/api/users/${target.userId}/sessions/revoke`,
      ...asOwner,
    });

    // ---- secrets ---------------------------------------------------------------
    const secret = await step("/api/secrets", {
      method: "POST",
      url: "/api/secrets",
      payload: { name: `et3-secret-${Date.now()}`, value: "et3-value", description: "" },
      ...asOwner,
      expect: [201],
    });
    const secretId = secret.json<{ id: string }>().id;

    await step("/api/secrets/:id/rotate", {
      method: "POST",
      url: `/api/secrets/${secretId}/rotate`,
      payload: { value: "et3-rotated" },
      ...asOwner,
    });
    await step("/api/secrets/:id", { method: "DELETE", url: `/api/secrets/${secretId}`, ...asOwner });

    // ---- platform --------------------------------------------------------------
    await step("/api/settings/:key", {
      method: "PATCH",
      url: "/api/settings/platform.displayName",
      payload: { value: "SUNIL" },
      ...asOwner,
    });

    const providers = await call(ctx.app, { method: "GET", url: "/api/providers", cookie: ownerCookie });
    const providerId = providers.json<{ items: { id: string }[] }>().items[0]!.id;
    await step("/api/providers/:id", {
      method: "PATCH",
      url: `/api/providers/${providerId}`,
      payload: { enabled: false },
      ...asOwner,
    });

    const agent = await step("/api/agents", {
      method: "POST",
      url: "/api/agents",
      payload: {
        slug: `et3-agent-${Date.now()}`,
        name: "ET-3 Agent",
        role: "fixture",
        systemInstructions: "none",
        maxDurationSeconds: 60,
        heartbeatIntervalSeconds: 30,
        staleThresholdSeconds: 90,
      },
      ...asOwner,
      expect: [201],
    });
    const agentId = agent.json<{ id: string }>().id;

    await step("/api/agents/:id", {
      method: "PATCH",
      url: `/api/agents/${agentId}`,
      payload: { name: "ET-3 Agent Renamed" },
      ...asOwner,
    });
    await step("/api/agents/:id/run", {
      method: "POST",
      url: `/api/agents/${agentId}/run`,
      ...asOwner,
      expect: [202],
    });

    // ---- self-service on a secondary principal --------------------------------
    const selfLogin = await call(ctx.app, {
      method: "POST",
      url: "/api/auth/login",
      payload: { email: target.email, password: "et3-target-passphrase-1" },
    });
    const selfCookie = setCookieValue(selfLogin);
    const selfCsrf = selfLogin.json<{ csrfToken: string }>().csrfToken;
    const asSelf = { cookie: selfCookie, csrfToken: selfCsrf };

    const sessions = await call(ctx.app, { method: "GET", url: "/api/auth/sessions", cookie: selfCookie });
    const revocableId = sessions
      .json<{ items: { id: string; state: string }[] }>()
      .items.find((s) => s.state === "REVOKED")!.id;
    await step("/api/auth/sessions/:id", {
      method: "DELETE",
      url: `/api/auth/sessions/${revocableId}`,
      ...asSelf,
    });

    await step("/api/auth/password", {
      method: "POST",
      url: "/api/auth/password",
      payload: {
        currentPassword: "et3-target-passphrase-1",
        newPassword: "et3-target-passphrase-2",
      },
      ...asSelf,
    });

    const enrol = await step("/api/auth/mfa/enrol", {
      method: "POST",
      url: "/api/auth/mfa/enrol",
      ...asSelf,
    });
    const mfaSecret = enrol.json<{ secret: string }>().secret;

    await step("/api/auth/mfa/activate", {
      method: "POST",
      url: "/api/auth/mfa/activate",
      payload: { code: totp(mfaSecret, target.email) },
      ...asSelf,
    });

    await step("/api/auth/logout", { method: "POST", url: "/api/auth/logout", ...asSelf });

    const challenge = await call(ctx.app, {
      method: "POST",
      url: "/api/auth/login",
      payload: { email: target.email, password: "et3-target-passphrase-2" },
    });
    const challengeCookie = setCookieValue(challenge);
    const challengeCsrf = challenge.json<{ csrfToken: string }>().csrfToken;

    const verified = await step("/api/auth/mfa/verify", {
      method: "POST",
      url: "/api/auth/mfa/verify",
      payload: { code: totp(mfaSecret, target.email, Date.now() + 30_000) },
      cookie: challengeCookie,
      csrfToken: challengeCsrf,
    });

    await step("/api/auth/mfa/disable", {
      method: "POST",
      url: "/api/auth/mfa/disable",
      payload: { password: "et3-target-passphrase-2" },
      cookie: setCookieValue(verified),
      csrfToken: verified.json<{ csrfToken: string }>().csrfToken,
    });

    // ---- coverage assertion ----------------------------------------------------
    const mutating = describeControllerRoutes(API_CONTROLLERS, API_PREFIX)
      .filter((route) => ["POST", "PUT", "PATCH", "DELETE"].includes(route.method))
      .map((route) => `${route.method} ${route.path}`);

    const missed = mutating.filter((route) => !exercised.includes(route));
    expect(
      missed,
      `mutating routes never exercised by ET-3 3.1:\n  ${missed.join("\n  ")}`,
    ).toEqual([]);
    expect(new Set(exercised).size).toBe(new Set(mutating).size);
  }, 180_000);

  // ── 3.3 ────────────────────────────────────────────────────────────────────
  it("3.3 denied mutations are audited with outcome FAILURE and a denial category", async () => {
    const viewer = await inviteAndAccept(ctx.app, owner, ROLE_IDS.viewer);

    const cases: { name: string; correlationId: string; expected: number; reason: string }[] = [];

    // 401 — unauthenticated mutation
    const unauth = `et3-denial-401-${randomUUID()}`;
    const unauthResponse = await call(ctx.app, {
      method: "POST",
      url: "/api/invitations",
      payload: { email: "denied@sunil.test", roleId: ROLE_IDS.viewer },
      headers: { "x-correlation-id": unauth },
    });
    cases.push({ name: "401", correlationId: unauth, expected: 401, reason: "unauthenticated" });
    expect(unauthResponse.statusCode).toBe(401);

    // 403 — authenticated but unauthorised
    const forbidden = `et3-denial-403-${randomUUID()}`;
    const forbiddenResponse = await call(ctx.app, {
      method: "POST",
      url: "/api/invitations",
      payload: { email: "denied@sunil.test", roleId: ROLE_IDS.viewer },
      cookie: viewer.cookie,
      csrfToken: viewer.csrfToken,
      headers: { "x-correlation-id": forbidden },
    });
    cases.push({ name: "403", correlationId: forbidden, expected: 403, reason: "forbidden" });
    expect(forbiddenResponse.statusCode).toBe(403);

    // 403 — CSRF
    const csrf = `et3-denial-csrf-${randomUUID()}`;
    const csrfResponse = await call(ctx.app, {
      method: "POST",
      url: "/api/invitations",
      payload: { email: "denied@sunil.test", roleId: ROLE_IDS.viewer },
      cookie: owner.cookie,
      headers: { "x-correlation-id": csrf },
    });
    cases.push({ name: "csrf", correlationId: csrf, expected: 403, reason: "csrf" });
    expect(csrfResponse.statusCode).toBe(403);

    for (const testCase of cases) {
      const records = await ctx.prisma.auditLog.findMany({
        where: { correlationId: testCase.correlationId },
      });
      expect(records.length, `${testCase.name} produced no denial record`).toBeGreaterThan(0);
      expect(records.every((row) => row.outcome === "FAILURE")).toBe(true);
      expect(records.map((row) => row.denialReason)).toContain(testCase.reason);
    }

    // 429 — rate limited. A dedicated app with a ceiling of one request per minute.
    const limited = await createTestApp({
      reset: false,
      env: { SUNIL_RATE_AUTH_IP_PER_MIN: "1" },
    });
    try {
      await call(limited.app, {
        method: "POST",
        url: "/api/auth/login",
        payload: { email: OWNER_EMAIL, password: "wrong" },
      });
      const rateCorrelation = `et3-denial-429-${randomUUID()}`;
      const throttled = await call(limited.app, {
        method: "POST",
        url: "/api/auth/login",
        payload: { email: OWNER_EMAIL, password: "wrong" },
        headers: { "x-correlation-id": rateCorrelation },
      });
      expect(throttled.statusCode).toBe(429);
      expect(throttled.headers["retry-after"]).toBeDefined();

      const records = await limited.prisma.auditLog.findMany({
        where: { correlationId: rateCorrelation },
      });
      expect(records.length).toBeGreaterThan(0);
      expect(records.map((row) => row.denialReason)).toContain("rate_limited");
    } finally {
      await limited.close();
    }
  }, 90_000);

  // ── 3.4 ────────────────────────────────────────────────────────────────────
  it("3.4 audit records cannot be updated or deleted through the application", async () => {
    const record = await ctx.prisma.auditLog.findFirst({ orderBy: { createdAt: "desc" } });
    expect(record).not.toBeNull();

    // Layer 1 — the Prisma client extension in `@sunil/db` refuses the operation.
    await expect(
      ctx.prisma.auditLog.update({ where: { id: record!.id }, data: { action: "tampered" } }),
    ).rejects.toThrow(/append-only/i);
    await expect(ctx.prisma.auditLog.delete({ where: { id: record!.id } })).rejects.toThrow(
      /append-only/i,
    );
    await expect(ctx.prisma.auditLog.deleteMany({})).rejects.toThrow(/append-only/i);

    // Layer 2 — the database trigger refuses it even for raw SQL through the app role.
    await expect(
      ctx.prisma.$executeRawUnsafe(`UPDATE audit_logs SET action = 'tampered' WHERE id = $1`, record!.id),
    ).rejects.toThrow(/append-only/i);
    await expect(
      ctx.prisma.$executeRawUnsafe(`DELETE FROM audit_logs WHERE id = $1`, record!.id),
    ).rejects.toThrow(/append-only/i);
  });

  // ── 3.5 ────────────────────────────────────────────────────────────────────
  it("3.5 reading the audit log without audit:read is 403", async () => {
    const target = await inviteAndAccept(ctx.app, owner, ROLE_IDS.agent);
    const response = await call(ctx.app, { method: "GET", url: "/api/audit", cookie: target.cookie });
    expect(response.statusCode).toBe(403);
    expect(response.json()).toEqual({ error: "FORBIDDEN" });
  }, 60_000);

  // ── 3.6 ────────────────────────────────────────────────────────────────────
  it("3.6 no audit payload contains secret plaintext or a password hash", async () => {
    const sentinel = `ET3-SENTINEL-${randomUUID()}`;
    const password = `et3-scan-passphrase-${randomUUID().slice(0, 8)}`;

    await call(ctx.app, {
      method: "POST",
      url: "/api/secrets",
      payload: { name: `et3-scan-${Date.now()}`, value: sentinel, description: "scanned" },
      cookie: owner.cookie,
      csrfToken: owner.csrfToken,
    });

    const invited = await inviteAndAccept(ctx.app, owner, ROLE_IDS.viewer, password);
    expect(invited.userId).toBeTruthy();

    const page = await call(ctx.app, {
      method: "GET",
      url: "/api/audit?pageSize=200",
      cookie: owner.cookie,
    });
    expect(page.statusCode).toBe(200);
    expect(page.raw).not.toContain(sentinel);
    expect(page.raw).not.toContain(password);
    expect(page.raw).not.toContain("$argon2");

    // And directly against the table, not only the API projection.
    const rows = await ctx.prisma.auditLog.findMany({ take: 500, orderBy: { createdAt: "desc" } });
    const serialised = JSON.stringify(rows);
    expect(serialised).not.toContain(sentinel);
    expect(serialised).not.toContain(password);
    expect(serialised).not.toContain("$argon2");
  }, 60_000);

  // ── 3.7 ────────────────────────────────────────────────────────────────────
  it("3.7 an agent-actor audit record round-trips with actorType AGENT and the agent id", async () => {
    const agent = await call(ctx.app, {
      method: "POST",
      url: "/api/agents",
      payload: {
        slug: `et3-actor-agent-${Date.now()}`,
        name: "Actor",
        role: "fixture",
        systemInstructions: "none",
        maxDurationSeconds: 60,
        heartbeatIntervalSeconds: 30,
        staleThresholdSeconds: 90,
      },
      cookie: owner.cookie,
      csrfToken: owner.csrfToken,
    });
    const agentId = agent.json<{ id: string; slug: string }>().id;
    const slug = agent.json<{ slug: string }>().slug;

    // Emitted through the shipped audit path, with the non-human actor override (§5.4).
    const uow = ctx.app.get<AuditedUnitOfWork>(TOKENS.UnitOfWork);
    await uow.recordOutOfBand({
      action: "agent.run",
      targetType: "agent",
      targetId: agentId,
      outcome: "SUCCESS",
      after: { emittedBy: "agent-runtime" },
      actorOverride: { actorType: "AGENT", actorId: agentId, actorLabel: `agent:${slug}` },
    });

    const record = await ctx.prisma.auditLog.findFirst({
      where: { actorType: "AGENT", actorId: agentId },
      orderBy: { createdAt: "desc" },
    });
    expect(record).not.toBeNull();
    expect(record!.actorType).toBe("AGENT");
    expect(record!.actorId).toBe(agentId);
    expect(record!.actorLabel).toBe(`agent:${slug}`);
  }, 60_000);

  // ── 3.8 ────────────────────────────────────────────────────────────────────
  it("3.8 one correlation id links an audited mutation to its structured log lines", async () => {
    const lines: string[] = [];
    const destination = new Writable({
      write(chunk: Buffer, _encoding, done) {
        lines.push(chunk.toString("utf8"));
        done();
      },
    });

    const logged = await createTestApp({
      reset: false,
      logger: { level: "info", destination },
    });
    try {
      const principal = await loginAsOwner(logged.app);
      const correlationId = `et3-correlated-${randomUUID()}`;

      const response = await call(logged.app, {
        method: "POST",
        url: "/api/invitations",
        payload: { email: `et3-log-${Date.now()}@sunil.test`, roleId: ROLE_IDS.viewer },
        cookie: principal.cookie,
        csrfToken: principal.csrfToken,
        headers: { "x-correlation-id": correlationId },
      });
      expect(response.statusCode).toBe(201);

      const record = await logged.prisma.auditLog.findFirst({ where: { correlationId } });
      expect(record, "no audit record for the correlation id").not.toBeNull();

      const output = lines.join("");
      expect(output, "correlation id absent from the structured log output").toContain(
        correlationId,
      );
      // The log lines are JSON, not free text (NFR-012).
      const parsed = output
        .split("\n")
        .filter((line) => line.trim().length > 0)
        .map((line) => JSON.parse(line) as { reqId?: string; req?: { id?: string } });
      expect(
        parsed.some((line) => line.reqId === correlationId || line.req?.id === correlationId),
      ).toBe(true);
    } finally {
      await logged.close();
    }
  }, 90_000);
});
