import { describe, expect, it } from "vitest";
import { ConfigurationError, PERMISSIONS, PermissionKeySchema } from "@sunil/core";
import { prepareApiBootstrap } from "../main.js";

const validEnv = {
  DATABASE_URL: "postgresql://localhost:5432/sunil",
  REDIS_URL: "redis://localhost:6379",
  SUNIL_MASTER_KEY: Buffer.alloc(32, 3).toString("base64"),
} as NodeJS.ProcessEnv;

describe("apps/api consumes @sunil/core (FR-002)", () => {
  it("compiles against the single shared permission catalogue", () => {
    expect(PERMISSIONS).toHaveLength(21);
    expect(PermissionKeySchema.safeParse("secret:rotate").success).toBe(true);
    expect(PermissionKeySchema.safeParse("secret:value").success).toBe(false);
  });
});

describe("apps/api startup configuration (FR-004)", () => {
  it("resolves the API port from validated configuration", () => {
    expect(prepareApiBootstrap(validEnv).port).toBe(3001);
  });

  it("refuses to start when a required variable is missing, naming it", () => {
    try {
      prepareApiBootstrap({} as NodeJS.ProcessEnv);
      throw new Error("expected a ConfigurationError");
    } catch (error) {
      expect(error).toBeInstanceOf(ConfigurationError);
      expect((error as ConfigurationError).variables).toContain("DATABASE_URL");
    }
  });

  it("hard-fails a production profile with cookies explicitly insecure (FR-023)", () => {
    expect(() =>
      prepareApiBootstrap({
        ...validEnv,
        NODE_ENV: "production",
        SUNIL_COOKIE_SECURE: "false",
      } as NodeJS.ProcessEnv),
    ).toThrow(ConfigurationError);
  });
});
