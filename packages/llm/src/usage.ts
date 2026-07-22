/**
 * Usage recording (§10.4, FR-064).
 *
 * ONE `usage_records` row per LLM call, success or failure. This is DECORATOR COMPOSITION,
 * not caller discipline: `withUsageRecording(adapter, recorder)` wraps every method, and the
 * provider factory applies it unconditionally, so there is no way to obtain a provider from
 * this package that does not record.
 *
 * What never reaches the row: prompt text, completion text, credentials. Only the redacted
 * error message, token counts, cost, latency and identifiers.
 */
import {
  UsageRecordInputSchema,
  ValidationError,
  estimateCostUsd,
  type Infer,
  type ProviderErrorClass,
} from "@sunil/core";
import type { CompletionRequest, CompletionResult, ProviderSlug } from "@sunil/core";
import type { UsageRepository } from "@sunil/db";
import { toProviderError } from "./errors.js";
import { NOOP_LLM_LOGGER, type LlmLogger } from "./logging.js";
import type { ModelRatesSource } from "./rates.js";
import {
  isLLMAdapter,
  type CallOptions,
  type CompletionDelta,
  type EmbedRequest,
  type EmbedResult,
  type LLMProvider,
  type StreamOutcome,
  type TokenUsage,
} from "./provider.js";

export type UsageRow = Infer<typeof UsageRecordInputSchema>;

/** Where usage rows go. Implemented against `UsageRepository`; faked in tests. */
export interface UsageSink {
  record(row: UsageRow): Promise<void>;
}

/** The Phase 1 sink: `usage_records` in Postgres, written outside any audited transaction. */
export class PrismaUsageSink implements UsageSink {
  readonly #usage: UsageRepository;

  constructor(usage: UsageRepository) {
    this.#usage = usage;
  }

  async record(row: UsageRow): Promise<void> {
    await this.#usage.record({
      provider: row.provider,
      model: row.model,
      feature: row.feature,
      tokensIn: row.tokensIn,
      tokensOut: row.tokensOut,
      estimatedCostUsd: row.estimatedCostUsd,
      latencyMs: row.latencyMs,
      errorClass: row.errorClass ?? null,
      errorMessage: row.errorMessage ?? null,
      retryCount: row.retryCount,
      correlationId: row.correlationId ?? null,
      ...(row.agentId ? { agent: { connect: { id: row.agentId } } } : {}),
    });
  }
}

export interface UsageCallMeta {
  readonly provider: ProviderSlug;
  readonly model: string;
  readonly feature: string;
  readonly correlationId: string;
  readonly agentId?: string | null;
  readonly retryCount?: number;
}

const ZERO_USAGE: TokenUsage = { tokensIn: 0, tokensOut: 0 };

export class UsageRecorder {
  readonly #sink: UsageSink;
  readonly #rates: ModelRatesSource;
  readonly #logger: LlmLogger;
  readonly #now: () => number;

  constructor(deps: {
    sink: UsageSink;
    rates: ModelRatesSource;
    logger?: LlmLogger;
    now?: () => number;
  }) {
    this.#sink = deps.sink;
    this.#rates = deps.rates;
    this.#logger = deps.logger ?? NOOP_LLM_LOGGER;
    this.#now = deps.now ?? Date.now;
  }

  /**
   * Run a call and record exactly one usage row for it.
   *
   * A failure in the usage WRITE is logged at `error` (an operational alert condition) and
   * never converts a successful LLM call into a failed one — usage is observability, unlike
   * audit, whose failure deliberately fails the request (ADR-005).
   */
  async around<T>(
    meta: UsageCallMeta,
    call: () => Promise<T>,
    extractUsage: (result: T) => TokenUsage,
  ): Promise<T> {
    const startedAt = this.#now();
    try {
      const result = await call();
      await this.#write(meta, extractUsage(result), this.#now() - startedAt, undefined);
      return result;
    } catch (error) {
      const providerError = toProviderError(meta.provider, error);
      await this.#write(meta, ZERO_USAGE, this.#now() - startedAt, providerError);
      // A request WE built badly is a 400, not a 502: the usage row records it as `contract`,
      // but the caller keeps the typed ValidationError naming the field.
      throw error instanceof ValidationError ? error : providerError;
    }
  }

  /** Record a call whose usage is known after the fact — the streaming path. */
  async recordOutcome(
    meta: UsageCallMeta,
    outcome: { usage: TokenUsage; latencyMs: number; error?: unknown },
  ): Promise<void> {
    const providerError = outcome.error === undefined ? undefined : toProviderError(meta.provider, outcome.error);
    await this.#write(meta, outcome.usage, outcome.latencyMs, providerError);
  }

  async #write(
    meta: UsageCallMeta,
    usage: TokenUsage,
    latencyMs: number,
    error: { errorClass: ProviderErrorClass; message: string } | undefined,
  ): Promise<void> {
    try {
      const rates = await this.#rates.get();
      const row = UsageRecordInputSchema.parse({
        provider: meta.provider,
        model: meta.model,
        feature: meta.feature,
        agentId: meta.agentId ?? null,
        tokensIn: usage.tokensIn,
        tokensOut: usage.tokensOut,
        estimatedCostUsd: estimateCostUsd(rates, meta.model, usage.tokensIn, usage.tokensOut),
        latencyMs: Math.max(0, Math.round(latencyMs)),
        errorClass: error?.errorClass ?? null,
        // Already scrubbed by `toProviderError`; truncated by the schema's max length.
        errorMessage: error ? error.message.slice(0, 2000) : null,
        retryCount: meta.retryCount ?? 0,
        correlationId: meta.correlationId,
      });
      await this.#sink.record(row);
    } catch (writeError) {
      this.#logger.error(
        {
          provider: meta.provider,
          model: meta.model,
          feature: meta.feature,
          correlationId: meta.correlationId,
          error: writeError instanceof Error ? writeError.name : "unknown",
        },
        "usage record could not be written (FR-064); the LLM call outcome stands",
      );
    }
  }
}

/**
 * Wrap a provider so every call records usage. Applied by the factory, never left to the
 * caller — that is what "decorator composition in the package, not caller discipline" means.
 */
export function withUsageRecording(provider: LLMProvider, recorder: UsageRecorder): LLMProvider {
  const metaFor = (
    model: string,
    feature: string,
    correlationId: string,
    options: CallOptions | undefined,
    agentIdFromRequest?: string | null,
  ): UsageCallMeta => ({
    provider: provider.slug,
    model,
    feature,
    correlationId,
    agentId: options?.agentId ?? agentIdFromRequest ?? null,
    retryCount: options?.retryCount ?? 0,
  });

  return {
    slug: provider.slug,
    capabilities: provider.capabilities,
    verification: provider.verification,

    complete(request: CompletionRequest, options?: CallOptions): Promise<CompletionResult> {
      return recorder.around(
        metaFor(request.model, request.feature, request.correlationId, options, request.agentId),
        () => provider.complete(request, options),
        (result) => result.usage,
      );
    },

    embed(request: EmbedRequest, options?: CallOptions): Promise<EmbedResult> {
      return recorder.around(
        metaFor(request.model, request.feature, request.correlationId, options),
        () => provider.embed(request, options),
        (result) => result.usage,
      );
    },

    stream(request: CompletionRequest, options?: CallOptions): AsyncIterable<CompletionDelta> {
      const meta = metaFor(
        request.model,
        request.feature,
        request.correlationId,
        options,
        request.agentId,
      );

      if (!isLLMAdapter(provider)) {
        // A provider without the internal seam still records — with the counts it can prove.
        return recordSimpleStream(provider, request, options, recorder, meta);
      }

      return recordAdapterStream(provider, request, options, recorder, meta);
    },
  };
}

async function* recordAdapterStream(
  provider: LLMProvider & {
    streamWithUsage(
      request: CompletionRequest,
      onComplete: (outcome: StreamOutcome) => void,
      options?: CallOptions,
    ): AsyncIterable<CompletionDelta>;
  },
  request: CompletionRequest,
  options: CallOptions | undefined,
  recorder: UsageRecorder,
  meta: UsageCallMeta,
): AsyncIterable<CompletionDelta> {
  let outcome: StreamOutcome = { usage: ZERO_USAGE, latencyMs: 0 };
  let failure: unknown;
  try {
    for await (const delta of provider.streamWithUsage(
      request,
      (final) => {
        outcome = final;
      },
      options,
    )) {
      yield delta;
    }
  } catch (error) {
    failure = toProviderError(provider.slug, error);
    throw failure;
  } finally {
    await recorder.recordOutcome(meta, {
      usage: outcome.usage,
      latencyMs: outcome.latencyMs,
      ...(failure === undefined ? {} : { error: failure }),
    });
  }
}

async function* recordSimpleStream(
  provider: LLMProvider,
  request: CompletionRequest,
  options: CallOptions | undefined,
  recorder: UsageRecorder,
  meta: UsageCallMeta,
): AsyncIterable<CompletionDelta> {
  const startedAt = Date.now();
  let failure: unknown;
  try {
    for await (const delta of provider.stream(request, options)) {
      yield delta;
    }
  } catch (error) {
    failure = toProviderError(provider.slug, error);
    throw failure;
  } finally {
    await recorder.recordOutcome(meta, {
      usage: ZERO_USAGE,
      latencyMs: Date.now() - startedAt,
      ...(failure === undefined ? {} : { error: failure }),
    });
  }
}
