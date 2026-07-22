/**
 * §10.5 / FR-065 — the "unverified against live endpoints" labelling MECHANISM.
 *
 * Gate 1 requires this to be visible and structural rather than a comment, so these tests
 * assert the mechanism, not the prose.
 */
import { describe, expect, it } from "vitest";
import { InvariantViolationError, PHASE1_VERIFICATION, PROVIDER_SLUGS } from "@sunil/core";
import { AnthropicAdapter } from "../adapters/anthropic.js";
import { OllamaAdapter } from "../adapters/ollama.js";
import { OpenAiAdapter } from "../adapters/openai.js";
import { CONTRACT_NOTES, contractNotesFor } from "../contract-notes.js";
import { MockTransport } from "../testing/mock-transport.js";
import {
  LIVE_VERIFICATION_REQUIREMENTS,
  PHASE1_VERIFICATION_STATUSES,
  UNVERIFIED_LABEL,
  assertPhase1VerificationStatus,
  describeAllVerifications,
  describeVerification,
  isPhase1VerificationStatus,
  verificationStatusFor,
} from "../verification.js";
import { FakeSecretStore } from "./support.js";

const transport = new MockTransport([]).fetch;
const secrets = new FakeSecretStore({ "llm:test": "sentinel" });

describe("every adapter labels itself mock-verified (§10.5 code layer)", () => {
  const adapters = [
    new AnthropicAdapter({ transport, secrets, credentialName: "llm:test" }),
    new OpenAiAdapter({ transport, secrets, credentialName: "llm:test" }),
    new OllamaAdapter({ transport }),
  ];

  it.each(adapters.map((adapter) => [adapter.slug, adapter] as const))(
    "%s reports verification 'mock-verified'",
    (_slug, adapter) => {
      expect(adapter.verification).toBe("mock-verified");
      expect(adapter.verification).toBe(PHASE1_VERIFICATION);
    },
  );

  it("covers all three Phase 1 provider slugs and nothing else", () => {
    expect(adapters.map((adapter) => adapter.slug).sort()).toEqual([...PROVIDER_SLUGS].sort());
  });
});

describe("the data layer cannot reach LIVE_VERIFIED in Phase 1", () => {
  it("offers exactly two statuses", () => {
    expect(PHASE1_VERIFICATION_STATUSES).toEqual(["UNCONFIGURED", "MOCK_VERIFIED"]);
  });

  it("maps credential presence onto a status, with no input producing LIVE_VERIFIED", () => {
    expect(verificationStatusFor(false)).toBe("UNCONFIGURED");
    expect(verificationStatusFor(true)).toBe("MOCK_VERIFIED");
  });

  it("refuses LIVE_VERIFIED at runtime as well as at the type level", () => {
    expect(isPhase1VerificationStatus("LIVE_VERIFIED")).toBe(false);
    expect(() => assertPhase1VerificationStatus("LIVE_VERIFIED")).toThrow(InvariantViolationError);
    expect(() => assertPhase1VerificationStatus("MOCK_VERIFIED")).not.toThrow();
  });
});

describe("the portal wording comes from one place (Gate 1 wording)", () => {
  it("renders 'not configured / unverified against live endpoints' with no credential", () => {
    const disclosure = describeVerification("anthropic", false);
    expect(disclosure.label).toBe(`not configured / ${UNVERIFIED_LABEL}`);
    expect(disclosure.status).toBe("UNCONFIGURED");
    expect(disclosure.verification).toBe("mock-verified");
  });

  it("still says unverified once a credential exists — never 'connected' or 'healthy'", () => {
    const disclosure = describeVerification("openai", true);
    expect(disclosure.label).toBe(UNVERIFIED_LABEL);
    expect(disclosure.detail).toContain(UNVERIFIED_LABEL);
    expect(disclosure.label.toLowerCase()).not.toContain("connected");
    expect(disclosure.label.toLowerCase()).not.toContain("healthy");
  });

  it("lists what live verification will require", () => {
    expect(LIVE_VERIFICATION_REQUIREMENTS.length).toBeGreaterThanOrEqual(3);
    expect(describeVerification("ollama", false).liveVerificationRequirements).toBe(
      LIVE_VERIFICATION_REQUIREMENTS,
    );
  });

  it("describes all three providers for a page with no rows yet", () => {
    const all = describeAllVerifications();
    expect(all.map((entry) => entry.slug)).toEqual([...PROVIDER_SLUGS]);
    expect(all.every((entry) => entry.label.includes(UNVERIFIED_LABEL))).toBe(true);
  });
});

describe("recorded contract ambiguities (R-01: record, do not guess silently)", () => {
  it("records at least one ambiguity per provider", () => {
    for (const slug of PROVIDER_SLUGS) {
      expect(contractNotesFor(slug).length).toBeGreaterThan(0);
    }
  });

  it("gives every note a decision, not just a question", () => {
    for (const note of CONTRACT_NOTES) {
      expect(note.decision.length).toBeGreaterThan(10);
      expect(note.ambiguity.length).toBeGreaterThan(10);
    }
  });
});
