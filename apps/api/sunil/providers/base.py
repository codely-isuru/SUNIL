"""The provider abstraction SUNIL owns (ADR-003, `ARCHITECTURE_V1.md` §4.2).

`sunil/providers/` is the **only** package permitted to import a vendor
SDK (FR-040's own acceptance criterion — checked by T19's AST-walking
import-boundary test and run on every merge by T21). Everything above this
layer — the Model Router (`core/routing`), agents, tools — depends only on
`LLMProvider`, `LLMRequest`/`LLMResponse` and the exception hierarchy
below, never on a vendor type. That is what §33 rule 1 means by "models
are replaceable resources; SUNIL is the product", and it is provable by a
test that swaps in a fake provider and runs a full turn without touching
`core/orchestrator`, `core/agent_framework`, `agents/*` or `tools/*`
(ADR-003).
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum
from typing import Literal, Protocol


class LLMPurpose(StrEnum):
    """The logical reason for a call — not a provider attempt (A-2). M1
    writes `llm_calls` rows with `purpose` in `{PLAN, ANALYSIS}` only;
    `FINAL_RESPONSE` is defined and appears in the DB check constraint but
    **no M1 code path uses it** (ADR-015 — the analysis call already
    produces the user-facing prose)."""

    PLAN = "plan"
    ANALYSIS = "analysis"
    FINAL_RESPONSE = "final_response"


@dataclass(frozen=True)
class ChatTurn:
    role: Literal["user", "assistant"]
    content: str


@dataclass(frozen=True)
class LLMRequest:
    system: str
    messages: list[ChatTurn]
    max_tokens: int
    # None -> free text; set -> structured output demanded via the
    # verified `output_config={"format": {"type": "json_schema", ...}}`
    # surface (§4.3). A conformant response is enforced by constrained
    # decoding — the provider's own guarantee (§6.1 Layer 2).
    json_schema: dict | None = None
    temperature: float | None = None
    # Passed through verbatim when set (§4.4). M1 never sets it — Opus 5
    # and Sonnet 5 both default to `effort: high` on the Claude API.
    effort: str | None = None
    stop_sequences: list[str] | None = None


@dataclass(frozen=True)
class LLMResponse:
    text: str | None  # None when json_schema was requested
    data: dict | None  # populated ONLY on a schema-conformant parse
    provider: str
    model: str
    input_tokens: int
    output_tokens: int
    stop_reason: str | None
    provider_request_id: str | None
    latency_ms: int


@dataclass(frozen=True)
class ModelCapabilities:
    context_window: int
    max_output: int
    supports_structured_output: bool
    input_usd_per_mtok: Decimal
    output_usd_per_mtok: Decimal


class LLMProvider(Protocol):
    name: str

    def capabilities(self, model: str) -> ModelCapabilities: ...

    async def generate(
        self, model: str, request: LLMRequest, *, timeout_s: float | None = None
    ) -> LLMResponse:
        """`timeout_s` is the **per-call** timeout for this one attempt
        (`ARCHITECTURE_V1.md` §9.5 TB2: "Per-call timeout from
        `config/models.yaml`"), supplied by the Model Router from the
        resolved capability's `timeout_s` — never a client-level default,
        because a capability's own budget can differ from another's on the
        same shared, once-at-startup client (§3.2)."""
        ...


# -- SUNIL's own error hierarchy --------------------------------------------
#
# Vendor exceptions are normalised to these **at the provider boundary**
# (ADR-003) — retry policy (`core/routing/router.py`) never imports or
# catches a vendor exception type, so swapping the vendor never touches
# the retry logic.
#
# `input_tokens`/`output_tokens`/`provider_request_id` are carried on the
# exception when the provider actually received a response before failing
# (e.g. a schema-conformance failure after the model generated real
# output) — a failed attempt that consumed tokens still costs money and
# still belongs in the `llm_calls` row for that attempt (§13.1). They stay
# `None` when the provider never got a response at all (a connection
# failure, a timeout) — there is nothing to bill.


class ProviderError(Exception):
    """Base of SUNIL's own provider-error hierarchy."""

    def __init__(
        self,
        message: str,
        *,
        input_tokens: int | None = None,
        output_tokens: int | None = None,
        provider_request_id: str | None = None,
    ) -> None:
        super().__init__(message)
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens
        self.provider_request_id = provider_request_id


class ProviderTransientError(ProviderError):
    """Retryable (§4.5): connection failure, timeout, rate limit, 5xx."""


class ProviderPermanentError(ProviderError):
    """Not retryable: a 4xx that will not succeed on replay."""


class StructuredOutputError(ProviderPermanentError):
    """A `json_schema` request did not come back as a schema-conformant
    parse. Layer 2 of the plan-validation chain (`ARCHITECTURE_V1.md`
    §6.1): this method never returns half-parsed data, never falls back to
    regex, never strips markdown fences and retries."""


class UnknownProviderError(ProviderError):
    """A capability names a provider that nobody registered
    (`providers/registry.py`) — fails closed, never a bare `KeyError`."""

    def __init__(self, provider_name: str) -> None:
        self.provider_name = provider_name
        super().__init__(f"no provider registered with name {provider_name!r}")
