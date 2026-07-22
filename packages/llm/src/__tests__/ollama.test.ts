/** FR-063 — Ollama adapter: local endpoint, NO API key, typed connectivity failure. */
import { describe, expect, it } from "vitest";
import { ProviderError } from "@sunil/core";
import { OllamaAdapter } from "../adapters/ollama.js";
import {
  OLLAMA_CHAT_FIXTURE,
  OLLAMA_EMBED_FIXTURE,
  OLLAMA_STREAM_NDJSON,
} from "../testing/fixtures.js";
import { MockTransport } from "../testing/mock-transport.js";

const BASE_URL = "http://ollama.test:11434";

const request = {
  model: "llama3.2",
  messages: [{ role: "user" as const, content: "Say hello." }],
  feature: "unit-test",
  correlationId: "corr-ollama-1",
};

describe("OllamaAdapter.complete", () => {
  it("returns the normalised response shape from a configured base URL", async () => {
    const transport = new MockTransport([{ match: "/api/chat", json: OLLAMA_CHAT_FIXTURE }]);
    const adapter = new OllamaAdapter({ transport: transport.fetch, baseUrl: BASE_URL });

    const result = await adapter.complete(request);

    expect(result).toMatchObject({
      provider: "ollama",
      model: "llama3.2",
      content: "Fixture completion from a mocked transport.",
      stopReason: "stop",
      usage: { tokensIn: 19, tokensOut: 12 },
    });
    expect(transport.lastRequest()?.url).toBe(`${BASE_URL}/api/chat`);
  });

  it("sends no credential header at all — Ollama has no API key (FR-063)", async () => {
    const transport = new MockTransport([{ match: "/api/chat", json: OLLAMA_CHAT_FIXTURE }]);
    const adapter = new OllamaAdapter({ transport: transport.fetch, baseUrl: BASE_URL });

    await adapter.complete(request);

    const headers = transport.lastRequest()?.headers ?? {};
    expect(headers["authorization"]).toBeUndefined();
    expect(headers["x-api-key"]).toBeUndefined();
  });

  it("returns a typed connectivity error when no Ollama service is reachable", async () => {
    const transport = new MockTransport([
      {
        match: "/api/chat",
        throws: () => new TypeError("fetch failed"),
      },
    ]);
    const adapter = new OllamaAdapter({ transport: transport.fetch, baseUrl: BASE_URL });

    const error = (await adapter.complete(request).catch((caught: unknown) => caught)) as ProviderError;

    expect(error).toBeInstanceOf(ProviderError);
    expect(error.provider).toBe("ollama");
    expect(error.errorClass).toBe("connectivity");
    expect(error.retryable).toBe(true);
    // The process is still alive and the error is ours, not undici's.
    expect(error.name).toBe("ProviderError");
  });

  it("returns a typed timeout error within the configured timeout, without crashing", async () => {
    const transport = new MockTransport([
      { match: "/api/chat", json: OLLAMA_CHAT_FIXTURE, delayMs: 500 },
    ]);
    const adapter = new OllamaAdapter({ transport: transport.fetch, baseUrl: BASE_URL });

    const startedAt = Date.now();
    const error = (await adapter
      .complete({ ...request, timeoutMs: 25 })
      .catch((caught: unknown) => caught)) as ProviderError;

    expect(error).toBeInstanceOf(ProviderError);
    expect(error.errorClass).toBe("timeout");
    expect(Date.now() - startedAt).toBeLessThan(500);
  });

  it("maps a 404 from an older server onto the non-retryable `contract` class", async () => {
    const transport = new MockTransport([{ match: "/api/embed", status: 404, json: {} }]);
    const adapter = new OllamaAdapter({ transport: transport.fetch, baseUrl: BASE_URL });

    const error = (await adapter
      .embed({ model: "nomic-embed-text", input: ["a"], feature: "f", correlationId: "c" })
      .catch((caught: unknown) => caught)) as ProviderError;

    expect(error.errorClass).toBe("contract");
    expect(error.retryable).toBe(false);
    expect(error.status).toBe(404);
  });
});

describe("OllamaAdapter.embed and .stream", () => {
  it("returns embedding vectors from /api/embed", async () => {
    const transport = new MockTransport([{ match: "/api/embed", json: OLLAMA_EMBED_FIXTURE }]);
    const adapter = new OllamaAdapter({ transport: transport.fetch, baseUrl: BASE_URL });

    const result = await adapter.embed({
      model: "nomic-embed-text",
      input: ["alpha", "beta"],
      feature: "embed-test",
      correlationId: "corr-ollama-embed",
    });

    expect(result.vectors).toEqual([
      [0.11, 0.22, 0.33],
      [0.44, 0.55, 0.66],
    ]);
    expect(result.usage).toEqual({ tokensIn: 6, tokensOut: 0 });
  });

  it("parses NDJSON stream framing and accumulates final token counts", async () => {
    const transport = new MockTransport([
      {
        match: "/api/chat",
        body: OLLAMA_STREAM_NDJSON,
        headers: { "content-type": "application/x-ndjson" },
      },
    ]);
    const adapter = new OllamaAdapter({ transport: transport.fetch, baseUrl: BASE_URL });

    const deltas: string[] = [];
    let outcome = { usage: { tokensIn: -1, tokensOut: -1 }, latencyMs: -1 };
    for await (const delta of adapter.streamWithUsage(request, (final) => {
      outcome = final;
    })) {
      if (!delta.done) deltas.push(delta.delta);
    }

    expect(deltas.join("")).toBe("Hello world");
    expect(outcome.usage).toEqual({ tokensIn: 5, tokensOut: 3 });
  });

  it("declares no vision capability and refuses it in a typed way", () => {
    const adapter = new OllamaAdapter({ transport: new MockTransport([]).fetch });
    expect(adapter.capabilities).toEqual({ streaming: true, embeddings: true, vision: false });
  });
});
