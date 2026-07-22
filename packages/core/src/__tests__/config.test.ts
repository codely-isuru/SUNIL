import { describe, expect, it } from "vitest";
import {
  CoreEnvSchema,
  ENV_VAR_NAMES,
  SECRET_ENV_VAR_NAMES,
  assertProductionCookiePolicy,
  parseEnv,
} from "../config.js";
import { ConfigurationError } from "../errors.js";

const VALID_KEY = Buffer.alloc(32, 7).toString("base64");

const validEnv = {
  DATABASE_URL: "postgresql://user:pass@localhost:5432/db",
  REDIS_URL: "redis://localhost:6379",
  SUNIL_MASTER_KEY: VALID_KEY,
};

describe("configuration inventory (§16 / FR-004)", () => {
  it("lists every variable exactly once", () => {
    expect(new Set(ENV_VAR_NAMES).size).toBe(ENV_VAR_NAMES.length);
  });

  it("marks every credential-shaped variable as secret", () => {
    for (const name of SECRET_ENV_VAR_NAMES) {
      expect(ENV_VAR_NAMES).toContain(name);
    }
    expect(SECRET_ENV_VAR_NAMES).toContain("SUNIL_MASTER_KEY");
    expect(SECRET_ENV_VAR_NAMES).toContain("SUNIL_OWNER_INITIAL_PASSWORD");
  });

  it("applies the documented non-secret defaults", () => {
    const env = parseEnv(CoreEnvSchema, validEnv as NodeJS.ProcessEnv);
    expect(env.SUNIL_SESSION_IDLE_HOURS).toBe(8);
    expect(env.SUNIL_SESSION_ABSOLUTE_HOURS).toBe(24);
    expect(env.SUNIL_AUTH_MAX_FAILURES).toBe(5);
    expect(env.SUNIL_RATE_AUTH_IP_PER_MIN).toBe(20);
    expect(env.SUNIL_TIMEZONE).toBe("Australia/Hobart");
    expect(env.SUNIL_COOKIE_SECURE).toBe(true);
  });

  it("fails fast naming the offending variable", () => {
    try {
      parseEnv(CoreEnvSchema, {} as NodeJS.ProcessEnv);
      throw new Error("expected parseEnv to throw");
    } catch (error) {
      expect(error).toBeInstanceOf(ConfigurationError);
      const configError = error as ConfigurationError;
      expect(configError.variables).toContain("DATABASE_URL");
      expect(configError.variables).toContain("SUNIL_MASTER_KEY");
    }
  });

  it("never prints the value of a secret variable in the failure message", () => {
    const canary = "CANARY-MASTER-KEY-VALUE-DO-NOT-PRINT";
    try {
      parseEnv(CoreEnvSchema, {
        ...validEnv,
        SUNIL_MASTER_KEY: canary,
      } as NodeJS.ProcessEnv);
      throw new Error("expected parseEnv to throw");
    } catch (error) {
      expect(error).toBeInstanceOf(ConfigurationError);
      expect((error as Error).message).not.toContain(canary);
      expect((error as Error).message).toContain("SUNIL_MASTER_KEY");
    }
  });

  it("rejects a master key that is not exactly 32 bytes (FR-041)", () => {
    const short = Buffer.alloc(16, 1).toString("base64");
    expect(
      CoreEnvSchema.safeParse({ ...validEnv, SUNIL_MASTER_KEY: short }).success,
    ).toBe(false);
  });
});

describe("permissive-by-omission is impossible (FR-023)", () => {
  it("hard-fails a production profile with cookies explicitly insecure", () => {
    expect(() => assertProductionCookiePolicy("production", false)).toThrow(ConfigurationError);
  });

  it("allows insecure cookies only outside production", () => {
    expect(() => assertProductionCookiePolicy("development", false)).not.toThrow();
    expect(() => assertProductionCookiePolicy("production", true)).not.toThrow();
  });
});
