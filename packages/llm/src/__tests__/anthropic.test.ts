/**
 * FR-061 — Anthropic adapter against a MOCKED transport. No API key exists in this
 * environment and none is needed: the whole suite runs on fixtures (Gate 1).
 */
import { describe, expect, it } from "vitest";
import { CapabilityNotSupportedError, ProviderError, SecretNotFoundError } from "@sunil/core";
import { AnthropicAdapter } from "../adapters/anthropic.js";
import {
  ANTHROPIC_MESSAGE_FIXTURE,
  ANTHROPIC_RATE_LIMIT_FIXTURE,
  ANTHROPIC_SERVER_ERROR_FIXTURE,
  ANTHROPIC_STREAM_SSE,
} from "../testing/fixtures.js";
import { MockTransport } from "../testing/mock-transport.js";
import { FakeSecretStore, SENTINEL_KEY } from "./support.js";

const CREDENTIAL = "llm:anthropic:api-key";

function adapterWith(transport: MockTransport, secrets = new FakeSecretStore({ [CREDENTIAL]: SENTINEL_KEY })) {
  return {
    adapter: new AnthropicAdapter({ transport: transport.fetch, secrets, credentialName: CREDENTIAL }),
    secrets,
  };
}

const request = {
  model: "claude-sonnet-4-5",
  messages: [
    { role: "system" as const, content: "You are terse." },
    { role: "user" as const, content: "Say hello." },
  ],
  feature: "unit-test",
  correlationId: "corr-anthropic-1",
};

describe("AnthropicAdapter.complete", () => {
  it("normalises a canned Anthropic-shaped response and populates token counts", async () => {
    const transport = new MockTransport([{ match: "/v1/messages", json: ANTHROPIC_MESSAGE_FIXTURE }]);
    const { adapter } = adapterWith(transport);

    const result = await adapter.complete(request);

    expect(result.provider).toBe("anthropic");
    expect(result.model).toBe("claude-sonnet-4-5");
    expect(result.content).toBe("Fixture completion from a mocked transport.");
    expect(result.stopReason).toBe("end_turn");
    expect(result.usage).toEqual({ tokensIn: 42, tokensOut: 17 });
    expect(result.latencyMs).toBeGreaterThanOrEqual(0);
  });

  it("hoists system messages into the top-level `system` parameter (contract note)", async () => {
    const transport = new MockTransport([{ match: "/v1/messages", json: ANTHROPIC_MESSAGE_FIXTURE }]);
    const { adapter } = adapterWith(transport);

    await adapter.complete(request);

    const body = transport.lastRequest()?.body as { system?: string; messages: { role: string }[] };
    expect(body.system).toBe("You are terse.");
    expect(body.messages.map((message) => message.role)).toEqual(["user"]);
  });

  it("takes its credential from the SecretStore at call time, not from env or a DB column", async () => {
    const transport = new MockTransport([{ match: "/v1/messages", json: ANTHROPIC_MESSAGE_FIXTURE }]);
    const { adapter, secrets } = adapterWith(transport);

    await adapter.complete(request);

    expect(secrets.reads).toEqual([CREDENTIAL]);
    // Round-trip integrity: the SDK received exactly the SecretStore value.
    expect(transport.lastRequest()?.headers["x-api-key"]).toBe(SENTINEL_KEY);
  });

  it("classifies an unresolvable credential as `auth` and never calls the provider", async () => {
    const transport = new MockTransport([{ match: "/v1/messages", json: ANTHROPIC_MESSAGE_FIXTURE }]);
    const { adapter } = adapterWith(transport, new FakeSecretStore({}));

    const error = (await adapter.complete(request).catch((caught: unknown) => caught)) as ProviderError;

    expect(error).toBeInstanceOf(ProviderError);
    expect(error.errorClass).toBe("auth");
    expect(error.retryable).toBe(false);
    expect(error.cause).toBeInstanceOf(SecretNotFoundError);
    // The message names the reference, never a value.
    expect(error.message).toContain(CREDENTIAL);
    expect(transport.requests).toHaveLength(0);
  });

  it("maps a rate-limit response to a typed retryable error carrying provider and status", async () => {
    const transport = new MockTransport([
      { match: "/v1/messages", status: 429, json: ANTHROPIC_RATE_LIMIT_FIXTURE },
    ]);
    const { adapter } = adapterWith(transport);

    const error = await adapter.complete(request).catch((caught: unknown) => caught);

    expect(error).toBeInstanceOf(ProviderError);
    const providerError = error as ProviderError;
    expect(providerError.provider).toBe("anthropic");
    expect(providerError.status).toBe(429);
    expect(providerError.errorClass).toBe("rate_limit");
    expect(providerError.retryable).toBe(true);
  });

  it("maps a 5xx to a retryable `server` error rather than a raw transport error", async () => {
    const transport = new MockTransport([
      { match: "/v1/messages", status: 503, json: ANTHROPIC_SERVER_ERROR_FIXTURE },
    ]);
    const { adapter } = adapterWith(transport);

    const error = (await adapter.complete(request).catch((caught: unknown) => caught)) as ProviderError;

    expect(error).toBeInstanceOf(ProviderError);
    expect(error.errorClass).toBe("server");
    expect(error.retryable).toBe(true);
    expect(error.name).not.toBe("APIError");
  });

  it("classifies a 401 as a non-retryable auth error", async () => {
    const transport = new MockTransport([{ match: "/v1/messages", status: 401, json: { error: {} } }]);
    const { adapter } = adapterWith(transport);

    const error = (await adapter.complete(request).catch((caught: unknown) => caught)) as ProviderError;
    expect(error.errorClass).toBe("auth");
    expect(error.retryable).toBe(false);
  });

  it("rejects a request that fails inbound Zod validation before any transport call", async () => {
    const transport = new MockTransport([{ match: "/v1/messages", json: ANTHROPIC_MESSAGE_FIXTURE }]);
    const { adapter } = adapterWith(transport);

    await expect(adapter.complete({ ...request, messages: [] } as never)).rejects.toMatchObject({
      code: "VALIDATION_FAILED",
      fields: ["messages"],
    });
    expect(transport.requests).toHaveLength(0);
  });
});

describe("AnthropicAdapter.stream", () => {
  it("parses real SSE bytes through the SDK and accumulates split token counts", async () => {
    const transport = new MockTransport([
      {
        match: "/v1/messages",
        body: ANTHROPIC_STREAM_SSE,
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
  });
});

describe("AnthropicAdapter capability gating (FR-060)", () => {
  it("declares streaming and vision but not embeddings", () => {
    const { adapter } = adapterWith(new MockTransport([]));
    expect(adapter.capabilities).toEqual({ streaming: true, embeddings: false, vision: true });
  });

  it("throws a typed CapabilityNotSupportedError when embed is invoked", async () => {
    const { adapter } = adapterWith(new MockTransport([]));
    await expect(
      adapter.embed({ model: "x", input: ["y"], feature: "f", correlationId: "c" }),
    ).rejects.toBeInstanceOf(CapabilityNotSupportedError);
  });
});
