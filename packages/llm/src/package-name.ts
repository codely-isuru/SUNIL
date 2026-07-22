/** Package identity, kept in its own module so `index.ts` stays a pure re-export barrel. */
import { PHASE1_VERIFICATION } from "@sunil/core";

export const PACKAGE_NAME = "@sunil/llm" as const;

/**
 * Phase 1 adapters are mock-verified only — unverified against live endpoints (FR-065).
 * Re-exported here so the portal and the phase report read one constant, not three.
 */
export const VERIFICATION = PHASE1_VERIFICATION;
