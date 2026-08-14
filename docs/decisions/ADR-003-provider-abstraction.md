# ADR-003 — SUNIL owns the provider abstraction: a `LLMProvider` protocol behind a capability-keyed Model Router

**Status:** Proposed (Gate 2) · **Date:** 2026-08-14 · **Decider:** Solution Architect
**Context refs:** `ROADMAP.md` §5, §33 rule 1, `docs/ARCHITECTURE_V1.md` §4, FR-040/041/042/045/046/047,
NFR-010.

## Context

`ROADMAP.md` §33.1 states the product thesis: *SUNIL is the product; models are replaceable
resources.* §5 forbids `claude.send(prompt)` and prescribes
`model_router.run(task=…, capability=…, privacy_level=…, cost_priority=…)`. FR-040's own acceptance
criterion is that **no file outside the provider module references a vendor SDK**.

The abstraction can either be written (about 200 lines) or adopted from a framework.

## Decision

SUNIL defines its own two-layer abstraction:

1. **`sunil/providers/base.py`** — a `Protocol` with `capabilities(model)` and
   `generate(model, LLMRequest) -> LLMResponse`, plus SUNIL-owned request/response dataclasses and a
   SUNIL-owned error hierarchy (`ProviderTransientError` / `ProviderPermanentError` /
   `StructuredOutputError`). Vendor exceptions are normalised **at the provider boundary**, so retry
   policy never imports a vendor type.
2. **`sunil/core/routing/router.py`** — `ModelRouter.run(capability=…, request=…, purpose=…, ctx=…,
   privacy_level=…, cost_priority=…)`. Callers name a capability, never a vendor or a model.
   Selection in M1 is a lookup in `config/models.yaml`; retry, per-attempt `llm_calls` persistence
   and cost computation live here.

`privacy_level` and `cost_priority` are accepted and recorded but **not used for selection in M1**
(NFR-010) — the signature exists now so V2's LOCAL-ONLY enforcement is additive.

Adding a provider is: implement the protocol, add one line to `providers/registry.py`, add models and
pricing to `config/models.yaml`, point a capability at it. **Zero changes to orchestrator, agents or
tools** — asserted by a test that runs a full turn against a fake provider.

## Rejected alternatives

| Rejected | Why |
|---|---|
| **LiteLLM** | Genuinely solves multi-provider routing and would save perhaps 150 lines. But it is a large, fast-moving dependency whose own abstraction would become SUNIL's, contradicting §33.1, and its structured-output handling would sit between us and the `output_config` guarantee that ET-7 depends on. Note: a *future* provider adapter may be implemented on top of LiteLLM **behind** this protocol — that is precisely what the protocol is for. |
| **LangChain / LlamaIndex** | Brings an entire agent, memory and tool framework that duplicates and conflicts with §7, §8, §10 and §11 — the parts of SUNIL that are the actual product. Adopting it would make SUNIL a thin wrapper over someone else's opinions, which is the inverse of the roadmap's thesis. Also a very large surface to debug three days from a deadline. |
| **The Anthropic SDK directly, wrapped later** | Fails FR-040 outright, and "we'll abstract it later" never survives contact with a second provider. |
| **One provider class with `if provider == …` branches** | Every new provider edits shared code — the exact coupling FR-042 forbids. |
| **OpenAI-compatible shim for everything** | Attractive uniformity, but it would erase Anthropic's `output_config` constrained decoding, which is the foundation of the plan-validation design (ADR-004). Losing the strongest control to gain interface symmetry is a bad trade. |

## Consequences

- ~200 lines of SUNIL-owned code to maintain, and each new provider's quirks are ours to normalise.
- One lint rule + one test enforce "only `sunil/providers/` may import a vendor SDK". Without them
  this decision decays silently.
- Because SUNIL owns retry (`max_retries=0` on the SDK client), each attempt is individually
  persisted — which is how FR-045's "retry count is visible" becomes data rather than a log string.
