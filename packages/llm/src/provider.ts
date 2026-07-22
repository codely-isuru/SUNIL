/**
 * The `LLMProvider` interface (§10.1) — one interface, three adapters, no routing.
 *
 * Scope fence (FR-066): this package contains NO routing rules, NO primary/fallback
 * selection, NO failover and NO budget caps. A caller names the provider slug explicitly as
 * configuration. Budget enforcement lives in the agent runtime loop (§11.4), not here.
 */
import { CapabilityNotSupportedError } from "@sunil/core";
import type { z } from "@sunil/core";
import type {
  CompletionDeltaSchema,
  CompletionRequest,
  CompletionResult,
  EmbedRequestSchema,
  EmbedResultSchema,
  ProviderCapabilities,
  ProviderSlug,
  TokenUsageSchema,
} from "@sunil/core";
import type { Phase1Verification } from "./verification.js";

/**
 * `@sunil/core` exports these schemas but not their inferred types, so they are derived here
 * rather than redefined — the schema remains the single source of truth. `EmbedRequest` is
 * the INPUT type (defaults still optional), matching how core exports `CompletionRequest`.
 */
export type CompletionDelta = z.infer<typeof CompletionDeltaSchema>;
export type EmbedRequest = z.input<typeof EmbedRequestSchema>;
export type EmbedResult = z.infer<typeof EmbedResultSchema>;
export type TokenUsage = z.infer<typeof TokenUsageSchema>;

export type Capability = keyof ProviderCapabilities;

export interface LLMProvider {
  readonly slug: ProviderSlug;
  readonly capabilities: ProviderCapabilities;
  /** Phase 1 literal — see §10.5. Cannot widen to anything implying live verification. */
  readonly verification: Phase1Verification;

  complete(request: CompletionRequest, options?: CallOptions): Promise<CompletionResult>;
  /** Capability-gated: throws `CapabilityNotSupportedError` when `capabilities.streaming` is false. */
  stream(request: CompletionRequest, options?: CallOptions): AsyncIterable<CompletionDelta>;
  /** Capability-gated: throws `CapabilityNotSupportedError` when `capabilities.embeddings` is false. */
  embed(request: EmbedRequest, options?: CallOptions): Promise<EmbedResult>;
}

export interface CallOptions {
  /** Caller-owned cancellation — composed with the per-request deadline (§11.4). */
  readonly signal?: AbortSignal;
  /** Recorded on the usage row; the caller's own retry attempts, not the SDK's. */
  readonly retryCount?: number;
  /** Attributes usage to an agent run (nullable — FR-064). */
  readonly agentId?: string | null;
}

/**
 * Reported by an adapter when a stream finishes, so the usage recorder can write one row per
 * streamed call without the public interface carrying usage on every delta.
 */
export interface StreamOutcome {
  readonly usage: TokenUsage;
  readonly latencyMs: number;
}

/**
 * Internal adapter surface. Adapters implement this; consumers only ever see `LLMProvider`.
 * The extra method exists so `withUsageRecording` can record a streamed call's token counts
 * (which arrive out of band, in provider-specific stream events).
 */
export interface LLMAdapter extends LLMProvider {
  streamWithUsage(
    request: CompletionRequest,
    onComplete: (outcome: StreamOutcome) => void,
    options?: CallOptions,
  ): AsyncIterable<CompletionDelta>;
}

export function isLLMAdapter(provider: LLMProvider): provider is LLMAdapter {
  return typeof (provider as LLMAdapter).streamWithUsage === "function";
}

/**
 * FR-060: invoking an undeclared capability throws a typed, documented error rather than
 * failing ambiguously somewhere inside an SDK.
 */
export function assertCapability(
  slug: ProviderSlug,
  capabilities: ProviderCapabilities,
  capability: Capability,
): void {
  if (!capabilities[capability]) {
    throw new CapabilityNotSupportedError(slug, capability);
  }
}
