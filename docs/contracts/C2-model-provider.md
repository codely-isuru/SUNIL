# C2 — Model Provider / Gateway Seam

**Version:** 1.0.0 · **Status:** FROZEN (Phase 0, 2026-09-10) · **Owner:** Solution Architect
**Consumers:** Stream B (LiteLLM gateway), core orchestrator (both LLM stages), Stream C (Mem0
embeddings ride the same seam), M2 rebuild (streaming leg).
**Informed by:** M1 reference `main:apps/api/sunil/core/routing/*`, `main:apps/api/sunil/providers/*`,
ADR-003 (SUNIL owns the abstraction), ADR-017 (settings-driven base URLs, canonical-or-loopback).
**Related decisions:** ADR-033 (gateway egress rule), ADR-028 (only the analysis call streams).

Change policy: additive optional request fields bump MINOR; changes to existing fields, the
protocol, or error kinds bump MAJOR with a new ADR.

---

## 1. Purpose

Keep **capability and privacy routing SUNIL-owned** (§33.1, §33.3, §26.10) while making the
transport a replaceable vendor. The Model Router maps `capability → model → provider` from
`config/models.yaml` and enforces privacy classes; the provider behind it is, by default, **one
adapter speaking the OpenAI-compatible API to LiteLLM**, with the M1-style direct adapters retained
as the documented fallback lane. Flipping gateway↔direct is a settings change (ADR-033), never a
router-policy change.

Funding/auth verified (memory lesson 2026-08-05, funding as a gating row): LiteLLM is self-hosted
MIT — no vendor account needed; the only billed dependencies remain the provider keys the owner
already holds (Anthropic/OpenAI), which move from app env into the LiteLLM container.

## 2. Interface definition

Types live in `apps/api/sunil/providers/base.py` (rebuilt); the router in `core/routing/router.py`.

```python
from collections.abc import AsyncIterator
from enum import StrEnum
from typing import Literal, Protocol

from pydantic import BaseModel


class PrivacyClass(StrEnum):
    PUBLIC = "public"
    INTERNAL = "internal"
    CONFIDENTIAL = "confidential"
    LOCAL_ONLY = "local_only"   # never leaves machines the owner controls (§26.10)


class ChatMessage(BaseModel):
    role: Literal["system", "user", "assistant", "tool"]
    content: str


class CompletionRequest(BaseModel):
    model: str                      # router-resolved model id (config/models.yaml), e.g. "claude-sonnet-4-5"
    messages: list[ChatMessage]
    max_tokens: int
    temperature: float = 0.2
    json_schema: dict | None = None # non-None ⇒ structured output REQUIRED (ROADMAP §25);
                                    # the plan stage always sets this, free-form never plans
    agent_id: str                   # selects the per-agent virtual key + budget (gateway lane)
    request_id: str                 # trace correlation, forwarded as metadata, never in prompt
    privacy_class: PrivacyClass


class Usage(BaseModel):
    input_tokens: int
    output_tokens: int
    cost_usd: float                 # from config/models.yaml pricing, computed SUNIL-side (M1 rule);
                                    # gateway-reported cost is recorded but never authoritative


class CompletionResult(BaseModel):
    text: str
    parsed: dict | None             # present iff json_schema was set and the output parsed
    usage: Usage
    provider_model: str             # what actually served it (gateway may alias)
    finish_reason: Literal["stop", "max_tokens", "refusal", "error"]


class StreamEvent(BaseModel):
    type: Literal["token", "done"]
    token: str | None = None            # type="token"
    result: CompletionResult | None = None  # type="done" — authoritative, tokens are a projection


class LLMProvider(Protocol):
    name: str

    async def complete(self, request: CompletionRequest) -> CompletionResult: ...
    def stream(self, request: CompletionRequest) -> AsyncIterator[StreamEvent]: ...
```

**Router stays SUNIL (normative):** `core/routing/router.py` resolves
`(capability, privacy_class) → (model, provider_name)` from `config/models.yaml`, enforcing:
`LOCAL_ONLY` resolves only to providers flagged `local: true` (none in Phase 0 — a `LOCAL_ONLY`
request with no local provider is a **routing error**, never a silent downgrade); the dev-lane
provider (`omniroute`, if configured) is eligible only for `PUBLIC`. These rules run **before**
provider selection, so no transport setting (including the ADR-033 kill switch) can widen the
population of workloads reaching a cloud provider — the exclusion is structural (memory lesson
2026-08-17: population scoping must not be an input the excluded population's decision reads).

## 3. The gateway adapter (default lane)

`providers/gateway.py::GatewayProvider` implements `LLMProvider` over LiteLLM's OpenAI-compatible
surface:

- `POST {SUNIL_LLM_GATEWAY_BASE_URL}/v1/chat/completions` (httpx, no SDK), `stream=true` for
  `stream()`, `response_format={"type":"json_schema", ...}` when `json_schema` is set.
- `Authorization: Bearer <virtual key>` where the key = settings `litellm_virtual_key_<agent_id>`
  if present else `litellm_virtual_key_default`. Keys are `SecretStr`, registered with the ADR-006
  redaction registry. Budgets/rate limits live on the keys inside LiteLLM, not in SUNIL.
- `SUNIL_LLM_GATEWAY_BASE_URL` is validated at `Settings` construction per **ADR-033**: loopback,
  or the literal Compose service host `litellm` — any other host refuses to boot (extends ADR-017's
  canonical-or-loopback rule to a gateway that has no public canonical host).
- Metadata: `extra_body={"metadata": {"request_id": ..., "agent_id": ...}}` so gateway logs and
  `llm_calls` rows correlate.

**Fallback lane (kill switch):** `SUNIL_LLM_PROVIDER_LANE=gateway|direct` (default `gateway`).
`direct` re-registers the M1-style `AnthropicProvider`/`OpenAIProvider` adapters (canonical-or-
loopback base URLs per ADR-017, keys from app env). The lane flag selects transport wiring at
startup only; it is not readable by the router (structural — see §2).

## 4. Error semantics

Adapters raise exactly one exception family; the orchestrator's retry policy (rebuilt from M1
`core/routing/retry.py`) branches on `kind`:

```python
class ProviderError(Exception):
    kind: Literal[
        "auth",            # 401/403 from gateway or provider — never retried, redacted message
        "rate_limit",      # 429 — retried with backoff up to policy budget
        "overloaded",      # 5xx/529 — retried
        "timeout",         # connect/read timeout — retried once
        "bad_request",     # 4xx incl. schema-invalid structured output request — not retried
        "invalid_output",  # json_schema set but output failed to parse/validate — ONE re-ask, then fail
        "budget_exceeded", # LiteLLM virtual-key budget exhausted — not retried; surfaces to owner
    ]
    retryable: bool
    provider_model: str | None
    usage: Usage | None    # tokens burned by failed attempts still count (M1 A-2 rule)
```

A turn that exhausts retries surfaces as C5 `failure.kind="provider_error"`. `invalid_output` on
the PLAN stage is a `plan_rejected` failure — free-form output never becomes a plan (§25).

## 5. FAKE specification — `FakeProvider` (QA-buildable, no questions)

Module: `apps/api/tests/fakes/fake_provider.py`. `name="fake"`. Deterministic, no I/O, no sleep
(except where scripted). Behaviour keys off the **last user message** content:

| Last user message contains | `complete()` returns | Notes |
|---|---|---|
| `PLAN:` | `parsed`/`text` = the fixed plan JSON below | simulates the plan stage; requires `json_schema is not None`, else raises `AssertionError("plan requested without schema")` |
| `FAIL:rate_limit` | raises `ProviderError(kind="rate_limit", retryable=True)` | every call — tests count retries |
| `FAIL:auth` | raises `ProviderError(kind="auth", retryable=False)` | |
| `FAIL:invalid_output` | when `json_schema` set: first call returns `text="{not json"` with `parsed=None`; a second call in the same process returns the fixed plan (exercises the one re-ask) | instance-level counter |
| anything else | `text = "FAKE: " + <last user message>`, `parsed=None` | echo lane |

Fixed plan JSON (exact value):

```json
{"intent": "fake_intent", "confidence": 0.9, "privacy_level": "internal",
 "objective": "fake objective", "agents": ["project_manager"],
 "steps": [{"id": "step_1", "action": "tool_call", "tool": "fake_tool",
            "operation": "write_item", "params": {"key": "demo", "value": "1"}}]}
```

Usage on every successful call: `input_tokens=100, output_tokens=25, cost_usd=0.000125`;
`provider_model="fake-1"`, `finish_reason="stop"`.

`stream()`: yields one `token` event per whitespace-separated word of what `complete()` would have
returned as `text` (tokens carry a trailing space except the last), then exactly one
`done` event whose `result` equals the `complete()` value byte-for-byte. `FAIL:*` markers raise
before the first event.

Contract tests (`apps/api/tests/contracts/test_c2_provider.py`), run against `FakeProvider` and
later against `GatewayProvider` pointed at a loopback double:

1. echo round-trip; usage arithmetic summed across attempts including failures.
2. `PLAN:` + schema → `parsed` validates against the plan schema.
3. `FAIL:invalid_output` → exactly one re-ask, then success.
4. `stream()` tokens concatenate to `done.result.text` exactly (projection property, ADR-027).
5. router: `LOCAL_ONLY` request with no local provider → routing error raised BEFORE any provider
   call (the fake records zero calls).
6. `Settings(sunil_llm_gateway_base_url="https://evil.example")` refuses to construct (ADR-033).
