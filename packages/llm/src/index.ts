/**
 * `@sunil/llm` — the LLM provider abstraction (§10, ADR-008).
 *
 * ⚠ EVERY ADAPTER IN THIS PACKAGE IS UNVERIFIED AGAINST LIVE ENDPOINTS ⚠
 * No LLM provider API key exists in this environment (Gate 1). Adapters are verified against
 * mocked transports ONLY and report `verification: 'mock-verified'`. See `./verification.ts`
 * for the mechanism and `./contract-notes.ts` for the ambiguities that a live endpoint would
 * settle.
 *
 * Scope fence (FR-066): no routing, no failover, no budget caps. The caller names the
 * provider slug explicitly as configuration. Routing is Phase 2.
 *
 * NOTE: `./testing/*` (MockTransport and fixtures) is deliberately NOT exported. The package
 * exposes a single `"."` entry point, so no production code path can reach a mock (FR-065).
 */
export { PACKAGE_NAME, VERIFICATION } from "./package-name.js";

export type { Transport } from "./transport.js";
export { REAL_FETCH_TRANSPORT, deadlineSignal } from "./transport.js";

export {
  LIVE_VERIFICATION_REQUIREMENTS,
  NOT_CONFIGURED_LABEL,
  PHASE1_VERIFICATION_STATUSES,
  UNVERIFIED_LABEL,
  assertPhase1VerificationStatus,
  describeAllVerifications,
  describeVerification,
  isPhase1VerificationStatus,
  verificationStatusFor,
} from "./verification.js";
export type {
  Phase1Verification,
  Phase1VerificationStatus,
  VerificationDisclosure,
} from "./verification.js";

export { CONTRACT_NOTES, contractNotesFor } from "./contract-notes.js";
export type { ContractNote } from "./contract-notes.js";

export { assertCapability, isLLMAdapter } from "./provider.js";
export type {
  CallOptions,
  Capability,
  CompletionDelta,
  EmbedRequest,
  EmbedResult,
  LLMAdapter,
  LLMProvider,
  StreamOutcome,
  TokenUsage,
} from "./provider.js";

export { classifyStatus, toProviderError, toValidationError } from "./errors.js";
export type { Classification } from "./errors.js";

export { NOOP_LLM_LOGGER } from "./logging.js";
export type { LlmLogger } from "./logging.js";

export {
  MODEL_RATES_SETTING_KEY,
  StaticModelRates,
  SystemSettingModelRates,
} from "./rates.js";
export type { ModelRatesSource } from "./rates.js";

export { PrismaUsageSink, UsageRecorder, withUsageRecording } from "./usage.js";
export type { UsageCallMeta, UsageRow, UsageSink } from "./usage.js";

export { ANTHROPIC_CAPABILITIES, AnthropicAdapter } from "./adapters/anthropic.js";
export type { AnthropicAdapterOptions } from "./adapters/anthropic.js";
export { OPENAI_CAPABILITIES, OpenAiAdapter } from "./adapters/openai.js";
export type { OpenAiAdapterOptions } from "./adapters/openai.js";
export { DEFAULT_OLLAMA_BASE_URL, OLLAMA_CAPABILITIES, OllamaAdapter } from "./adapters/ollama.js";
export type { OllamaAdapterOptions } from "./adapters/ollama.js";

export { createProvider, createProviderWithTransport } from "./factory.js";
export type { ProviderConfig, ProviderDeps } from "./factory.js";
