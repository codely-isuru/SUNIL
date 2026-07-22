/**
 * ⚠ UNVERIFIED AGAINST LIVE ENDPOINTS ⚠
 *
 * The §10.5 labelling mechanism (Gate 1 / FR-065 / NFR-019), implemented as a mechanism
 * rather than a comment.
 *
 * No LLM provider API key exists in this environment, so every adapter in this package is
 * verified against MOCKED transports only. Three things make that statement structural
 * instead of aspirational:
 *
 *  1. `Phase1VerificationStatus` is `Exclude<ProviderVerification, "LIVE_VERIFIED">`. Any
 *     Phase 1 code path that tries to persist `LIVE_VERIFIED` through this module is a TYPE
 *     ERROR, and `assertPhase1VerificationStatus` refuses it at runtime as well.
 *  2. Every adapter exports `verification = 'mock-verified'` (a literal type — it cannot
 *     widen) and carries the banner comment above.
 *  3. `describeVerification()` produces the exact wording the portal renders and the phase
 *     report quotes, from data, so the label cannot drift between code, UI and docs.
 */
import {
  InvariantViolationError,
  PHASE1_VERIFICATION,
  PROVIDER_SLUGS,
  type ProviderSlug,
  type ProviderVerification,
} from "@sunil/core";

/** The literal every adapter reports (§10.1). */
export type Phase1Verification = typeof PHASE1_VERIFICATION;

/** The Gate 1 wording. One constant; portal, API and phase report all read it. */
export const UNVERIFIED_LABEL = "unverified against live endpoints" as const;

/** Displayed for a provider with no credential configured (FR-065). */
export const NOT_CONFIGURED_LABEL = "not configured" as const;

/**
 * The only two statuses Phase 1 may ever produce. `LIVE_VERIFIED` exists in the Prisma enum
 * for Phase 2's live smoke test and is deliberately unreachable from here.
 */
export type Phase1VerificationStatus = Exclude<ProviderVerification, "LIVE_VERIFIED">;

export const PHASE1_VERIFICATION_STATUSES: readonly Phase1VerificationStatus[] = [
  "UNCONFIGURED",
  "MOCK_VERIFIED",
];

/** What live verification will require. Quoted by `LOCAL_SETUP.md` and the phase report. */
export const LIVE_VERIFICATION_REQUIREMENTS: readonly string[] = [
  "A real provider credential stored through the SecretStore (ANTHROPIC_API_KEY / OPENAI_API_KEY are documented names only and are unset in this environment; Ollama needs a reachable OLLAMA_BASE_URL).",
  "A live smoke-test script that runs each adapter against the real endpoint with the production transport.",
  "A diff of the recorded fixtures in packages/llm/src/testing/fixtures against the live responses, to detect contract drift (auth header shape, SSE framing, token-count field names, error bodies).",
  "A Phase 2 decision to write LIVE_VERIFIED, which no Phase 1 code path can perform.",
];

export interface VerificationDisclosure {
  readonly slug: ProviderSlug;
  /** Always `mock-verified` in Phase 1. */
  readonly verification: Phase1Verification;
  readonly status: Phase1VerificationStatus;
  /** Exactly what the portal renders. Never "connected" or "healthy". */
  readonly label: string;
  /** Longer sentence for the providers page and the phase report. */
  readonly detail: string;
  readonly liveVerificationRequirements: readonly string[];
}

/**
 * The status a Phase 1 provider row may carry. Note the return type: there is no argument
 * value that yields `LIVE_VERIFIED`.
 */
export function verificationStatusFor(hasCredential: boolean): Phase1VerificationStatus {
  return hasCredential ? "MOCK_VERIFIED" : "UNCONFIGURED";
}

export function isPhase1VerificationStatus(value: string): value is Phase1VerificationStatus {
  return (PHASE1_VERIFICATION_STATUSES as readonly string[]).includes(value);
}

/**
 * Runtime backstop for the type-level fence: throws if anything tries to persist
 * `LIVE_VERIFIED` (or an unknown status) in Phase 1.
 */
export function assertPhase1VerificationStatus(
  value: string,
): asserts value is Phase1VerificationStatus {
  if (!isPhase1VerificationStatus(value)) {
    throw new InvariantViolationError(
      `Phase 1 may not record provider verification status '${value}' — adapters are ${UNVERIFIED_LABEL} (FR-065)`,
    );
  }
}

/** Build the disclosure the portal renders and the phase report quotes. */
export function describeVerification(
  slug: ProviderSlug,
  hasCredential: boolean,
): VerificationDisclosure {
  const status = verificationStatusFor(hasCredential);
  const label = status === "UNCONFIGURED" ? `${NOT_CONFIGURED_LABEL} / ${UNVERIFIED_LABEL}` : UNVERIFIED_LABEL;
  return {
    slug,
    verification: PHASE1_VERIFICATION,
    status,
    label,
    detail:
      status === "UNCONFIGURED"
        ? `The ${slug} adapter has no credential configured and is ${UNVERIFIED_LABEL}. It has been exercised against mocked transports only.`
        : `The ${slug} adapter is mock-verified and ${UNVERIFIED_LABEL}. It has been exercised against mocked transports only.`,
    liveVerificationRequirements: LIVE_VERIFICATION_REQUIREMENTS,
  };
}

/** Disclosure for all three Phase 1 providers, e.g. for a settings page with no rows yet. */
export function describeAllVerifications(
  hasCredential: (slug: ProviderSlug) => boolean = () => false,
): readonly VerificationDisclosure[] {
  return PROVIDER_SLUGS.map((slug) => describeVerification(slug, hasCredential(slug)));
}
