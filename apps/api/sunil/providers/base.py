"""C2 — Model Provider / Gateway seam (frozen contract transcription).

Source of truth: ``docs/contracts/C2-model-provider.md`` **v1.0.1** (FROZEN, Phase 0
2026-09-10) §2 "Interface definition" and §4 "Error semantics". The router that
sits in front of this seam is ``core/routing/router.py`` and stays SUNIL-owned
(C2 §2); the gateway adapter is ``providers/gateway.py`` (C2 §3).

Zero business logic lives here: protocols, models and the one exception family.

**Frozen security property — ``CompletionRequest`` has no ``tools`` field.**
The seam carries no provider-native tool-calling channel, because the only path
from model output to a privileged action is a validated plan step through the C1
chokepoint (ROADMAP §25 / §33.5, C1 §3). Adding ``tools``/``tool_choice`` here
would create a second path and is a MAJOR contract change requiring a new ADR —
it is not an oversight to be "fixed" by an implementer.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from enum import StrEnum
from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict


class PrivacyClass(StrEnum):
    """C2 §2."""

    PUBLIC = "public"
    INTERNAL = "internal"
    CONFIDENTIAL = "confidential"
    LOCAL_ONLY = "local_only"  # never leaves machines the owner controls (§26.10)


class _ClosedModel(BaseModel):
    """Every C2 request/result model is CLOSED (v1.0.1, backend review F11): an
    undeclared field raises ``ValidationError`` at the call site instead of being
    silently dropped (pydantic's default ``extra="ignore"``).

    The property is the contract — C2 §2 makes ``extra="forbid"`` normative for
    all five §2 models — and this shared base is the recommended mechanism, so a
    model added to this module later cannot forget it by accident. It is what
    keeps the frozen no-tools shape from eroding quietly: ``CompletionRequest(
    ..., tools=[...])`` and ``ChatMessage(..., tool_calls=[...])`` are now loud
    errors rather than silently discarded arguments.
    """

    model_config = ConfigDict(extra="forbid")


class ChatMessage(_ClosedModel):
    role: Literal["system", "user", "assistant", "tool"]
    content: str


class CompletionRequest(_ClosedModel):
    model: str  # router-resolved model id (config/models.yaml), e.g. "claude-sonnet" — see the namespace rule below
    messages: list[ChatMessage]
    max_tokens: int
    temperature: float = 0.2
    json_schema: dict | None = None  # non-None ⇒ structured output REQUIRED (ROADMAP §25);
    # the plan stage always sets this, free-form never plans
    agent_id: str  # selects the per-agent virtual key + budget (gateway lane)
    request_id: str  # trace correlation, forwarded as metadata, never in prompt
    privacy_class: PrivacyClass


class Usage(_ClosedModel):
    input_tokens: int
    output_tokens: int
    cost_usd: float  # from config/models.yaml pricing, computed SUNIL-side (M1 rule);
    # gateway-reported cost is recorded but never authoritative


class CompletionResult(_ClosedModel):
    text: str
    parsed: dict | None  # non-None iff json_schema was set (parse failure RAISES
    # ProviderError(kind="invalid_output"), never a silent None — §4)
    usage: Usage
    provider_model: str  # what actually served it (gateway may alias)
    finish_reason: Literal["stop", "max_tokens", "refusal", "error"]


class StreamEvent(_ClosedModel):
    type: Literal["token", "done"]
    token: str | None = None  # type="token"
    result: CompletionResult | None = None  # type="done" — authoritative, tokens are a projection


class LLMProvider(Protocol):
    name: str

    async def complete(self, request: CompletionRequest) -> CompletionResult: ...

    def stream(self, request: CompletionRequest) -> AsyncIterator[StreamEvent]: ...


#: C2 §2 — the frozen Phase 0 gateway alias namespace. ``config/models.yaml`` ids
#: MUST equal LiteLLM's ``model_name`` alias set verbatim; upstream ids such as
#: ``anthropic/claude-sonnet-4-5`` appear only inside the gateway's own config and
#: in ``CompletionResult.provider_model`` as reported facts.
GATEWAY_MODEL_ALIASES = (
    "claude-sonnet",
    "claude-opus",
    "claude-haiku",
    "gpt-flagship",
    "gpt-mini",
)


class ProviderError(Exception):
    """C2 §4 — the single exception family; the orchestrator's retry policy
    branches on ``kind``.

    The contract declares the attribute set and their types; the constructor is
    keyword-only so no call site can positionally confuse ``kind`` with
    ``provider_model``. ``retryable=True`` marks eligibility only — the SUNIL
    retry policy, not the flag, caps the count (C2 §4, retry ownership).
    """

    kind: Literal[
        "auth",  # 401/403 from gateway or provider — never retried, redacted message
        "rate_limit",  # 429 — retried with backoff up to policy budget
        "overloaded",  # 5xx/529 — retried
        "timeout",  # connect/read timeout — retried once
        "bad_request",  # 4xx incl. schema-invalid structured output request — not retried
        "invalid_output",  # json_schema set but output failed to parse/validate — ONE re-ask, then fail
        "budget_exceeded",  # LiteLLM virtual-key budget exhausted — not retried; surfaces to owner
    ]
    retryable: bool
    provider_model: str | None
    usage: Usage | None  # tokens burned by failed attempts still count (M1 A-2 rule)

    def __init__(
        self,
        *,
        kind: Literal[
            "auth",
            "rate_limit",
            "overloaded",
            "timeout",
            "bad_request",
            "invalid_output",
            "budget_exceeded",
        ],
        retryable: bool,
        provider_model: str | None = None,
        usage: Usage | None = None,
        message: str | None = None,
    ) -> None:
        super().__init__(message if message is not None else kind)
        self.kind = kind
        self.retryable = retryable
        self.provider_model = provider_model
        self.usage = usage


class GatewayModelParityError(Exception):
    """C2 §3 — raised by ``GatewayProvider.start()`` when a ``config/models.yaml``
    id is absent from the gateway's ``/v1/models`` alias set. A drifted alias
    namespace is a boot failure, never a runtime 400."""
