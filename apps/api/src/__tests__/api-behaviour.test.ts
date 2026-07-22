/**
 * The remaining Phase 1 behaviours that are not an exit test in their own right:
 * OpenAPI generation (§13/FR-020), KEK rotation (§8.2), the runtime audit tally (§9.4),
 * per-session rate limiting (§6.3) and idempotency keys.
 */
import { randomUUID } from "node:crypto";
import { Controller, HttpCode, Post } from "@nestjs/common";
import { afterAll, beforeAll, describe, expect, it } from "vitest";
import { ROLE_IDS, type SecretStore } from "@sunil/core";
import { buildOpenApiDocument, findForbiddenOperations } from "../openapi.js";
import { Audited, Public } from "../common/declarations.js";
import { TOKENS } from "../tokens.js";
import {
  TEST_DSN,
  call,
  createTestApp,
  loginAsOwner,
  testMasterKey,
  type Principal,
  type TestApp,
} from "./harness.js";

const describeDb = TEST_DSN ? describe : describe.skip;

/**
 * §9.4's runtime control, as a fixture: a mutating route that is correctly DECLARED and
 * correctly marked `@Audited`, but never actually writes a record. The build-time
 * enumeration test cannot catch this — only the tally can.
 */
@Controller("et-tally")
class SilentMutationController {
  @Post("mutate")
  @Public()
  @Audited("agent.run")
  @HttpCode(200)
  mutate() {
    return { ok: true };
  }
}

describeDb("OpenAPI (§13, FR-020)", () => {
  let ctx: TestApp;

  beforeAll(async () => {
    ctx = await createTestApp();
  }, 60_000);

  afterAll(async () => {
    await ctx?.close();
  });

  it("generates a document covering the §13 surface with no registration operation", () => {
    const document = buildOpenApiDocument(ctx.app);
    const paths = Object.keys(document.paths ?? {});

    expect(paths.length).toBeGreaterThan(25);
    expect(paths).toContain("/api/auth/login");
    expect(paths).toContain("/api/secrets");
    expect(findForbiddenOperations(document)).toEqual([]);
  });

  it("contains no secret material in any example or schema", async () => {
    const owner = await loginAsOwner(ctx.app);
    const sentinel = `OPENAPI-SENTINEL-${randomUUID()}`;
    await call(ctx.app, {
      method: "POST",
      url: "/api/secrets",
      payload: { name: `openapi-${Date.now()}`, value: sentinel, description: "" },
      cookie: owner.cookie,
      csrfToken: owner.csrfToken,
    });

    const serialised = JSON.stringify(buildOpenApiDocument(ctx.app));
    expect(serialised).not.toContain(sentinel);
    expect(serialised).not.toMatch(/sk-[A-Za-z0-9]{16,}/);
    expect(serialised).not.toContain("BEGIN PRIVATE KEY");
  }, 60_000);
});

describeDb("§8.2 KEK rotation", () => {
  const currentKey = testMasterKey();
  const rotatedKey = Buffer.alloc(32, 11).toString("base64");
  const secretName = `kek-rotation-${Date.now()}`;
  const secretValue = `kek-value-${randomUUID()}`;

  let first: TestApp;

  beforeAll(async () => {
    first = await createTestApp();
    const store = first.app.get<SecretStore>(TOKENS.SecretStore);
    await store.put(secretName, secretValue, { description: "written under KEK v1" });
  }, 60_000);

  afterAll(async () => {
    await first?.close();
  });

  it("reads a secret wrapped under the PREVIOUS KEK and lazily re-wraps it under the current one", async () => {
    const beforeRotation = await first.prisma.secret.findUnique({ where: { name: secretName } });
    expect(beforeRotation!.masterKeyVersion).toBe(1);

    const rotated = await createTestApp({
      reset: false,
      env: {
        SUNIL_MASTER_KEY: rotatedKey,
        SUNIL_MASTER_KEY_PREVIOUS: currentKey,
        SUNIL_MASTER_KEY_VERSION: "2",
      },
    });

    try {
      const store = rotated.app.get<SecretStore>(TOKENS.SecretStore);
      const value = await store.get(secretName);
      expect(value.use((plaintext) => plaintext)).toBe(secretValue);

      const afterRotation = await rotated.prisma.secret.findUnique({ where: { name: secretName } });
      expect(afterRotation!.masterKeyVersion).toBe(2);
      // Only the DEK wrapping changed; the value ciphertext and its version did not.
      expect(afterRotation!.version).toBe(beforeRotation!.version);
      expect(
        Buffer.from(afterRotation!.wrappedDek).equals(Buffer.from(beforeRotation!.wrappedDek)),
      ).toBe(false);

      // Reading again under the current KEK alone still works.
      const again = await store.get(secretName);
      expect(again.use((plaintext) => plaintext)).toBe(secretValue);
    } finally {
      await rotated.close();
    }
  }, 90_000);

  it("refuses to decrypt a secret whose KEK version is not available", async () => {
    const orphaned = await createTestApp({
      reset: false,
      env: { SUNIL_MASTER_KEY: rotatedKey, SUNIL_MASTER_KEY_VERSION: "5" },
    });
    try {
      const store = orphaned.app.get<SecretStore>(TOKENS.SecretStore);
      await expect(store.get(secretName)).rejects.toMatchObject({ code: "SECRET_INTEGRITY" });
    } finally {
      await orphaned.close();
    }
  }, 90_000);
});

describeDb("§9.4 the runtime audit tally", () => {
  let ctx: TestApp;

  beforeAll(async () => {
    ctx = await createTestApp({ extraControllers: [SilentMutationController] });
  }, 60_000);

  afterAll(async () => {
    await ctx?.close();
  });

  it("refuses to return a successful mutating response that wrote no audit record", async () => {
    const response = await call(ctx.app, { method: "POST", url: "/api/et-tally/mutate" });
    expect(response.statusCode).toBe(500);
    expect(response.json()).toEqual({ error: "INTERNAL" });
    expect(response.raw).not.toContain("ok");
  });

  it("lets a properly audited mutation through", async () => {
    const owner = await loginAsOwner(ctx.app);
    const response = await call(ctx.app, {
      method: "POST",
      url: "/api/invitations",
      payload: { email: `tally-${Date.now()}@sunil.test`, roleId: ROLE_IDS.viewer },
      cookie: owner.cookie,
      csrfToken: owner.csrfToken,
    });
    expect(response.statusCode).toBe(201);
  }, 60_000);
});

describeDb("§6.3 per-session rate limiting and idempotency", () => {
  let ctx: TestApp;
  let owner: Principal;

  beforeAll(async () => {
    ctx = await createTestApp({ env: { SUNIL_RATE_SESSION_PER_MIN: "5" } });
    owner = await loginAsOwner(ctx.app);
  }, 60_000);

  afterAll(async () => {
    await ctx?.close();
  });

  it("returns 429 with Retry-After once the per-session ceiling is passed", async () => {
    const statuses: number[] = [];
    for (let i = 0; i < 8; i += 1) {
      const response = await call(ctx.app, {
        method: "GET",
        url: "/api/auth/me",
        cookie: owner.cookie,
      });
      statuses.push(response.statusCode);
      if (response.statusCode === 429) {
        expect(response.headers["retry-after"]).toBeDefined();
        expect(response.json()).toEqual({ error: "RATE_LIMITED" });
      }
    }
    expect(statuses.filter((s) => s === 200).length).toBeGreaterThan(0);
    expect(statuses).toContain(429);
  }, 60_000);

  it("replays an Idempotency-Key rather than creating a second invitation", async () => {
    const limited = await createTestApp({ reset: false });
    try {
      const principal = await loginAsOwner(limited.app);
      const key = `idem-${randomUUID()}`;
      const email = `idem-${Date.now()}@sunil.test`;
      const before = await limited.prisma.invitation.count();

      const first = await call(limited.app, {
        method: "POST",
        url: "/api/invitations",
        payload: { email, roleId: ROLE_IDS.viewer },
        cookie: principal.cookie,
        csrfToken: principal.csrfToken,
        headers: { "idempotency-key": key },
      });
      expect(first.statusCode).toBe(201);

      const replay = await call(limited.app, {
        method: "POST",
        url: "/api/invitations",
        payload: { email, roleId: ROLE_IDS.viewer },
        cookie: principal.cookie,
        csrfToken: principal.csrfToken,
        headers: { "idempotency-key": key },
      });
      expect(replay.statusCode).toBe(201);
      expect(replay.json<{ id: string }>().id).toBe(first.json<{ id: string }>().id);

      // Exactly one row, despite two requests.
      expect(await limited.prisma.invitation.count()).toBe(before + 1);
    } finally {
      await limited.close();
    }
  }, 90_000);
});
