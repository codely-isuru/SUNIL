import { describe, expect, it } from "vitest";
import { PROVIDER_ERROR_CLASSES, PHASE1_VERIFICATION, ProviderError } from "@sunil/core";
import { PACKAGE_NAME, VERIFICATION } from "../index.js";

describe("@sunil/llm skeleton", () => {
  it("is wired into the workspace and reaches @sunil/core", () => {
    expect(PACKAGE_NAME).toBe("@sunil/llm");
  });

  it("reports mock-verified only — Phase 1 is unverified against live endpoints (FR-065)", () => {
    expect(VERIFICATION).toBe(PHASE1_VERIFICATION);
    expect(VERIFICATION).toBe("mock-verified");
  });

  it("has the six-class provider error taxonomy available to adapters (§10.3)", () => {
    expect([...PROVIDER_ERROR_CLASSES].sort()).toEqual([
      "auth",
      "connectivity",
      "contract",
      "rate_limit",
      "server",
      "timeout",
    ]);
    const error = new ProviderError({
      provider: "anthropic",
      errorClass: "rate_limit",
      retryable: true,
      message: "slow down",
      status: 429,
    });
    expect(error.retryable).toBe(true);
    expect(error.httpStatus).toBe(502);
  });
});
