/**
 * LLM request/response contracts (§10.1).
 *
 * Adapters in `packages/llm` validate against these in BOTH directions (FR-060/NFR-003).
 * Phase 1 has no routing, no failover and no budget caps in the provider layer (FR-066) —
 * the caller names the provider slug explicitly as configuration.
 */
import { z } from "../zod.js";
import { PROVIDER_ERROR_CLASSES } from "../errors.js";

export const PROVIDER_SLUGS = ["anthropic", "openai", "ollama"] as const;
export const ProviderSlugSchema = z.enum(PROVIDER_SLUGS);

export const PROVIDER_VERIFICATION_STATUSES = [
  "UNCONFIGURED",
  "MOCK_VERIFIED",
  "LIVE_VERIFIED",
] as const;
export const ProviderVerificationSchema = z.enum(PROVIDER_VERIFICATION_STATUSES);

/**
 * Phase 1 adapters may only ever report this. `LIVE_VERIFIED` exists for Phase 2's live
 * smoke test; no Phase 1 code path writes it (FR-065, §10.5).
 */
export const PHASE1_VERIFICATION = "mock-verified" as const;

export const ChatRoleSchema = z.enum(["system", "user", "assistant"]);

export type ChatRole = z.infer<typeof ChatRoleSchema>;

export const ChatMessageSchema = z.object({
  role: ChatRoleSchema,
  content: z.string(),
});

export type ChatMessage = z.infer<typeof ChatMessageSchema>;

export const CompletionRequestSchema = z.object({
  model: z.string().min(1).max(200),
  messages: z.array(ChatMessageSchema).min(1),
  maxTokens: z.number().int().positive().max(200_000).default(1024),
  temperature: z.number().min(0).max(2).optional(),
  stopSequences: z.array(z.string()).max(8).optional(),
  /** Free-text label recorded on the usage row, e.g. `agent-run` (FR-064). */
  feature: z.string().min(1).max(100),
  agentId: z.uuid().nullish(),
  correlationId: z.string().min(1).max(128),
  timeoutMs: z.number().int().positive().max(600_000).default(60_000),
});

/**
 * Naming convention for every schema in this file, matching `audit.ts`:
 *   `X`        — the INPUT type, what a caller hands in (defaults still optional).
 *   `ParsedX`  — the OUTPUT type, what the schema produces (defaults applied, so the
 *                fields adapters actually rely on are non-optional).
 * Where a schema has no defaults the two are identical and only `X` is exported.
 */
export type CompletionRequest = z.input<typeof CompletionRequestSchema>;
export type ParsedCompletionRequest = z.output<typeof CompletionRequestSchema>;

export const TokenUsageSchema = z.object({
  tokensIn: z.number().int().nonnegative(),
  tokensOut: z.number().int().nonnegative(),
});

export type TokenUsage = z.infer<typeof TokenUsageSchema>;

export const CompletionResultSchema = z.object({
  provider: ProviderSlugSchema,
  model: z.string(),
  content: z.string(),
  stopReason: z.string().nullish(),
  usage: TokenUsageSchema,
  latencyMs: z.number().int().nonnegative(),
});

export type CompletionResult = z.infer<typeof CompletionResultSchema>;

export const CompletionDeltaSchema = z.object({
  provider: ProviderSlugSchema,
  model: z.string(),
  delta: z.string(),
  done: z.boolean().default(false),
});

export type CompletionDelta = z.input<typeof CompletionDeltaSchema>;
export type ParsedCompletionDelta = z.output<typeof CompletionDeltaSchema>;

export const EmbedRequestSchema = z.object({
  model: z.string().min(1).max(200),
  input: z.array(z.string().min(1)).min(1).max(512),
  feature: z.string().min(1).max(100),
  correlationId: z.string().min(1).max(128),
  timeoutMs: z.number().int().positive().max(600_000).default(60_000),
});

export type EmbedRequest = z.input<typeof EmbedRequestSchema>;
export type ParsedEmbedRequest = z.output<typeof EmbedRequestSchema>;

export const EmbedResultSchema = z.object({
  provider: ProviderSlugSchema,
  model: z.string(),
  vectors: z.array(z.array(z.number())),
  usage: TokenUsageSchema,
  latencyMs: z.number().int().nonnegative(),
});

export type EmbedResult = z.infer<typeof EmbedResultSchema>;

export const ProviderCapabilitiesSchema = z.object({
  streaming: z.boolean(),
  embeddings: z.boolean(),
  vision: z.boolean(),
});

export type ProviderCapabilities = z.infer<typeof ProviderCapabilitiesSchema>;

export const ProviderErrorClassSchema = z.enum(PROVIDER_ERROR_CLASSES);

/**
 * Per-model token rates, seeded into `SystemSetting["llm.modelRates"]`.
 * Cost estimation reads rates from configuration data — never call-site constants (FR-064).
 */
export const ModelRateSchema = z.object({
  inputPerMillionUsd: z.number().nonnegative(),
  outputPerMillionUsd: z.number().nonnegative(),
});

export type ModelRate = z.infer<typeof ModelRateSchema>;

export const ModelRatesSchema = z.record(z.string(), ModelRateSchema);

export type ModelRates = z.infer<typeof ModelRatesSchema>;

/** Usage row contract (§5.5). No prompt or completion text is ever recorded (FR-064). */
export const UsageRecordInputSchema = z.object({
  provider: z.string().min(1).max(50),
  model: z.string().min(1).max(200),
  feature: z.string().min(1).max(100),
  agentId: z.uuid().nullish(),
  tokensIn: z.number().int().nonnegative(),
  tokensOut: z.number().int().nonnegative(),
  estimatedCostUsd: z.number().nonnegative(),
  latencyMs: z.number().int().nonnegative(),
  errorClass: ProviderErrorClassSchema.nullish(),
  errorMessage: z.string().max(2000).nullish(),
  retryCount: z.number().int().nonnegative().default(0),
  correlationId: z.string().min(1).max(128).nullish(),
});

export type UsageRecordInput = z.input<typeof UsageRecordInputSchema>;
export type ParsedUsageRecordInput = z.output<typeof UsageRecordInputSchema>;

/** Cost estimation from configured rates. Returns USD, 6-decimal domain (Decimal(12,6)). */
export function estimateCostUsd(
  rates: ModelRates,
  model: string,
  tokensIn: number,
  tokensOut: number,
): number {
  const rate = rates[model];
  if (!rate) return 0;
  const cost =
    (tokensIn / 1_000_000) * rate.inputPerMillionUsd +
    (tokensOut / 1_000_000) * rate.outputPerMillionUsd;
  return Math.round(cost * 1_000_000) / 1_000_000;
}
