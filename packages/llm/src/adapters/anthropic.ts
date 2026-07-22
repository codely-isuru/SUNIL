/**
 * ⚠ UNVERIFIED AGAINST LIVE ENDPOINTS — mock-verified only (Gate 1 / FR-061 / §10.5) ⚠
 *
 * Anthropic adapter. Wraps the official `@anthropic-ai/sdk` constructed with an INJECTED
 * `fetch` (ADR-008): the SDK owns the auth-header shape, the SSE framing and the field names
 * — the parts R-01 says we cannot verify — so the unverifiable surface is reduced to the
 * normalisation in this file.
 *
 * Credential handling (FR-061): the API key is resolved from `SecretStore` AT CALL TIME and
 * passed into the SDK constructor inside `SecretValue.use(...)`. It is never read from a DB
 * column, never read from `process.env` here, never logged, and never stored on the instance.
 */
import Anthropic from "@anthropic-ai/sdk";
import {
  CompletionRequestSchema,
  CompletionResultSchema,
  PHASE1_VERIFICATION,
} from "@sunil/core";
import type {
  CompletionRequest,
  CompletionResult,
  ProviderCapabilities,
  ProviderSlug,
  SecretStore,
} from "@sunil/core";
import { toProviderError, toValidationError } from "../errors.js";
import { assertCapability } from "../provider.js";
import type {
  CallOptions,
  CompletionDelta,
  EmbedRequest,
  EmbedResult,
  LLMAdapter,
  StreamOutcome,
} from "../provider.js";
import { deadlineSignal, type Transport } from "../transport.js";
import type { Phase1Verification } from "../verification.js";

export const ANTHROPIC_CAPABILITIES: ProviderCapabilities = {
  streaming: true,
  embeddings: false,
  vision: true,
};

export interface AnthropicAdapterOptions {
  readonly transport: Transport;
  readonly secrets: SecretStore;
  /** Reference INTO the SecretStore (`llm:anthropic:api-key`), never a credential value. */
  readonly credentialName: string;
  readonly baseUrl?: string | null;
}

type ParsedRequest = ReturnType<typeof parseRequest>;

export class AnthropicAdapter implements LLMAdapter {
  readonly slug: ProviderSlug = "anthropic";
  readonly capabilities = ANTHROPIC_CAPABILITIES;
  readonly verification: Phase1Verification = PHASE1_VERIFICATION;

  readonly #options: AnthropicAdapterOptions;

  constructor(options: AnthropicAdapterOptions) {
    this.#options = options;
  }

  /**
   * Build a client for ONE call inside `SecretValue.use`. Deliberately not cached: the
   * credential's lifetime is the call, not the process.
   */
  async #withClient<T>(fn: (client: Anthropic) => Promise<T>): Promise<T> {
    const secret = await this.#options.secrets.get(this.#options.credentialName);
    return secret.use((apiKey) =>
      fn(
        new Anthropic({
          apiKey,
          fetch: this.#options.transport,
          // The SDK retries internally by default; retries are the caller's decision here so
          // that `usage_records.retryCount` reflects reality.
          maxRetries: 0,
          ...(this.#options.baseUrl ? { baseURL: this.#options.baseUrl } : {}),
        }),
      ),
    );
  }

  async complete(request: CompletionRequest, options?: CallOptions): Promise<CompletionResult> {
    const parsed = parseRequest(request);
    const startedAt = Date.now();
    const deadline = deadlineSignal(parsed.timeoutMs, options?.signal);

    try {
      const message = await this.#withClient((client) =>
        client.messages.create({ ...messageParams(parsed) }, { signal: deadline.signal }),
      );

      const content = message.content
        .map((block) => (block.type === "text" ? block.text : ""))
        .join("");

      // Boundary validation, outbound direction (FR-060/NFR-003). A shape we did not expect
      // is contract drift and surfaces as a typed `contract` ProviderError.
      return CompletionResultSchema.parse({
        provider: this.slug,
        model: message.model,
        content,
        stopReason: message.stop_reason,
        usage: {
          tokensIn: message.usage.input_tokens,
          tokensOut: message.usage.output_tokens,
        },
        latencyMs: Date.now() - startedAt,
      });
    } catch (error) {
      throw toProviderError(this.slug, error);
    } finally {
      deadline.dispose();
    }
  }

  stream(request: CompletionRequest, options?: CallOptions): AsyncIterable<CompletionDelta> {
    return this.streamWithUsage(request, () => undefined, options);
  }

  async *streamWithUsage(
    request: CompletionRequest,
    onComplete: (outcome: StreamOutcome) => void,
    options?: CallOptions,
  ): AsyncIterable<CompletionDelta> {
    assertCapability(this.slug, this.capabilities, "streaming");
    const parsed = parseRequest(request);
    const startedAt = Date.now();
    const deadline = deadlineSignal(parsed.timeoutMs, options?.signal);
    let tokensIn = 0;
    let tokensOut = 0;
    let model = parsed.model;

    try {
      const stream = await this.#withClient((client) =>
        client.messages.create(
          { ...messageParams(parsed), stream: true },
          { signal: deadline.signal },
        ),
      );

      for await (const event of stream) {
        if (event.type === "message_start") {
          tokensIn = event.message.usage.input_tokens;
          model = event.message.model;
        } else if (event.type === "content_block_delta" && event.delta.type === "text_delta") {
          yield { provider: this.slug, model, delta: event.delta.text, done: false };
        } else if (event.type === "message_delta") {
          tokensOut = event.usage.output_tokens;
        }
      }

      yield { provider: this.slug, model, delta: "", done: true };
    } catch (error) {
      throw toProviderError(this.slug, error);
    } finally {
      deadline.dispose();
      onComplete({ usage: { tokensIn, tokensOut }, latencyMs: Date.now() - startedAt });
    }
  }

  /** Anthropic exposes no embeddings endpoint — FR-060's typed refusal, not a silent 404. */
  async embed(_request: EmbedRequest, _options?: CallOptions): Promise<EmbedResult> {
    assertCapability(this.slug, this.capabilities, "embeddings");
    throw new Error("unreachable: the capability assertion above always throws");
  }
}

/** Boundary validation, inbound direction (FR-060/NFR-003). */
function parseRequest(request: CompletionRequest) {
  const result = CompletionRequestSchema.safeParse(request);
  if (!result.success) throw toValidationError(result.error, "anthropic completion request");
  return result.data;
}

/**
 * Contract note `anthropic.system-messages`: the Messages API takes `system` as a top-level
 * parameter, so inline system messages are hoisted rather than sent as a `system` role.
 */
function messageParams(parsed: ParsedRequest): {
  model: string;
  max_tokens: number;
  messages: { role: "user" | "assistant"; content: string }[];
  system?: string;
  temperature?: number;
  stop_sequences?: string[];
} {
  const system = parsed.messages
    .filter((message) => message.role === "system")
    .map((message) => message.content);

  return {
    model: parsed.model,
    max_tokens: parsed.maxTokens,
    messages: parsed.messages
      .filter((message) => message.role !== "system")
      .map((message) => ({ role: message.role as "user" | "assistant", content: message.content })),
    ...(system.length > 0 ? { system: system.join("\n") } : {}),
    ...(parsed.temperature === undefined ? {} : { temperature: parsed.temperature }),
    ...(parsed.stopSequences === undefined ? {} : { stop_sequences: parsed.stopSequences }),
  };
}
