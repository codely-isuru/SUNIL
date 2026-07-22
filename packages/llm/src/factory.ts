/**
 * The provider DI factory (§10.2, FR-065).
 *
 * `createProvider` constructs `REAL_FETCH_TRANSPORT` UNCONDITIONALLY. It takes no transport
 * parameter, reads no configuration that could select one, and imports nothing from
 * `./testing`. There is therefore no production configuration profile that can select a
 * mocked transport — which is the claim FR-065 makes and `factory.test.ts` proves.
 *
 * `createProviderWithTransport` exists for tests and refuses to run outside `NODE_ENV=test`.
 *
 * Usage recording is applied HERE, so no caller can obtain an unrecorded provider (§10.4).
 */
import { InvariantViolationError, ValidationError } from "@sunil/core";
import type { ProviderSlug, SecretStore } from "@sunil/core";
import { AnthropicAdapter } from "./adapters/anthropic.js";
import { OllamaAdapter } from "./adapters/ollama.js";
import { OpenAiAdapter } from "./adapters/openai.js";
import type { LLMProvider } from "./provider.js";
import { REAL_FETCH_TRANSPORT, type Transport } from "./transport.js";
import { withUsageRecording, type UsageRecorder } from "./usage.js";

/**
 * Provider selection is CONFIGURATION, passed in by the caller (FR-066): this package has no
 * routing rules, no failover and no default provider.
 */
export interface ProviderConfig {
  readonly slug: ProviderSlug;
  /** `LlmProvider.baseUrl`. Required for Ollama, optional override for the hosted providers. */
  readonly baseUrl?: string | null;
  /** `LlmProvider.credentialName` — a SecretStore reference, never a credential value. */
  readonly credentialName?: string | null;
}

export interface ProviderDeps {
  readonly secrets: SecretStore;
  readonly usage: UsageRecorder;
}

function build(config: ProviderConfig, deps: ProviderDeps, transport: Transport): LLMProvider {
  switch (config.slug) {
    case "anthropic":
      return withUsageRecording(
        new AnthropicAdapter({
          transport,
          secrets: deps.secrets,
          credentialName: requireCredentialName(config),
          baseUrl: config.baseUrl ?? null,
        }),
        deps.usage,
      );
    case "openai":
      return withUsageRecording(
        new OpenAiAdapter({
          transport,
          secrets: deps.secrets,
          credentialName: requireCredentialName(config),
          baseUrl: config.baseUrl ?? null,
        }),
        deps.usage,
      );
    case "ollama":
      return withUsageRecording(
        new OllamaAdapter({ transport, baseUrl: config.baseUrl ?? null }),
        deps.usage,
      );
  }
}

/** The ONLY production constructor. Real `fetch`, always. */
export function createProvider(config: ProviderConfig, deps: ProviderDeps): LLMProvider {
  return build(config, deps, REAL_FETCH_TRANSPORT);
}

/**
 * Test-only constructor. Guarded at runtime as well as by convention: outside `NODE_ENV=test`
 * this throws rather than returning a provider wired to an injected transport.
 */
export function createProviderWithTransport(
  config: ProviderConfig,
  deps: ProviderDeps,
  transport: Transport,
): LLMProvider {
  if (process.env["NODE_ENV"] !== "test") {
    throw new InvariantViolationError(
      "an injected LLM transport is only permitted under NODE_ENV=test (FR-065)",
    );
  }
  return build(config, deps, transport);
}

function requireCredentialName(config: ProviderConfig): string {
  if (!config.credentialName) {
    throw new ValidationError(
      `provider '${config.slug}' has no credentialName; a SecretStore reference is required`,
      ["credentialName"],
    );
  }
  return config.credentialName;
}
