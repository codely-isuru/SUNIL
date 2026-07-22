/**
 * ET-5 — Secret round-trip never exposes plaintext via an API
 * (PHASE1_REQUIREMENTS §5, steps 5.1–5.11).
 *
 * A single sentinel value is stored, exercised and then hunted for: in every response body
 * captured during this file's run, in every response header, in the OpenAPI document, in the
 * complete structured log output, in `usage_records`, and in the audit log. Zero matches is
 * the pass condition.
 *
 * 5.7 (the portal bundle) is out of scope for `apps/api` — `apps/web` owns it. Everything
 * this app can contribute to it is 5.5/5.6: nothing leaves the API in the first place.
 */
import { Writable } from "node:stream";
import { randomUUID } from "node:crypto";
import { Controller, Get } from "@nestjs/common";
import { afterAll, beforeAll, describe, expect, it } from "vitest";
import { SecretValue, secretNameFor, type SecretStore } from "@sunil/core";
import { API_CONTROLLERS } from "../app.module.js";
import { API_PREFIX } from "../app.factory.js";
import { describeControllerRoutes } from "../common/route-audit.js";
import { buildOpenApiDocument, findForbiddenOperations } from "../openapi.js";
import { Public } from "../common/declarations.js";
import { InMemorySecretStore } from "../secrets/in-memory-secret-store.js";
import { fingerprintOf } from "../secrets/fingerprint.js";
import { TOKENS } from "../tokens.js";
import {
  TEST_DSN,
  call,
  createTestApp,
  loginAsOwner,
  type InjectResult,
  type Principal,
  type TestApp,
} from "./harness.js";

const describeDb = TEST_DSN ? describe : describe.skip;

/** The sentinel. Unique per run so a stale row cannot make this test pass by accident. */
const SENTINEL = `SUNIL-ET5-SENTINEL-${randomUUID().replace(/-/g, "")}`;
const ROTATED_SENTINEL = `SUNIL-ET5-ROTATED-${randomUUID().replace(/-/g, "")}`;

/** Every response this file produces, for the 5.6 sweep. */
const captured: { url: string; body: string; headers: string }[] = [];

function capture(url: string, response: InjectResult): InjectResult {
  captured.push({ url, body: response.raw, headers: JSON.stringify(response.headers) });
  return response;
}

/**
 * §8.4 layer 2's negative control: a route that tries to serialise a `SecretValue`.
 * The interceptor must THROW rather than emit the redaction marker — a marker in a response
 * body means a developer wired a secret into a DTO and nobody noticed.
 */
@Controller("et5-leak")
class LeakyController {
  @Get("secret-value")
  @Public()
  leak() {
    return { credential: new SecretValue("et5:leak", SENTINEL) };
  }

  @Get("nested-secret-value")
  @Public()
  leakNested() {
    return { data: { items: [{ credential: new SecretValue("et5:leak", SENTINEL) }] } };
  }
}

describe("ET-5 — SecretValue and fingerprint mechanics (no database required)", () => {
  it("SecretValue yields the redaction marker on every serialisation path (§8.4)", () => {
    const value = new SecretValue("test", SENTINEL);
    expect(JSON.stringify(value)).toBe('"[REDACTED]"');
    expect(String(value)).toBe("[REDACTED]");
    expect(`${value}`).toBe("[REDACTED]");
    expect(JSON.stringify({ nested: { credential: value } })).not.toContain(SENTINEL);
    // The plaintext is reachable only through use().
    expect(value.use((plaintext) => plaintext)).toBe(SENTINEL);
  });

  it("the fingerprint is the ONLY value-derived datum, and it discloses at most four characters", () => {
    const fingerprint = fingerprintOf(SENTINEL);
    expect(fingerprint).toContain(SENTINEL.slice(-4));
    expect(fingerprint).not.toContain(SENTINEL);
    expect(fingerprint).toMatch(/^….{1,4} \/ sha256:[0-9a-f]{8}$/);
  });

  it("FR-040 swappability: the in-memory double satisfies the same interface", async () => {
    const store: SecretStore = new InMemorySecretStore();
    const metadata = await store.put("swap:test", SENTINEL, { description: "double" });
    expect(metadata.fingerprint).toBe(fingerprintOf(SENTINEL));

    const value = await store.get("swap:test");
    expect(value.use((plaintext) => plaintext)).toBe(SENTINEL);
    expect(JSON.stringify(value)).not.toContain(SENTINEL);

    const rotated = await store.rotate("swap:test", ROTATED_SENTINEL);
    expect(rotated.version).toBe(2);
    expect((await store.get("swap:test")).use((p) => p)).toBe(ROTATED_SENTINEL);

    await store.delete("swap:test");
    await expect(store.describe("swap:test")).rejects.toThrow();
  });
});

describeDb("ET-5 — secret round-trip", () => {
  let ctx: TestApp;
  let owner: Principal;
  let secretId: string;
  let secretName: string;

  beforeAll(async () => {
    ctx = await createTestApp({ extraControllers: [LeakyController] });
    owner = await loginAsOwner(ctx.app);
    secretName = `et5-sentinel-${Date.now()}`;
  }, 60_000);

  afterAll(async () => {
    await ctx?.close();
  });

  // ── 5.1 ────────────────────────────────────────────────────────────────────
  it("5.1 storing the sentinel returns metadata only — no secret in the response", async () => {
    const response = capture(
      "POST /api/secrets",
      await call(ctx.app, {
        method: "POST",
        url: "/api/secrets",
        payload: { name: secretName, value: SENTINEL, description: "ET-5 sentinel" },
        cookie: owner.cookie,
        csrfToken: owner.csrfToken,
      }),
    );

    expect(response.statusCode).toBe(201);
    const body = response.json<{ id: string; fingerprint: string; version: number }>();
    secretId = body.id;

    expect(response.raw).not.toContain(SENTINEL);
    expect(body.fingerprint).toBe(fingerprintOf(SENTINEL));
    expect(body.version).toBe(1);
    // The DTO is allowlisted: no ciphertext, no key material, no value field.
    expect(Object.keys(body).sort()).toEqual([
      "createdAt",
      "description",
      "fingerprint",
      "id",
      "masterKeyVersion",
      "name",
      "rotatedAt",
      "updatedAt",
      "version",
    ]);
  });

  // ── 5.2 ────────────────────────────────────────────────────────────────────
  it("5.2 the stored row holds ciphertext, a unique IV, an auth tag and a key reference — never the plaintext", async () => {
    const row = await ctx.prisma.secret.findUnique({ where: { name: secretName } });
    expect(row).not.toBeNull();

    expect(row!.ciphertext.byteLength).toBeGreaterThan(0);
    expect(row!.iv.byteLength).toBe(12);
    expect(row!.authTag.byteLength).toBe(16);
    expect(row!.wrappedDek.byteLength).toBeGreaterThan(0);
    expect(row!.dekIv.byteLength).toBe(12);
    expect(row!.dekAuthTag.byteLength).toBe(16);
    expect(row!.masterKeyVersion).toBe(1);

    const asText = Buffer.from(row!.ciphertext).toString("utf8");
    const asHex = Buffer.from(row!.ciphertext).toString("hex");
    expect(asText).not.toContain(SENTINEL);
    expect(asHex).not.toContain(Buffer.from(SENTINEL, "utf8").toString("hex"));
    expect(JSON.stringify(row)).not.toContain(SENTINEL);
  });

  // ── 5.3 ────────────────────────────────────────────────────────────────────
  it("5.3 the same plaintext stored twice produces different ciphertexts (unique IV per encryption)", async () => {
    const second = `${secretName}-twin`;
    await call(ctx.app, {
      method: "POST",
      url: "/api/secrets",
      payload: { name: second, value: SENTINEL, description: "twin" },
      cookie: owner.cookie,
      csrfToken: owner.csrfToken,
    });

    const [a, b] = await Promise.all([
      ctx.prisma.secret.findUnique({ where: { name: secretName } }),
      ctx.prisma.secret.findUnique({ where: { name: second } }),
    ]);

    expect(Buffer.from(a!.iv).equals(Buffer.from(b!.iv))).toBe(false);
    expect(Buffer.from(a!.ciphertext).equals(Buffer.from(b!.ciphertext))).toBe(false);
    // Same plaintext, so the same fingerprint — the fingerprint is a display mask, not a key.
    expect(a!.fingerprint).toBe(b!.fingerprint);
  });

  // ── 5.4 ────────────────────────────────────────────────────────────────────
  it("5.4 the secret round-trips correctly into a mocked provider transport", async () => {
    const store = ctx.app.get<SecretStore>(TOKENS.SecretStore);
    const value = await store.get(secretName);

    // The transport seam (ADR-008): the plaintext is handed straight into the client
    // constructor inside `use()`, never assigned to a variable that outlives it.
    let sawAuthorizationHeader: string | undefined;
    const mockTransport = async (headers: Record<string, string>): Promise<number> => {
      sawAuthorizationHeader = headers["authorization"];
      return 200;
    };

    const status = await value.use((plaintext) =>
      mockTransport({ authorization: `Bearer ${plaintext}` }),
    );

    expect(status).toBe(200);
    expect(sawAuthorizationHeader).toBe(`Bearer ${SENTINEL}`);
  });

  // ── §8.4 layer 2 ───────────────────────────────────────────────────────────
  it("the serialisation interceptor THROWS if a SecretValue reaches a response (§8.4)", async () => {
    const direct = capture(
      "GET /api/et5-leak/secret-value",
      await call(ctx.app, { method: "GET", url: "/api/et5-leak/secret-value" }),
    );
    expect(direct.statusCode).toBe(500);
    expect(direct.raw).not.toContain(SENTINEL);
    expect(direct.raw).not.toContain("[REDACTED]");
    expect(direct.json()).toEqual({ error: "INTERNAL" });

    const nested = capture(
      "GET /api/et5-leak/nested-secret-value",
      await call(ctx.app, { method: "GET", url: "/api/et5-leak/nested-secret-value" }),
    );
    expect(nested.statusCode).toBe(500);
    expect(nested.raw).not.toContain(SENTINEL);
  });

  // ── 5.5 ────────────────────────────────────────────────────────────────────
  it("5.5 no Phase 1 endpoint that could plausibly return the secret does so", async () => {
    const readable = describeControllerRoutes(API_CONTROLLERS, API_PREFIX).filter(
      (route) => route.method === "GET",
    );

    for (const route of readable) {
      const url = route.path
        .replace(":id", secretId)
        .replace(":key", "platform.displayName")
        .replace(":token", "irrelevant");
      const response = capture(
        `GET ${route.path}`,
        await call(ctx.app, { method: "GET", url, cookie: owner.cookie }),
      );
      expect(response.raw, `${route.path} leaked the sentinel`).not.toContain(SENTINEL);
    }

    // Forced error responses on the secret routes.
    const notFound = capture(
      "GET /api/secrets/<missing>",
      await call(ctx.app, {
        method: "GET",
        url: "/api/secrets/00000000-0000-7000-8000-0000000000ff",
        cookie: owner.cookie,
      }),
    );
    expect(notFound.statusCode).toBe(404);
    expect(notFound.raw).not.toContain(SENTINEL);

    const badInput = capture(
      "POST /api/secrets (invalid)",
      await call(ctx.app, {
        method: "POST",
        url: "/api/secrets",
        payload: { name: "INVALID NAME WITH SPACES", value: SENTINEL },
        cookie: owner.cookie,
        csrfToken: owner.csrfToken,
      }),
    );
    expect(badInput.statusCode).toBe(400);
    // The validation error names FIELDS, never values (FR-030/FR-042).
    expect(badInput.raw).not.toContain(SENTINEL);
    expect(badInput.json()).toEqual({ error: "VALIDATION_FAILED" });

    // The generated OpenAPI document.
    const document = buildOpenApiDocument(ctx.app);
    const serialised = JSON.stringify(document);
    expect(serialised).not.toContain(SENTINEL);
    expect(findForbiddenOperations(document)).toEqual([]);
  }, 90_000);

  // ── 5.9 ────────────────────────────────────────────────────────────────────
  it("5.9 a single tampered byte fails authentication loudly, returns nothing, and is audited", async () => {
    const tamperedName = `${secretName}-tampered`;
    const store = ctx.app.get<SecretStore>(TOKENS.SecretStore);
    await store.put(tamperedName, SENTINEL, { description: "to be corrupted" });

    const row = await ctx.prisma.secret.findUnique({ where: { name: tamperedName } });
    const corrupted = Buffer.from(row!.ciphertext);
    corrupted[0] = corrupted[0]! ^ 0x01;
    await ctx.prisma.secret.update({
      where: { name: tamperedName },
      data: { ciphertext: new Uint8Array(corrupted) },
    });

    await expect(store.get(tamperedName)).rejects.toMatchObject({ code: "SECRET_INTEGRITY" });

    const failure = await ctx.prisma.auditLog.findFirst({
      where: { action: "secret.read", outcome: "FAILURE", targetId: row!.id },
      orderBy: { createdAt: "desc" },
    });
    expect(failure, "the integrity failure was not audited").not.toBeNull();
    expect(JSON.stringify(failure)).not.toContain(SENTINEL);

    // The same treatment for a tampered AUTH TAG.
    const tagRow = await ctx.prisma.secret.findUnique({ where: { name: tamperedName } });
    const tag = Buffer.from(tagRow!.authTag);
    tag[0] = tag[0]! ^ 0xff;
    await ctx.prisma.secret.update({
      where: { name: tamperedName },
      data: { authTag: new Uint8Array(tag) },
    });
    await expect(store.get(tamperedName)).rejects.toMatchObject({ code: "SECRET_INTEGRITY" });
  }, 60_000);

  it("a ciphertext copied from another row fails authentication — the AAD binds it (§8.2)", async () => {
    const store = ctx.app.get<SecretStore>(TOKENS.SecretStore);
    const victimName = `${secretName}-swap-victim`;
    const donorName = `${secretName}-swap-donor`;
    await store.put(victimName, "victim-value", {});
    await store.put(donorName, SENTINEL, {});

    const donor = await ctx.prisma.secret.findUnique({ where: { name: donorName } });
    await ctx.prisma.secret.update({
      where: { name: victimName },
      data: {
        ciphertext: donor!.ciphertext,
        iv: donor!.iv,
        authTag: donor!.authTag,
        wrappedDek: donor!.wrappedDek,
        dekIv: donor!.dekIv,
        dekAuthTag: donor!.dekAuthTag,
      },
    });

    // The wrapped DEK's AAD is the DONOR's row id, so unwrapping under the victim's id fails.
    await expect(store.get(victimName)).rejects.toMatchObject({ code: "SECRET_INTEGRITY" });
  }, 60_000);

  // ── 5.10 ───────────────────────────────────────────────────────────────────
  it("5.10 rotation replaces the value under the same reference, and the old ciphertext is gone", async () => {
    const before = await ctx.prisma.secret.findUnique({ where: { name: secretName } });

    const response = capture(
      "POST /api/secrets/:id/rotate",
      await call(ctx.app, {
        method: "POST",
        url: `/api/secrets/${secretId}/rotate`,
        payload: { value: ROTATED_SENTINEL },
        cookie: owner.cookie,
        csrfToken: owner.csrfToken,
      }),
    );

    expect(response.statusCode).toBe(200);
    expect(response.raw).not.toContain(ROTATED_SENTINEL);
    expect(response.raw).not.toContain(SENTINEL);

    const after = await ctx.prisma.secret.findUnique({ where: { name: secretName } });
    expect(after!.name).toBe(before!.name);
    expect(after!.id).toBe(before!.id);
    expect(after!.version).toBe(before!.version + 1);
    expect(after!.rotatedAt).not.toBeNull();
    // The previous ciphertext is retained NOWHERE — that is what makes it unretrievable.
    expect(Buffer.from(after!.ciphertext).equals(Buffer.from(before!.ciphertext))).toBe(false);

    const store = ctx.app.get<SecretStore>(TOKENS.SecretStore);
    const value = await store.get(secretName);
    expect(value.use((plaintext) => plaintext)).toBe(ROTATED_SENTINEL);

    const rotationAudit = await ctx.prisma.auditLog.findFirst({
      where: { action: "secret.rotate", targetId: secretId },
      orderBy: { createdAt: "desc" },
    });
    expect(rotationAudit).not.toBeNull();
    expect(JSON.stringify(rotationAudit)).not.toContain(ROTATED_SENTINEL);
  }, 60_000);

  // ── 5.11 ───────────────────────────────────────────────────────────────────
  it("5.11 every secret operation is audited by NAME and operation, never by value", async () => {
    const records = await ctx.prisma.auditLog.findMany({
      where: { action: { in: ["secret.create", "secret.read", "secret.rotate", "secret.delete"] } },
      orderBy: { createdAt: "asc" },
    });

    const actions = new Set(records.map((row) => row.action));
    expect(actions.has("secret.create")).toBe(true);
    expect(actions.has("secret.read")).toBe(true);
    expect(actions.has("secret.rotate")).toBe(true);

    const serialised = JSON.stringify(records);
    expect(serialised).not.toContain(SENTINEL);
    expect(serialised).not.toContain(ROTATED_SENTINEL);
    // …but the NAME is there, so the record is actually useful.
    expect(serialised).toContain(secretName);

    // Delete completes the set, and refuses while a reference exists.
    const mfaReference = secretNameFor.totp("00000000-0000-7000-8000-000000000123");
    expect(mfaReference).toContain("mfa:totp:");

    const deleted = await call(ctx.app, {
      method: "DELETE",
      url: `/api/secrets/${secretId}`,
      cookie: owner.cookie,
      csrfToken: owner.csrfToken,
    });
    expect(deleted.statusCode).toBe(200);
    const deleteAudit = await ctx.prisma.auditLog.findFirst({
      where: { action: "secret.delete", targetId: secretId },
    });
    expect(deleteAudit).not.toBeNull();
  }, 60_000);

  // ── 5.6 ────────────────────────────────────────────────────────────────────
  it("5.6 every response body and header captured in this run is sentinel-free", () => {
    expect(captured.length).toBeGreaterThan(10);
    const offenders = captured.filter(
      (entry) =>
        entry.body.includes(SENTINEL) ||
        entry.body.includes(ROTATED_SENTINEL) ||
        entry.headers.includes(SENTINEL) ||
        entry.headers.includes(ROTATED_SENTINEL),
    );
    expect(offenders.map((o) => o.url)).toEqual([]);
  });

  // ── 5.8 ────────────────────────────────────────────────────────────────────
  it("5.8 the sentinel appears in no log line and in no usage record", async () => {
    const usage = await ctx.prisma.usageRecord.findMany();
    expect(JSON.stringify(usage)).not.toContain(SENTINEL);
    expect(JSON.stringify(usage)).not.toContain(ROTATED_SENTINEL);

    const lines: string[] = [];
    const destination = new Writable({
      write(chunk: Buffer, _encoding, done) {
        lines.push(chunk.toString("utf8"));
        done();
      },
    });

    const logged = await createTestApp({ reset: false, logger: { level: "trace", destination } });
    try {
      const principal = await loginAsOwner(logged.app);
      const name = `et5-logged-${Date.now()}`;

      await call(logged.app, {
        method: "POST",
        url: "/api/secrets",
        payload: { name, value: SENTINEL, description: "logged run" },
        cookie: principal.cookie,
        csrfToken: principal.csrfToken,
      });
      await call(logged.app, { method: "GET", url: "/api/secrets", cookie: principal.cookie });

      const store = logged.app.get<SecretStore>(TOKENS.SecretStore);
      const value = await store.get(name);
      // Even a deliberate attempt to log the wrapper emits the marker, not the value (§8.4).
      const logger = logged.app.get<{ log(message: unknown): void }>("SUNIL_CONFIG", {
        strict: false,
      });
      expect(logger).toBeDefined();
      lines.push(JSON.stringify({ attempted: value }));

      const output = lines.join("");
      expect(output).not.toContain(SENTINEL);
      expect(output).toContain("[REDACTED]");
    } finally {
      await logged.close();
    }
  }, 90_000);
});
