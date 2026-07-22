/** FR-062 — OpenAI adapter against a MOCKED transport, including the `embed` capability. */
import { describe, expect, it } from "vitest";
import { ProviderError } from "@sunil/core";
import { OpenAiAdapter } from "../adapters/openai.js";
import {
  OPENAI_COMPLETION_FIXTURE,
  OPENAI_EMBEDDING_FIXTURE,
  OPENAI_ERROR_FIXTURE,
  OPENAI_STREAM_SSE,
} from "../testing/fixtures.js";
import { MockTransport } from "../testing/mock-transport.js";
import { FakeSecretStore, SENTINEL_KEY, makeRecorder } from "./support.js";
import { withUsageRecording } from "../usage.js";

const CREDENTIAL = "llm:openai:api-key";

function adapterWith(transport: MockTransport) {
  const secrets = new FakeSecretStore({ [CREDENTIAL]: SENTINEL_KEY });
  return {
    adapter: new OpenAiAdapter({ transport: transport.fetch, secrets, credentialName: CREDENTIAL }),
    secrets,
  };
}

const request = {
  model: "gpt-4.1-mini",
  messages: [{ role: "user" as const, content: "Say hello." }],
  feature: "unit-test",
  correlationId: "corr-openai-1",
};

describe("OpenAiAdapter.complete", () => {
  it("normalises a canned chat-completions response with token counts", async () => {
    const transport = new MockTransport([{ match: "/chat/completions", json: OPENAI_COMPLETION_FIXTURE }]);
    const { adapter } = adapterWith(transport);

    const result = await adapter.complete(request);

    expect(result).toMatchObject({
      provider: "openai",
      model: "gpt-4.1-mini",
      content: "Fixture completion from a mocked transport.",
      stopReason: "stop",
      usage: { tokensIn: 31, tokensOut: 9 },
    });
  });

  it("sends `max_completion_tokens` and the bearer credential from the SecretStore", async () => {
    const transport = new MockTransport([{ match: "/chat/completions", json: OPENAI_COMPLETION_FIXTURE }]);
    const { adapter, secrets } = adapterWith(transport);

    await adapter.complete({ ...request, maxTokens: 256 });

    const recorded = transport.lastRequest();
    expect((recorded?.body as { max_completion_tokens?: number }).max_completion_tokens).toBe(256);
    expect(recorded?.headers["authorization"]).toBe(`Bearer ${SENTINEL_KEY}`);
    expect(secrets.reads).toEqual([CREDENTIAL]);
  });

  it("maps a chat-completions error response onto the typed taxonomy", async () => {
    const transport = new MockTransport([
      { match: "/chat/completions", status: 429, json: OPENAI_ERROR_FIXTURE },
    ]);
    const { adapter } = adapterWith(transport);

    const error = (await adapter.complete(request).catch((caught: unknown) => caught)) as ProviderError;

    expect(error).toBeInstanceOf(ProviderError);
    expect(error.provider).toBe("openai");
    expect(error.errorClass).toBe("rate_limit");
    expect(error.retryable).toBe(true);
    expect(error.status).toBe(429);
  });
});

describe("OpenAiAdapter.embed (FR-062)", () => {
  it("returns vectors of the declared dimensionality and is usage-logged", async () => {
    const transport = new MockTransport([{ match: "/embeddings", json: OPENAI_EMBEDDING_FIXTURE }]);
    const { adapter } = adapterWith(transport);
    const { recorder, sink } = makeRecorder({
      "text-embedding-3-small": { inputPerMillionUsd: 20, outputPerMillionUsd: 0 },
    });
    const recorded = withUsageRecording(adapter, recorder);

    const result = await recorded.embed({
      model: "text-embedding-3-small",
      input: ["alpha", "beta"],
      feature: "embed-test",
      correlationId: "corr-openai-embed",
    });

    expect(result.vectors).toHaveLength(2);
    expect(result.vectors[0]).toHaveLength(4);
    // Decoded from the base64 fixture by the SDK, then normalised to plain numbers.
    expect(result.vectors[0]?.[0]).toBeCloseTo(0.01, 6);
    expect(result.vectors[1]?.[3]).toBeCloseTo(0.08, 6);
    expect(Array.isArray(result.vectors[0])).toBe(true);
    expect(result.usage).toEqual({ tokensIn: 8, tokensOut: 0 });

    expect(sink.rows).toHaveLength(1);
    expect(sink.rows[0]).toMatchObject({
      provider: "openai",
      model: "text-embedding-3-small",
      feature: "embed-test",
      tokensIn: 8,
      tokensOut: 0,
      errorClass: null,
      correlationId: "corr-openai-embed",
    });
    expect(sink.rows[0]?.estimatedCostUsd).toBeCloseTo(0.00016, 6);
  });
});

describe("OpenAiAdapter.stream", () => {
  it("parses real SSE chunk bytes and reads usage from the final chunk", async () => {
    const transport = new MockTransport([
      {
        match: "/chat/completions",
        body: OPENAI_STREAM_SSE,
        headers: { "content-type": "text/event-stream" },
      },
    ]);
    const { adapter } = adapterWith(transport);

    const deltas: string[] = [];
    let outcome = { usage: { tokensIn: -1, tokensOut: -1 }, latencyMs: -1 };
    for await (const delta of adapter.streamWithUsage(request, (final) => {
      outcome = final;
    })) {
      if (!delta.done) deltas.push(delta.delta);
    }

    expect(deltas.join("")).toBe("Hello world");
    expect(outcome.usage).toEqual({ tokensIn: 11, tokensOut: 7 });
    expect((transport.lastRequest()?.body as { stream_options?: unknown }).stream_options).toEqual({
      include_usage: true,
    });
  });
});

describe("OpenAiAdapter capabilities", () => {
  it("declares streaming, embeddings and vision", () => {
    const { adapter } = adapterWith(new MockTransport([]));
    expect(adapter.capabilities).toEqual({ streaming: true, embeddings: true, vision: true });
  });
});
