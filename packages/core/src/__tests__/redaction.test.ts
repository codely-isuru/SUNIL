import { describe, expect, it } from "vitest";
import { REDACTED, isRedactedFieldName, redact, scrubString } from "../redaction.js";

describe("redaction (§9.5 / NFR-011)", () => {
  it("redacts deny-listed field names case-insensitively at any depth", () => {
    const input = {
      user: {
        email: "owner@example.test",
        PassWord: "hunter2-hunter2",
        nested: { apiKey: "abcd", recoveryCodes: ["A", "B"] },
      },
    };
    const out = redact(input) as Record<string, Record<string, unknown>>;
    expect(out["user"]?.["email"]).toBe("owner@example.test");
    expect(out["user"]?.["PassWord"]).toBe(REDACTED);
    const nested = out["user"]?.["nested"] as Record<string, unknown>;
    expect(nested["apiKey"]).toBe(REDACTED);
    expect(nested["recoveryCodes"]).toBe(REDACTED);
  });

  it("scrubs credential-shaped values wherever they appear", () => {
    expect(scrubString("using sk-ant-0123456789abcdefghij now")).toContain(REDACTED);
    expect(scrubString("using sk-ant-0123456789abcdefghij now")).not.toContain("0123456789");
    expect(scrubString("ghp_0123456789abcdefghij0123")).toBe(REDACTED);
    expect(
      scrubString("postgresql://sunil:supersecretvalue@postgres:5432/sunil"),
    ).not.toContain("supersecretvalue");
    expect(scrubString("-----BEGIN PRIVATE KEY-----\nabc\n-----END PRIVATE KEY-----")).toBe(
      REDACTED,
    );
  });

  it("leaves ordinary text intact", () => {
    expect(scrubString("Agent completed task in 1200ms")).toBe(
      "Agent completed task in 1200ms",
    );
  });

  it("survives cycles and over-deep structures", () => {
    const cyclic: Record<string, unknown> = { name: "a" };
    cyclic["self"] = cyclic;
    expect(() => redact(cyclic)).not.toThrow();
    expect(JSON.stringify(redact(cyclic))).toContain("CIRCULAR");
  });

  it("stringifies bigints and dates rather than throwing on serialise", () => {
    const out = redact({ seq: 10n, when: new Date("2026-01-01T00:00:00.000Z") }) as Record<
      string,
      unknown
    >;
    expect(out["seq"]).toBe("10");
    expect(out["when"]).toBe("2026-01-01T00:00:00.000Z");
  });

  it("knows its own deny-list", () => {
    expect(isRedactedFieldName("Authorization")).toBe(true);
    expect(isRedactedFieldName("displayName")).toBe(false);
  });
});
