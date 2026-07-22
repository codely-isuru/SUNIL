/**
 * FR-064 / §10.4 — one `usage_records` row per LLM call, success or failure, with rates from
 * configuration and no prompt or completion text anywhere on the row.
 */
import { describe, expect, it } from "vitest";
import { AnthropicAdapter } from "../adapters/anthropic.js";
import { OllamaAdapter } from "../adapters/ollama.js";
import {
  ANTHROPIC_MESSAGE_FIXTURE,
  ANTHROPIC_RATE_LIMIT_FIXTURE,
  ANTHROPIC_STREAM_SSE,
  OLLAMA_CHAT_FIXTURE,
} from "../testing/fixtures.js";
import { MockTransport } from "../testing/mock-transport.js";
import { StaticModelRates } from "../rates.js";
import { UsageRecorder, withUsageRecording, type UsageRow, type UsageSink } from "../usage.js";
import { FakeSecretStore, SENTINEL_KEY, makeRecorder } from "./support.js";

const CREDENTIAL = "llm:anthropic:api-key";
const RATES = { "claude-sonnet-4-5": { inputPerMillionUsd: 3, outputPerMillionUsd: 15 } };

const PROMPT = "SECRET-PROMPT-TEXT-do-not-persist";

const request = {
  model: "claude-sonnet-4-5",
  messages: [{ role: "user" as const, content: PROMPT }],
  feature: "agent-run",
  correlationId: "corr-usage-1",
};

function anthropicWith(transport: MockTransport) {
  return new AnthropicAdapter({
    transport: transport.fetch,
    secrets: new FakeSecretStore({ [CREDENTIAL]: SENTINEL_KEY }),
    credentialName: CREDENTIAL,
  });
}

describe("usage recording is decorator composition, not caller discipline", () => {
  it("writes exactly one row for a successful completion, with cost from configured rates", async () => {
    const transport = new MockTransport([{ match: "/v1/messages", json: ANTHROPIC_MESSAGE_FIXTURE }]);
    const { recorder, sink } = makeRecorder(RATES);
    const provider = withUsageRecording(anthropicWith(transport), recorder);

    await provider.complete(request, { agentId: null });

    expect(sink.rows).toHaveLength(1);
    const row = sink.rows[0] as UsageRow;
    expect(row).toMatchObject({
      provider: "anthropic",
      model: "claude-sonnet-4-5",
      feature: "agent-run",
      agentId: null,
      tokensIn: 42,
      tokensOut: 17,
      errorClass: null,
      errorMessage: null,
      retryCount: 0,
      correlationId: "corr-usage-1",
    });
    // 42/1e6*3 + 17/1e6*15 = 0.000381
    expect(row.estimatedCostUsd).toBeCloseTo(0.000381, 6);
    expect(row.latencyMs).toBeGreaterThanOrEqual(0);
  });

  it("writes a row for a FAILED call, carrying the error class and retry count", async () => {
    const transport = new MockTransport([
      { match: "/v1/messages", status: 429, json: ANTHROPIC_RATE_LIMIT_FIXTURE },
    ]);
    const { recorder, sink } = makeRecorder(RATES);
    const provider = withUsageRecording(anthropicWith(transport), recorder);

    await expect(provider.complete(request, { retryCount: 2 })).rejects.toMatchObject({
      code: "PROVIDER_ERROR",
    });

    expect(sink.rows).toHaveLength(1);
    expect(sink.rows[0]).toMatchObject({
      errorClass: "rate_limit",
      retryCount: 2,
      tokensIn: 0,
      tokensOut: 0,
      estimatedCostUsd: 0,
    });
  });

  it("writes a row for a streamed call once the stream finishes", async () => {
    const transport = new MockTransport([
      { match: "/v1/messages", body: ANTHROPIC_STREAM_SSE, headers: { "content-type": "text/event-stream" } },
    ]);
    const { recorder, sink } = makeRecorder(RATES);
    const provider = withUsageRecording(anthropicWith(transport), recorder);

    for await (const _delta of provider.stream(request)) {
      // drain
    }

    expect(sink.rows).toHaveLength(1);
    expect(sink.rows[0]).toMatchObject({ tokensIn: 11, tokensOut: 7, errorClass: null });
  });

  it("records a row for a request WE built badly, but still surfaces the ValidationError", async () => {
    const transport = new MockTransport([{ match: "/v1/messages", json: ANTHROPIC_MESSAGE_FIXTURE }]);
    const { recorder, sink } = makeRecorder(RATES);
    const provider = withUsageRecording(anthropicWith(transport), recorder);

    await expect(provider.complete({ ...request, messages: [] } as never)).rejects.toMatchObject({
      code: "VALIDATION_FAILED",
      fields: ["messages"],
    });

    expect(transport.requests).toHaveLength(0);
    expect(sink.rows).toHaveLength(1);
    expect(sink.rows[0]).toMatchObject({ errorClass: "contract", tokensIn: 0, tokensOut: 0 });
  });

  it("never records prompt or completion text (FR-064)", async () => {
    const transport = new MockTransport([{ match: "/v1/messages", json: ANTHROPIC_MESSAGE_FIXTURE }]);
    const { recorder, sink } = makeRecorder(RATES);
    const provider = withUsageRecording(anthropicWith(transport), recorder);

    await provider.complete(request);

    const serialised = JSON.stringify(sink.rows);
    expect(serialised).not.toContain(PROMPT);
    expect(serialised).not.toContain(ANTHROPIC_MESSAGE_FIXTURE.content[0]?.text);
    expect(serialised).not.toContain(SENTINEL_KEY);
  });

  it("estimates 0.00 for a model with no configured rate rather than inventing a price", async () => {
    const transport = new MockTransport([{ match: "/api/chat", json: OLLAMA_CHAT_FIXTURE }]);
    const { recorder, sink } = makeRecorder({});
    const provider = withUsageRecording(
      new OllamaAdapter({ transport: transport.fetch, baseUrl: "http://ollama.test:11434" }),
      recorder,
    );

    await provider.complete({ ...request, model: "llama3.2" });

    expect(sink.rows[0]?.estimatedCostUsd).toBe(0);
    expect(sink.rows[0]?.tokensIn).toBe(19);
  });

  it("does not fail a successful LLM call when the usage WRITE fails", async () => {
    const transport = new MockTransport([{ match: "/v1/messages", json: ANTHROPIC_MESSAGE_FIXTURE }]);
    const failingSink: UsageSink = {
      record: () => Promise.reject(new Error("usage table unavailable")),
    };
    const logged: string[] = [];
    const recorder = new UsageRecorder({
      sink: failingSink,
      rates: new StaticModelRates(RATES),
      logger: {
        debug: () => undefined,
        info: () => undefined,
        warn: () => undefined,
        error: (_context, message) => logged.push(message),
      },
    });
    const provider = withUsageRecording(anthropicWith(transport), recorder);

    await expect(provider.complete(request)).resolves.toMatchObject({ provider: "anthropic" });
    expect(logged).toHaveLength(1);
    expect(logged[0]).toContain("usage record could not be written");
  });
});
