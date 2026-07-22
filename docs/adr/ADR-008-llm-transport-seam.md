# ADR-008 — LLM transport seam: official SDKs with injected fetch

_Status: Accepted · Owner: Solution Architect · Phase: 1_

## Context

FR-060–FR-065: one `LLMProvider` interface with Anthropic, OpenAI and Ollama adapters,
verifiable **without any API keys** (none exist in this environment — Gate 1), with a mocked
transport confined to test/dev and adapters labelled "unverified against live endpoints".
Risk R-01 warns the real danger is contract drift: auth header shapes, streaming framing,
token-count field names, error taxonomies — the things that only surface against live
endpoints.

## Decision

The injectable seam is **the `fetch` function** (`Transport = typeof fetch`):

- **Anthropic and OpenAI adapters wrap the official SDKs** (`@anthropic-ai/sdk`, `openai`),
  constructed with an injected `fetch`. The SDKs encode the provider contracts (auth
  headers, SSE framing, field names, error classes) that R-01 identifies as the failure
  mode — using them *minimises* the unverifiable surface to our normalisation layer.
- **Ollama uses plain `fetch`** against its REST API through the same `Transport` type (no
  official SDK worth pinning; the API is small and local).
- **`MockTransport`** returns fixture `Response` objects captured from published provider
  response shapes (success, rate-limit, 5xx, streaming chunks). It lives in
  `packages/llm/testing`, is imported only by tests/dev fixtures, and the production DI
  factory constructs real-`fetch` adapters unconditionally — a unit test asserts no
  production configuration can select the mock (FR-065).
- Adapters normalise to our Zod-validated shapes and typed `ProviderError` taxonomy;
  credentials arrive per call via `SecretStore` (`SecretValue.use`), never from env/DB reads
  inside the adapter.
- Labelling: adapters export `verification: 'mock-verified'`; `LlmProvider.verificationStatus`
  cannot reach `LIVE_VERIFIED` through any Phase 1 code path; portal renders "unverified
  against live endpoints" (Gate 1 wording).

## Rejected alternatives

- **Hand-rolled HTTP clients for Anthropic/OpenAI.** Re-derives every contract detail from
  docs with no way to verify — maximises exactly the R-01 risk the seam exists to reduce.
  Rejected despite being the "purer" seam.
- **Vercel AI SDK as the abstraction.** Attractive breadth, but it inserts its own provider
  model and routing opinions above ours; Phase 2's router must be driven by *our* database
  routing rules (ARCHITECTURE §2.4), and the AI SDK would hide the usage/cost extraction
  points FR-064 needs per call. Also a large surface for the supply-chain budget.
- **Mock at the adapter interface instead of the transport** (fake `LLMProvider` in tests).
  Necessary for *consumer* tests, insufficient for *adapter* tests — it would leave adapter
  request-building and response-parsing entirely unexercised, i.e. the adapters would be
  untested code shipped as "mock-verified". Both levels exist; the transport seam is what
  makes the adapter level honest.
- **nock/msw-style network interception.** Patches the runtime instead of using an explicit
  seam; interception libraries chase Node fetch internals across versions. An injected
  function is dependency-free and obvious.

## Consequences

- Live verification in Phase 2 is a configuration change (real keys + real fetch + a smoke
  script diffing fixtures against live responses), not a rewrite — the fixtures become the
  contract-drift detector.
- We accept the official SDKs into the dependency budget (pinned exact; script-blocked
  install per ADR-007).
- Streaming fixtures must be captured as SSE byte streams, not parsed JSON, so the SDK's
  framing code is actually exercised — noted for BL-602.
