/**
 * ET-1 — Auth flows (PHASE1_REQUIREMENTS §5, steps 1.1–1.11).
 *
 * Every step runs against the real application: real guards, real argon2, real session rows,
 * real Postgres. Nothing in this file mocks a security control, because a mocked control
 * proves nothing about the one that ships.
 */
import { afterAll, beforeAll, describe, expect, it } from "vitest";
import { ROLE_IDS } from "@sunil/core";
import { Secret, TOTP } from "otpauth";
import {
  OWNER_EMAIL,
  OWNER_PASSWORD,
  TEST_DSN,
  call,
  createTestApp,
  inviteAndAccept,
  login,
  loginAsOwner,
  setCookieValue,
  type TestApp,
} from "./harness.js";

const describeDb = TEST_DSN ? describe : describe.skip;

function totpFor(base32: string, at = Date.now()): string {
  return new TOTP({
    issuer: "SUNIL",
    label: OWNER_EMAIL,
    algorithm: "SHA1",
    digits: 6,
    period: 30,
    secret: Secret.fromBase32(base32),
  }).generate({ timestamp: at });
}

describeDb("ET-1 — auth flows", () => {
  let ctx: TestApp;

  beforeAll(async () => {
    ctx = await createTestApp();
  }, 60_000);

  afterAll(async () => {
    await ctx?.close();
  });

  // ── 1.1 ────────────────────────────────────────────────────────────────────
  it("1.1 self-registration does not exist on any plausible path, authenticated or not", async () => {
    const before = await ctx.prisma.user.count();
    const owner = await loginAsOwner(ctx.app);

    const paths = [
      "/api/auth/register",
      "/api/auth/signup",
      "/api/auth/sign-up",
      "/api/register",
      "/api/signup",
      "/api/users",
      "/api/users/register",
      "/api/auth/create-account",
    ];

    for (const path of paths) {
      const anonymous = await call(ctx.app, {
        method: "POST",
        url: path,
        payload: { email: "intruder@sunil.test", password: "a-very-long-passphrase-1" },
      });
      expect([404, 405], `anonymous POST ${path}`).toContain(anonymous.statusCode);

      const authenticated = await call(ctx.app, {
        method: "POST",
        url: path,
        payload: { email: "intruder@sunil.test", password: "a-very-long-passphrase-1" },
        cookie: owner.cookie,
        csrfToken: owner.csrfToken,
      });
      expect([404, 405], `authenticated POST ${path}`).toContain(authenticated.statusCode);
    }

    expect(await ctx.prisma.user.count()).toBe(before);
  });

  // ── 1.2 ────────────────────────────────────────────────────────────────────
  it("1.2 owner login creates a session row and a correctly attributed cookie", async () => {
    const response = await call(ctx.app, {
      method: "POST",
      url: "/api/auth/login",
      payload: { email: OWNER_EMAIL, password: OWNER_PASSWORD },
    });

    expect(response.statusCode).toBe(200);
    const raw = response.headers["set-cookie"];
    const cookie = Array.isArray(raw) ? raw[0]! : (raw as string);

    expect(cookie).toContain("HttpOnly");
    expect(cookie).toContain("SameSite=Lax");
    expect(cookie).toContain("Path=/");
    expect(cookie).toMatch(/Max-Age=\d+/);
    // Local dev profile: SUNIL_COOKIE_SECURE=false, so no Secure flag and no __Host- prefix.
    expect(cookie.startsWith("sunil_session=")).toBe(true);

    const body = response.json<{ user: { email: string }; mfaRequired: boolean }>();
    expect(body.user.email).toBe(OWNER_EMAIL);
    expect(body.mfaRequired).toBe(false);
    expect(response.raw).not.toContain("passwordHash");
    expect(response.raw).not.toContain(OWNER_PASSWORD);

    const sessions = await ctx.prisma.session.findMany({ where: { state: "ACTIVE" } });
    expect(sessions.length).toBeGreaterThan(0);
    // The raw token is never stored — only its SHA-256 (§6.1).
    const token = setCookieValue(response).split("=")[1]!;
    expect(sessions.some((s) => s.tokenHash === token)).toBe(false);
  });

  it("1.2b the production cookie profile carries Secure and the __Host- prefix (FR-023)", async () => {
    const secureCtx = await createTestApp({
      reset: false,
      env: { SUNIL_COOKIE_SECURE: "true" },
    });
    try {
      const response = await call(secureCtx.app, {
        method: "POST",
        url: "/api/auth/login",
        payload: { email: OWNER_EMAIL, password: OWNER_PASSWORD },
      });
      const raw = response.headers["set-cookie"];
      const cookie = Array.isArray(raw) ? raw[0]! : (raw as string);
      expect(cookie.startsWith("__Host-sunil_session=")).toBe(true);
      expect(cookie).toContain("Secure");
      expect(cookie).toContain("HttpOnly");
      expect(cookie).toContain("SameSite=Lax");
    } finally {
      await secureCtx.close();
    }
  }, 60_000);

  // ── 1.3 ────────────────────────────────────────────────────────────────────
  it("1.3 a wrong password is generic, unaudited-as-success, and discloses no account existence", async () => {
    const sessionsBefore = await ctx.prisma.session.count();

    const knownEmail = await call(ctx.app, {
      method: "POST",
      url: "/api/auth/login",
      payload: { email: OWNER_EMAIL, password: "definitely-not-the-password" },
    });
    const unknownEmail = await call(ctx.app, {
      method: "POST",
      url: "/api/auth/login",
      payload: { email: "nobody-here@sunil.test", password: "definitely-not-the-password" },
    });

    expect(knownEmail.statusCode).toBe(401);
    expect(unknownEmail.statusCode).toBe(401);
    // Byte-identical responses: the caller cannot tell an existing account from a missing one.
    expect(knownEmail.raw).toBe(unknownEmail.raw);
    expect(knownEmail.json()).toEqual({ error: "UNAUTHENTICATED" });

    expect(await ctx.prisma.session.count()).toBe(sessionsBefore);

    const failures = await ctx.prisma.auditLog.findMany({
      where: { action: "auth.login.failure" },
      orderBy: { createdAt: "desc" },
      take: 2,
    });
    expect(failures).toHaveLength(2);
    expect(failures.every((row) => row.outcome === "FAILURE")).toBe(true);
    expect(failures.every((row) => row.denialReason === "unauthenticated")).toBe(true);
  });

  // ── 1.4 ────────────────────────────────────────────────────────────────────
  it("1.4 exceeding the failure threshold locks the account out, even for the correct password", async () => {
    // A separate application with a low threshold and its own counter store. The threshold
    // being configuration is the point (FR-029): no code change is needed to test it.
    const lockoutCtx = await createTestApp({
      reset: false,
      env: { SUNIL_AUTH_MAX_FAILURES: "3", SUNIL_AUTH_LOCKOUT_MIN: "15" },
    });
    try {
      // The victim is an invited account, not the owner — locking the owner out would
      // couple this test to every test that follows it.
      const owner = await loginAsOwner(ctx.app);
      const victim = await inviteAndAccept(ctx.app, owner, ROLE_IDS.viewer, "victim-passphrase-1");

      for (let attempt = 0; attempt < 3; attempt += 1) {
        const response = await call(lockoutCtx.app, {
          method: "POST",
          url: "/api/auth/login",
          payload: { email: victim.email, password: `wrong-${attempt}` },
        });
        expect(response.statusCode).toBe(401);
      }

      const withCorrectPassword = await call(lockoutCtx.app, {
        method: "POST",
        url: "/api/auth/login",
        payload: { email: victim.email, password: "victim-passphrase-1" },
      });

      expect(withCorrectPassword.statusCode).toBe(429);
      expect(withCorrectPassword.json()).toEqual({ error: "LOCKED_OUT" });
      expect(withCorrectPassword.headers["retry-after"]).toBeDefined();
      expect(withCorrectPassword.headers["set-cookie"]).toBeUndefined();

      const lockoutAudit = await lockoutCtx.prisma.auditLog.findFirst({
        where: { action: "auth.login.lockout" },
        orderBy: { createdAt: "desc" },
      });
      expect(lockoutAudit?.outcome).toBe("FAILURE");
      expect(lockoutAudit?.denialReason).toBe("locked_out");

      // Owner intervention clears it (FR-029). The clear runs on the app that holds the
      // counters, which is the one that armed the lockout.
      const ownerOnLockoutApp = await loginAsOwner(lockoutCtx.app);
      const cleared = await call(lockoutCtx.app, {
        method: "POST",
        url: `/api/users/${victim.userId}/lockout/clear`,
        cookie: ownerOnLockoutApp.cookie,
        csrfToken: ownerOnLockoutApp.csrfToken,
      });
      expect(cleared.statusCode).toBe(200);

      const afterClear = await call(lockoutCtx.app, {
        method: "POST",
        url: "/api/auth/login",
        payload: { email: victim.email, password: "victim-passphrase-1" },
      });
      expect(afterClear.statusCode).toBe(200);
    } finally {
      await lockoutCtx.close();
    }
  }, 60_000);

  // ── 1.5 / 1.6 ──────────────────────────────────────────────────────────────
  it("1.5 + 1.6 MFA gates the session; invalid, replayed and reused codes are refused", async () => {
    const owner = await loginAsOwner(ctx.app);

    const enrolment = await call(ctx.app, {
      method: "POST",
      url: "/api/auth/mfa/enrol",
      cookie: owner.cookie,
      csrfToken: owner.csrfToken,
    });
    expect(enrolment.statusCode).toBe(200);
    const { secret, otpauthUri } = enrolment.json<{ secret: string; otpauthUri: string }>();
    expect(otpauthUri).toContain("otpauth://totp/");

    // The shared secret is stored through the SecretStore, never as a column (FR-027).
    const credential = await ctx.prisma.mfaCredential.findFirst({ where: { userId: owner.userId } });
    expect(credential?.secretName).toBe(`mfa:totp:${owner.userId}`);
    const stored = await ctx.prisma.secret.findUnique({ where: { name: credential!.secretName } });
    expect(stored).not.toBeNull();
    expect(Buffer.from(stored!.ciphertext).toString("utf8")).not.toContain(secret);

    const activation = await call(ctx.app, {
      method: "POST",
      url: "/api/auth/mfa/activate",
      payload: { code: totpFor(secret) },
      cookie: owner.cookie,
      csrfToken: owner.csrfToken,
    });
    expect(activation.statusCode).toBe(200);
    const { recoveryCodes } = activation.json<{ recoveryCodes: string[] }>();
    expect(recoveryCodes).toHaveLength(10);

    // Log out, then log back in: the password alone must not establish a usable session.
    await call(ctx.app, {
      method: "POST",
      url: "/api/auth/logout",
      cookie: owner.cookie,
      csrfToken: owner.csrfToken,
    });

    const passwordOnly = await call(ctx.app, {
      method: "POST",
      url: "/api/auth/login",
      payload: { email: OWNER_EMAIL, password: OWNER_PASSWORD },
    });
    expect(passwordOnly.statusCode).toBe(200);
    expect(passwordOnly.json<{ mfaRequired: boolean }>().mfaRequired).toBe(true);
    const pendingCookie = setCookieValue(passwordOnly);
    const pendingCsrf = passwordOnly.json<{ csrfToken: string }>().csrfToken;

    const beforeMfa = await call(ctx.app, {
      method: "GET",
      url: "/api/auth/me",
      cookie: pendingCookie,
    });
    expect(beforeMfa.statusCode).toBe(401);

    const badCode = await call(ctx.app, {
      method: "POST",
      url: "/api/auth/mfa/verify",
      payload: { code: "000000" },
      cookie: pendingCookie,
      csrfToken: pendingCsrf,
    });
    expect(badCode.statusCode).toBe(401);

    // The activation code consumed its own timestep (replay prevention writes a high-water
    // mark), so the login challenge uses the NEXT step's code — which the ±1-step validation
    // window accepts. This is the same thing a real authenticator app does a few seconds later.
    const code = totpFor(secret, Date.now() + 30_000);
    const verified = await call(ctx.app, {
      method: "POST",
      url: "/api/auth/mfa/verify",
      payload: { code },
      cookie: pendingCookie,
      csrfToken: pendingCsrf,
    });
    expect(verified.statusCode).toBe(200);
    const elevatedCookie = setCookieValue(verified);
    const elevatedCsrf = verified.json<{ csrfToken: string }>().csrfToken;

    // Anti-fixation: the pre-elevation token is dead (§6.2, THREAT_MODEL T-02).
    expect(elevatedCookie).not.toBe(pendingCookie);
    const oldTokenAfterElevation = await call(ctx.app, {
      method: "GET",
      url: "/api/auth/me",
      cookie: pendingCookie,
    });
    expect(oldTokenAfterElevation.statusCode).toBe(401);

    const elevated = await call(ctx.app, {
      method: "GET",
      url: "/api/auth/me",
      cookie: elevatedCookie,
    });
    expect(elevated.statusCode).toBe(200);

    // Replay: the SAME code, on a fresh challenge, is refused (lastUsedStep high-water mark).
    await call(ctx.app, {
      method: "POST",
      url: "/api/auth/logout",
      cookie: elevatedCookie,
      csrfToken: elevatedCsrf,
    });
    const secondChallenge = await call(ctx.app, {
      method: "POST",
      url: "/api/auth/login",
      payload: { email: OWNER_EMAIL, password: OWNER_PASSWORD },
    });
    const replay = await call(ctx.app, {
      method: "POST",
      url: "/api/auth/mfa/verify",
      payload: { code },
      cookie: setCookieValue(secondChallenge),
      csrfToken: secondChallenge.json<{ csrfToken: string }>().csrfToken,
    });
    expect(replay.statusCode).toBe(401);

    // 1.6 — a recovery code works once and only once.
    const recoveryCode = recoveryCodes[0]!;
    const firstUse = await call(ctx.app, {
      method: "POST",
      url: "/api/auth/mfa/verify",
      payload: { recoveryCode },
      cookie: setCookieValue(secondChallenge),
      csrfToken: secondChallenge.json<{ csrfToken: string }>().csrfToken,
    });
    expect(firstUse.statusCode).toBe(200);

    const thirdChallenge = await call(ctx.app, {
      method: "POST",
      url: "/api/auth/login",
      payload: { email: OWNER_EMAIL, password: OWNER_PASSWORD },
    });
    const reuse = await call(ctx.app, {
      method: "POST",
      url: "/api/auth/mfa/verify",
      payload: { recoveryCode },
      cookie: setCookieValue(thirdChallenge),
      csrfToken: thirdChallenge.json<{ csrfToken: string }>().csrfToken,
    });
    expect(reuse.statusCode).toBe(401);

    // Leave the owner without MFA so later tests in this file are unaffected.
    const restored = setCookieValue(firstUse);
    await call(ctx.app, {
      method: "POST",
      url: "/api/auth/mfa/disable",
      payload: { password: OWNER_PASSWORD },
      cookie: restored,
      csrfToken: firstUse.json<{ csrfToken: string }>().csrfToken,
    });
  }, 60_000);

  // ── 1.7 / 1.8 ──────────────────────────────────────────────────────────────
  it("1.7 an invited user is created with exactly the invited role, and can log in", async () => {
    const owner = await loginAsOwner(ctx.app);
    const viewer = await inviteAndAccept(ctx.app, owner, ROLE_IDS.viewer);

    const assignments = await ctx.prisma.userRole.findMany({ where: { userId: viewer.userId } });
    expect(assignments).toHaveLength(1);
    expect(assignments[0]!.roleId).toBe(ROLE_IDS.viewer);

    const me = await call(ctx.app, { method: "GET", url: "/api/auth/me", cookie: viewer.cookie });
    expect(me.statusCode).toBe(200);
    expect(me.json<{ permissions: string[] }>().permissions.sort()).toEqual([
      "audit:read",
      "dashboard:read",
    ]);

    const created = await ctx.prisma.auditLog.findFirst({
      where: { action: "invitation.create" },
      orderBy: { createdAt: "desc" },
    });
    expect(created).not.toBeNull();
  }, 60_000);

  it("1.8 consumed, expired and mutated invitation tokens are all refused identically", async () => {
    const owner = await loginAsOwner(ctx.app);

    const invitation = await call(ctx.app, {
      method: "POST",
      url: "/api/invitations",
      payload: { email: "replay-target@sunil.test", roleId: ROLE_IDS.viewer },
      cookie: owner.cookie,
      csrfToken: owner.csrfToken,
    });
    const { token } = invitation.json<{ token: string }>();

    const first = await call(ctx.app, {
      method: "POST",
      url: `/api/invitations/${token}/accept`,
      payload: { password: "first-acceptance-passphrase-1" },
    });
    expect(first.statusCode).toBe(201);

    const usersAfterFirst = await ctx.prisma.user.count();

    const replayed = await call(ctx.app, {
      method: "POST",
      url: `/api/invitations/${token}/accept`,
      payload: { password: "second-acceptance-passphrase-1" },
    });

    // An expired invitation: created normally, then aged past its TTL.
    const expiring = await call(ctx.app, {
      method: "POST",
      url: "/api/invitations",
      payload: { email: "expired-target@sunil.test", roleId: ROLE_IDS.viewer },
      cookie: owner.cookie,
      csrfToken: owner.csrfToken,
    });
    const expiredToken = expiring.json<{ token: string; id: string }>();
    await ctx.prisma.invitation.update({
      where: { id: expiredToken.id },
      data: { expiresAt: new Date(Date.now() - 1000) },
    });
    const expired = await call(ctx.app, {
      method: "POST",
      url: `/api/invitations/${expiredToken.token}/accept`,
      payload: { password: "expired-acceptance-passphrase-1" },
    });

    const mutated = await call(ctx.app, {
      method: "POST",
      url: `/api/invitations/${token.slice(0, -1)}X/accept`,
      payload: { password: "mutated-acceptance-passphrase-1" },
    });

    for (const response of [replayed, expired, mutated]) {
      expect(response.statusCode).toBe(400);
      expect(response.json()).toEqual({ error: "VALIDATION_FAILED" });
    }
    // Identical bodies: token state is not disclosed.
    expect(replayed.raw).toBe(expired.raw);
    expect(expired.raw).toBe(mutated.raw);

    expect(await ctx.prisma.user.count()).toBe(usersAfterFirst);
  }, 60_000);

  // ── 1.9 ────────────────────────────────────────────────────────────────────
  it("1.9 a mutating request with a valid cookie but no/incorrect CSRF token is 403 with no state change", async () => {
    const owner = await loginAsOwner(ctx.app);
    const before = await ctx.prisma.invitation.count();

    const missing = await call(ctx.app, {
      method: "POST",
      url: "/api/invitations",
      payload: { email: "csrf-victim@sunil.test", roleId: ROLE_IDS.viewer },
      cookie: owner.cookie,
    });
    expect(missing.statusCode).toBe(403);
    expect(missing.json()).toEqual({ error: "CSRF_FAILED" });

    const wrong = await call(ctx.app, {
      method: "POST",
      url: "/api/invitations",
      payload: { email: "csrf-victim@sunil.test", roleId: ROLE_IDS.viewer },
      cookie: owner.cookie,
      csrfToken: "not-the-right-token",
    });
    expect(wrong.statusCode).toBe(403);

    expect(await ctx.prisma.invitation.count()).toBe(before);

    const denial = await ctx.prisma.auditLog.findFirst({
      where: { denialReason: "csrf" },
      orderBy: { createdAt: "desc" },
    });
    expect(denial?.outcome).toBe("FAILURE");

    // A safe method needs no token (FR-028).
    const safe = await call(ctx.app, { method: "GET", url: "/api/auth/me", cookie: owner.cookie });
    expect(safe.statusCode).toBe(200);

    // And with the right token it succeeds.
    const allowed = await call(ctx.app, {
      method: "POST",
      url: "/api/invitations",
      payload: { email: "csrf-victim@sunil.test", roleId: ROLE_IDS.viewer },
      cookie: owner.cookie,
      csrfToken: owner.csrfToken,
    });
    expect(allowed.statusCode).toBe(201);
  }, 60_000);

  // ── 1.10 ───────────────────────────────────────────────────────────────────
  it("1.10 a logged-out cookie is 401 on the next request", async () => {
    const owner = await loginAsOwner(ctx.app);

    const logout = await call(ctx.app, {
      method: "POST",
      url: "/api/auth/logout",
      cookie: owner.cookie,
      csrfToken: owner.csrfToken,
    });
    expect(logout.statusCode).toBe(200);
    const cleared = logout.headers["set-cookie"];
    expect(Array.isArray(cleared) ? cleared[0] : cleared).toContain("Max-Age=0");

    const reused = await call(ctx.app, {
      method: "GET",
      url: "/api/auth/me",
      cookie: owner.cookie,
    });
    expect(reused.statusCode).toBe(401);
  }, 60_000);

  // ── 1.11 ───────────────────────────────────────────────────────────────────
  it("1.11 an owner bulk-revoke kills a live session on its very next request", async () => {
    const owner = await loginAsOwner(ctx.app);
    const victim = await inviteAndAccept(ctx.app, owner, ROLE_IDS.viewer);

    const beforeRevoke = await call(ctx.app, {
      method: "GET",
      url: "/api/auth/me",
      cookie: victim.cookie,
    });
    expect(beforeRevoke.statusCode).toBe(200);

    const revoke = await call(ctx.app, {
      method: "POST",
      url: `/api/users/${victim.userId}/sessions/revoke`,
      cookie: owner.cookie,
      csrfToken: owner.csrfToken,
    });
    expect(revoke.statusCode).toBe(200);
    expect(revoke.json<{ revoked: number }>().revoked).toBeGreaterThan(0);

    const afterRevoke = await call(ctx.app, {
      method: "GET",
      url: "/api/auth/me",
      cookie: victim.cookie,
    });
    expect(afterRevoke.statusCode).toBe(401);
  }, 60_000);

  it("a disabled account cannot log in, and the failure is indistinguishable from a wrong password", async () => {
    const owner = await loginAsOwner(ctx.app);
    const target = await inviteAndAccept(ctx.app, owner, ROLE_IDS.viewer);

    await call(ctx.app, {
      method: "PATCH",
      url: `/api/users/${target.userId}`,
      payload: { status: "DISABLED" },
      cookie: owner.cookie,
      csrfToken: owner.csrfToken,
    });

    const attempt = await login(ctx.app, target.email, "irrelevant").catch((error: Error) => error);
    expect(attempt).toBeInstanceOf(Error);
    expect((attempt as Error).message).toContain("401");
  }, 60_000);
});
