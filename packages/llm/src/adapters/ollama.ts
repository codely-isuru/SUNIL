/**
 * ⚠ UNVERIFIED AGAINST LIVE ENDPOINTS — mock-verified only (Gate 1 / FR-063 / §10.5) ⚠
 *
 * Ollama adapter. No official SDK worth pinning and a small REST surface, so this one calls
 * the injected `Transport` directly (ADR-008) against `${baseUrl}/api/chat` and `/api/embed`.
 *
 * NO API KEY: Ollama is a local endpoint. The base URL is configuration (`OLLAMA_BASE_URL`)
 * supplied by the caller — this file never reads `process.env`.
 *
 * FR-063's second criterion is the important one: when no Ollama service is reachable, the
 * call returns a typed `connectivity` (or `timeout`) ProviderError within the configured
 * timeout, and neither the API nor the worker process crashes.
 */
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

export const OLLAMA_CAPABILITIES: ProviderCapabilities = {
  streaming: true,
  embeddings: true,
  vision: false,
};

export const DEFAULT_OLLAMA_BASE_URL = "http://localhost:11434";

export interface OllamaAdapterOptions {
  readonly transport: Transport;
  /** From `OLLAMA_BASE_URL` / the provider row. No credential exists for Ollama (FR-063). */
  readonly baseUrl?: string | null;
}

interface OllamaChatResponse {
  model?: string;
  message?: { role?: string; content?: string };
  done_reason?: string | null;
  prompt_eval_count?: number;
  eval_count?: number;
}

interface OllamaEmbedResponse {
  model?: string;
  embeddings?: number[][];
  prompt_eval_count?: number;
}

export class OllamaAdapter implements LLMAdapter {
  readonly slug: ProviderSlug = "ollama";
  readonly capabilities = OLLAMA_CAPABILITIES;
  readonly verification: Phase1Verification = PHASE1_VERIFICATION;

  readonly #transport: Transport;
  readonly #baseUrl: string;

  constructor(options: OllamaAdapterOptions) {
    this.#transport = options.transport;
    this.#baseUrl = (options.baseUrl ?? DEFAULT_OLLAMA_BASE_URL).replace(/\/+$/, "");
  }

  async #post(path: string, body: unknown, signal: AbortSignal): Promise<Response> {
    const response = await this.#transport(`${this.#baseUrl}${path}`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(body),
      signal,
    });

    if (!response.ok) {
      // Raw transport failures never escape: this becomes a typed ProviderError with the
      // status-derived class (§10.3).
      throw Object.assign(new Error(`ollama responded ${response.status}`), {
        status: response.status,
      });
    }
    return response;
  }

  async complete(request: CompletionRequest, options?: CallOptions): Promise<CompletionResult> {
    const parsed = parseRequest(request);
    const startedAt = Date.now();
    const deadline = deadlineSignal(parsed.timeoutMs, options?.signal);

    try {
      const response = await this.#post("/api/chat", chatBody(parsed, false), deadline.signal);
      const payload = (await response.json()) as OllamaChatResponse;

      return CompletionResultSchema.parse({
        provider: this.slug,
        model: payload.model ?? parsed.model,
        content: payload.message?.content ?? "",
        stopReason: payload.done_reason ?? null,
        // Contract note `ollama.token-count-fields`: absent counts are 0, never estimated.
        usage: {
          tokensIn: payload.prompt_eval_count ?? 0,
          tokensOut: payload.eval_count ?? 0,
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
      const response = await this.#post("/api/chat", chatBody(parsed, true), deadline.signal);

      // Ollama streams NDJSON, one JSON object per line.
      for await (const line of readLines(response)) {
        const chunk = JSON.parse(line) as OllamaChatResponse & { done?: boolean };
        if (chunk.model) model = chunk.model;
        if (typeof chunk.prompt_eval_count === "number") tokensIn = chunk.prompt_eval_count;
        if (typeof chunk.eval_count === "number") tokensOut = chunk.eval_count;
        const delta = chunk.message?.content ?? "";
        if (delta.length > 0) yield { provider: this.slug, model, delta, done: false };
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
    if (!result.success) throw toValidationError(result.error, "ollama embed request");
    const parsed = result.data;

    const startedAt = Date.now();
    const deadline = deadlineSignal(parsed.timeoutMs, options?.signal);

    try {
      const response = await this.#post(
        "/api/embed",
        { model: parsed.model, input: [...parsed.input] },
        deadline.signal,
      );
      const payload = (await response.json()) as OllamaEmbedResponse;

      return EmbedResultSchema.parse({
        provider: this.slug,
        model: payload.model ?? parsed.model,
        vectors: payload.embeddings ?? [],
        usage: { tokensIn: payload.prompt_eval_count ?? 0, tokensOut: 0 },
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
  if (!result.success) throw toValidationError(result.error, "ollama completion request");
  return result.data;
}

type ParsedRequest = ReturnType<typeof parseRequest>;

function chatBody(parsed: ParsedRequest, stream: boolean): Record<string, unknown> {
  return {
    model: parsed.model,
    messages: parsed.messages.map((message) => ({ role: message.role, content: message.content })),
    stream,
    options: {
      num_predict: parsed.maxTokens,
      ...(parsed.temperature === undefined ? {} : { temperature: parsed.temperature }),
      ...(parsed.stopSequences === undefined ? {} : { stop: [...parsed.stopSequences] }),
    },
  };
}

/** Yield complete NDJSON lines from a streamed body, tolerating chunk boundaries. */
async function* readLines(response: Response): AsyncGenerator<string> {
  const body = response.body;
  if (!body) return;

  const decoder = new TextDecoder();
  let buffer = "";

  for await (const chunk of body as unknown as AsyncIterable<Uint8Array>) {
    buffer += decoder.decode(chunk, { stream: true });
    let newline = buffer.indexOf("\n");
    while (newline >= 0) {
      const line = buffer.slice(0, newline).trim();
      buffer = buffer.slice(newline + 1);
      if (line.length > 0) yield line;
      newline = buffer.indexOf("\n");
    }
  }

  const tail = buffer.trim();
  if (tail.length > 0) yield tail;
}
