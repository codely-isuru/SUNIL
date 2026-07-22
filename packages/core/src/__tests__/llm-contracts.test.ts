/**
 * Contract-completeness tests for `schemas/llm.ts`.
 *
 * The type assertions here are the real subject: they are compiled by `tsconfig.spec.json`,
 * so if an exported type alias is removed or its inference changes, `pnpm typecheck` fails.
 * Before this file existed, `CompletionDeltaSchema`, `EmbedRequestSchema`, `EmbedResultSchema`
 * and `TokenUsageSchema` exported a schema with no companion type, which forced consumers to
 * write `z.infer<typeof …>` locally — a second, drifting definition of the same contract.
 */
import { describe, expect, it } from "vitest";
import {
  ChatMessageSchema,
  CompletionDeltaSchema,
  CompletionRequestSchema,
  EmbedRequestSchema,
  EmbedResultSchema,
  ModelRateSchema,
  TokenUsageSchema,
  type ChatMessage,
  type ChatRole,
  type CompletionDelta,
  type CompletionRequest,
  type EmbedRequest,
  type EmbedResult,
  type ModelRate,
  type ParsedCompletionDelta,
  type ParsedCompletionRequest,
  type ParsedEmbedRequest,
  type TokenUsage,
} from "../schemas/llm.js";

describe("every LLM schema exports its inferred type", () => {
  it("TokenUsage", () => {
    const usage: TokenUsage = { tokensIn: 10, tokensOut: 20 };
    expect(TokenUsageSchema.parse(usage)).toEqual(usage);
  });

  it("ChatRole / ChatMessage", () => {
    const role: ChatRole = "assistant";
    const message: ChatMessage = { role, content: "hello" };
    expect(ChatMessageSchema.parse(message)).toEqual(message);
  });

  it("ModelRate", () => {
    const rate: ModelRate = { inputPerMillionUsd: 3, outputPerMillionUsd: 15 };
    expect(ModelRateSchema.parse(rate)).toEqual(rate);
  });

  it("EmbedRequest / ParsedEmbedRequest — the parsed form has defaults applied", () => {
    const request: EmbedRequest = {
      model: "embed-x",
      input: ["a"],
      feature: "smoke-test",
      correlationId: "corr-1",
      // `timeoutMs` is omitted: that is what makes the input type distinct from the output.
    };
    const parsed: ParsedEmbedRequest = EmbedRequestSchema.parse(request);
    expect(parsed.timeoutMs).toBe(60_000);
  });

  it("EmbedResult", () => {
    const result: EmbedResult = {
      provider: "openai",
      model: "embed-x",
      vectors: [[0.1, 0.2]],
      usage: { tokensIn: 5, tokensOut: 0 },
      latencyMs: 12,
    };
    expect(EmbedResultSchema.parse(result)).toEqual(result);
  });

  it("CompletionDelta / ParsedCompletionDelta — `done` is optional in, required out", () => {
    const delta: CompletionDelta = { provider: "anthropic", model: "m", delta: "tok" };
    const parsed: ParsedCompletionDelta = CompletionDeltaSchema.parse(delta);
    expect(parsed.done).toBe(false);
  });

  it("CompletionRequest / ParsedCompletionRequest", () => {
    const request: CompletionRequest = {
      model: "m",
      messages: [{ role: "user", content: "hi" }],
      feature: "smoke-test",
      correlationId: "corr-2",
    };
    const parsed: ParsedCompletionRequest = CompletionRequestSchema.parse(request);
    expect(parsed.maxTokens).toBe(1024);
    expect(parsed.timeoutMs).toBe(60_000);
  });
});
