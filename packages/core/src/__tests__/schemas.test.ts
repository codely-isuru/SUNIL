import { inspect } from "node:util";
import { describe, expect, it } from "vitest";
import { EmailSchema, PASSWORD_MIN_LENGTH, PasswordSchema } from "../schemas/common.js";
import { loadAgentConfig } from "../schemas/agent.js";
import { SecretValue, isSecretValue } from "../schemas/secrets.js";
import { estimateCostUsd } from "../schemas/llm.js";
import { MfaVerifyRequestSchema } from "../schemas/identity.js";

describe("email normalisation (§5.1)", () => {
  it("trims and lowercases so the DB unique index is effectively case-insensitive", () => {
    expect(EmailSchema.parse("  Owner@Example.TEST  ")).toBe("owner@example.test");
  });

  it("rejects a non-email", () => {
    expect(EmailSchema.safeParse("not-an-email").success).toBe(false);
  });
});

describe("password policy (FR-030)", () => {
  it("enforces the documented minimum length", () => {
    expect(PasswordSchema.safeParse("short").success).toBe(false);
    expect(PasswordSchema.safeParse("a".repeat(PASSWORD_MIN_LENGTH)).success).toBe(false);
    expect(PasswordSchema.safeParse("correct horse battery").success).toBe(true);
  });

  it("rejects listed weak passwords", () => {
    expect(PasswordSchema.safeParse("password123").success).toBe(false);
  });

  it("never echoes the submitted value in an error message", () => {
    const submitted = "zzz-canary-value-zzz";
    const result = PasswordSchema.safeParse(submitted.slice(0, 4));
    expect(result.success).toBe(false);
    if (result.success) return;
    expect(JSON.stringify(result.error.issues)).not.toContain(submitted.slice(0, 4));
  });
});

describe("agent config (§11.1 / FR-070)", () => {
  const valid = {
    id: "018f4a9e-0000-7000-8000-000000000001",
    slug: "email-triage",
    name: "Email Triage",
    role: "Sorts the inbox",
    systemInstructions: "You are a triage agent.",
    maxDurationSeconds: 120,
    heartbeatIntervalSeconds: 30,
    staleThresholdSeconds: 90,
  };

  it("loads a valid configuration", () => {
    const result = loadAgentConfig(valid);
    expect(result.ok).toBe(true);
    if (!result.ok) return;
    expect(result.config.toolAllowlist).toEqual([]);
  });

  it("refuses to load an agent with a non-empty tool allowlist and names the field", () => {
    const result = loadAgentConfig({ ...valid, toolAllowlist: ["shell"] });
    expect(result.ok).toBe(false);
    if (result.ok) return;
    expect(result.issues.join("\n")).toMatch(/toolAllowlist/);
    expect(result.issues.join("\n")).toMatch(/Phase 2/);
  });

  it("returns nothing partially configured on failure", () => {
    const result = loadAgentConfig({ ...valid, maxDurationSeconds: 0 });
    expect(result.ok).toBe(false);
    expect(result).not.toHaveProperty("config");
  });
});

describe("SecretValue (§8.4)", () => {
  const value = new SecretValue("llm:anthropic:api-key", "canary-plaintext-0123456789");

  it("yields the plaintext only inside use()", () => {
    expect(value.use((p) => p)).toBe("canary-plaintext-0123456789");
  });

  it("cannot be serialised into a response body", () => {
    expect(JSON.stringify({ secret: value })).not.toContain("canary-plaintext");
    expect(JSON.stringify({ secret: value })).toContain("[REDACTED]");
  });

  it("cannot be interpolated into a log line", () => {
    expect(`${value}`).toBe("[REDACTED]");
    expect(String(value)).toBe("[REDACTED]");
  });

  it("cannot leak through util.inspect / console.log", () => {
    expect(inspect(value)).not.toContain("canary-plaintext");
    expect(inspect({ secret: value })).not.toContain("canary-plaintext");
  });

  it("is detectable by the serialisation interceptor", () => {
    expect(isSecretValue(value)).toBe(true);
    expect(isSecretValue("plain string")).toBe(false);
  });
});

describe("cost estimation reads rates from configuration (FR-064)", () => {
  const rates = {
    "claude-x": { inputPerMillionUsd: 3, outputPerMillionUsd: 15 },
  };

  it("computes from the supplied rate table", () => {
    expect(estimateCostUsd(rates, "claude-x", 1_000_000, 1_000_000)).toBe(18);
  });

  it("returns zero for an unknown model rather than guessing", () => {
    expect(estimateCostUsd(rates, "unknown-model", 1_000_000, 0)).toBe(0);
  });
});

describe("MFA verify accepts exactly one credential form (§6.4)", () => {
  it("accepts a TOTP code", () => {
    expect(MfaVerifyRequestSchema.safeParse({ code: "123456" }).success).toBe(true);
  });

  it("accepts a recovery code", () => {
    expect(MfaVerifyRequestSchema.safeParse({ recoveryCode: "abcdefg234" }).success).toBe(true);
  });

  it("rejects both or neither", () => {
    expect(
      MfaVerifyRequestSchema.safeParse({ code: "123456", recoveryCode: "ABCDEFG234" }).success,
    ).toBe(false);
    expect(MfaVerifyRequestSchema.safeParse({}).success).toBe(false);
  });
});
