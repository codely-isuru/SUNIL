/**
 * ⚠ UNVERIFIED AGAINST LIVE ENDPOINTS — mock-verified only (Gate 1 / FR-062 / §10.5) ⚠
 *
 * OpenAI adapter. Wraps the official `openai` SDK constructed with an INJECTED `fetch`
 * (ADR-008). Supports completions, streaming and embeddings.
 *
 * Credential handling (FR-061/062): resolved from `SecretStore` at call time and passed into
 * the SDK constructor inside `SecretValue.use(...)`. Never a DB column read, never an env
 * read here, never logged.
 *
 * Recorded contract ambiguity `openai.max-tokens-field`: we send `max_completion_tokens`.
 */
import OpenAI from "openai";
import {
  CompletionRequestSchema,
  CompletionResultSchema,
  EmbedRequestSchema,
  EmbedResultSchema,
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

export const OPENAI_CAPABILITIES: ProviderCapabilities = {
  streaming: true,
  embeddings: true,
  vision: true,
};

export interface OpenAiAdapterOptions {
  readonly transport: Transport;
  readonly secrets: SecretStore;
  /** Reference INTO the SecretStore (`llm:openai:api-key`), never a credential value. */
  readonly credentialName: string;
  readonly baseUrl?: string | null;
}

type ParsedRequest = ReturnType<typeof parseRequest>;

export class OpenAiAdapter implements LLMAdapter {
  readonly slug: ProviderSlug = "openai";
  readonly capabilities = OPENAI_CAPABILITIES;
  readonly verification: Phase1Verification = PHASE1_VERIFICATION;

  readonly #options: OpenAiAdapterOptions;

  constructor(options: OpenAiAdapterOptions) {
    this.#options = options;
  }

  async #withClient<T>(fn: (client: OpenAI) => Promise<T>): Promise<T> {
    const secret = await this.#options.secrets.get(this.#options.credentialName);
    return secret.use((apiKey) =>
      fn(
        new OpenAI({
          apiKey,
          fetch: this.#options.transport,
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
      const completion = await this.#withClient((client) =>
        client.chat.completions.create({ ...chatParams(parsed) }, { signal: deadline.signal }),
      );

      const choice = completion.choices[0];

      return CompletionResultSchema.parse({
        provider: this.slug,
        model: completion.model,
        content: choice?.message.content ?? "",
        stopReason: choice?.finish_reason ?? null,
        usage: {
          tokensIn: completion.usage?.prompt_tokens ?? 0,
          tokensOut: completion.usage?.completion_tokens ?? 0,
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
        client.chat.completions.create(
          {
            ...chatParams(parsed),
            stream: true,
            // Without this the streamed response carries no usage block at all.
            stream_options: { include_usage: true },
          },
          { signal: deadline.signal },
        ),
      );

      for await (const chunk of stream) {
        if (chunk.model) model = chunk.model;
        if (chunk.usage) {
          tokensIn = chunk.usage.prompt_tokens;
          tokensOut = chunk.usage.completion_tokens;
        }
        const delta = chunk.choices[0]?.delta.content;
        if (delta) yield { provider: this.slug, model, delta, done: false };
      }

      yield { provider: this.slug, model, delta: "", done: true };
    } catch (error) {
      throw toProviderError(this.slug, error);
    } finally {
      deadline.dispose();
      onComplete({ usage: { tokensIn, tokensOut }, latencyMs: Date.now() - startedAt });
    }
  }

  async embed(request: EmbedRequest, options?: CallOptions): Promise<EmbedResult> {
    assertCapability(this.slug, this.capabilities, "embeddings");
    const result = EmbedRequestSchema.safeParse(request);
    if (!result.success) throw toValidationError(result.error, "openai embed request");
    const parsed = result.data;

    const startedAt = Date.now();
    const deadline = deadlineSignal(parsed.timeoutMs, options?.signal);

    try {
      const response = await this.#withClient((client) =>
        client.embeddings.create(
          { model: parsed.model, input: [...parsed.input] },
          { signal: deadline.signal },
        ),
      );

      return EmbedResultSchema.parse({
        provider: this.slug,
        model: response.model,
        // The SDK requests base64 by default and hands back a Float32Array; `Array.from`
        // normalises both that and a plain float array to `number[]` (contract note
        // `openai.embedding-encoding`).
        vectors: response.data.map((item) => Array.from(item.embedding)),
        // Contract note `openai.embedding-token-counts`: embeddings have no output tokens.
        usage: { tokensIn: response.usage?.prompt_tokens ?? 0, tokensOut: 0 },
        latencyMs: Date.now() - startedAt,
      });
    } catch (error) {
      throw toProviderError(this.slug, error);
    } finally {
      deadline.dispose();
    }
  }
}

function parseRequest(request: CompletionRequest) {
  const result = CompletionRequestSchema.safeParse(request);
  if (!result.success) throw toValidationError(result.error, "openai completion request");
  return result.data;
}

function chatParams(parsed: ParsedRequest): {
  model: string;
  messages: { role: "system" | "user" | "assistant"; content: string }[];
  max_completion_tokens: number;
  temperature?: number;
  stop?: string[];
} {
  return {
    model: parsed.model,
    messages: parsed.messages.map((message) => ({ role: message.role, content: message.content })),
    max_completion_tokens: parsed.maxTokens,
    ...(parsed.temperature === undefined ? {} : { temperature: parsed.temperature }),
    ...(parsed.stopSequences === undefined ? {} : { stop: [...parsed.stopSequences] }),
  };
}
