"""The C5 envelope — `docs/contracts/C5-chat-openapi.yaml`, transcribed.

One module owns the wire shape of `POST /api/v1/chat`, because three streams
render it (D's parked outcome, E's n8n triggers, `apps/web`) and a second
definition would be a second contract.

Two rules live here rather than in the route, so no caller can forget them:

* **The exactly-one rule** (C5 OpenAPI `ChatResponse.description`): `ok` sets
  `message`, `failed` sets `failure`, `parked` sets `approval`, and the other two
  are `null`. `ChatResponse.model_validator` enforces it — the OpenAPI says
  "enforced by the response builder, not the schema", and this *is* that builder's
  enforcement point, so a half-built envelope cannot be serialised at all.
* **`trace[].detail` carries enums and numbers only** — never prose, never LLM
  output (C5 §1, M1's rule). `TraceEntryOut` rejects a string value that is not a
  short enum-like token, which makes "someone pasted the model's answer into a
  trace detail" a test failure rather than a leak.

`input_modality="voice"` is a 422 here, not a 501 later: ADR-020 makes the field
a seam whose *presence* is not a breaking change, and the server verifies voice
against a bound transcription that does not exist until the voice milestone
lands on V2. A client cannot label typed text as speech.
"""

from __future__ import annotations

import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

#: C5 OpenAPI `ChatFailure.kind`. The last three are approval terminals that
#: arrive on a CONTINUATION's record, never on a live turn's envelope (C5 §2.4).
FailureKind = Literal[
    "provider_error",
    "tool_failed",
    "plan_rejected",
    "unknown_project",
    "approval_refused",
    "approval_expired",
    "continuation_interrupted",
]

Outcome = Literal["ok", "failed", "parked"]

#: What a `trace[].detail` VALUE may look like when it is a string: an enum-ish
#: token, not prose. Numbers and booleans are unconditionally fine.
_ENUMISH = re.compile(r"^[A-Za-z0-9_.:-]{1,64}$")


class ChatRequest(BaseModel):
    """C5 OpenAPI `ChatRequest`. `additionalProperties: false` is `extra="forbid"`:
    an unknown body key is a 422 before any turn machinery runs (M1's rule)."""

    model_config = ConfigDict(extra="forbid")

    message: str = Field(min_length=1, max_length=8000)
    conversation_id: str | None = None
    input_modality: Literal["text", "voice"] = "text"
    channel_label: str | None = Field(default=None, max_length=64)

    @field_validator("input_modality")
    @classmethod
    def _voice_is_unverifiable(cls, value: str) -> str:
        if value == "voice":
            raise ValueError(
                "input_modality='voice' requires a server-verified speech binding "
                "(ADR-020); the voice milestone is not yet rebuilt on V2, so this "
                "is always 422 — clients cannot label typed text as speech"
            )
        return value


class MessageOut(BaseModel):
    id: str
    role: Literal["assistant"] = "assistant"
    content: str
    created_at: str


class ChatTaskOut(BaseModel):
    id: str
    status: str
    assigned_agent: str


class ProjectSummary(BaseModel):
    key: str
    display_name: str


class ChatFailure(BaseModel):
    kind: FailureKind
    #: Populated only for `kind="unknown_project"` — the owner is told what IS
    #: configured rather than only that they were wrong.
    known_projects: list[ProjectSummary] | None = None


class ApprovalRef(BaseModel):
    """Present exactly when `outcome="parked"`; links to the C4 approval.

    `summary` is built by SUNIL code but embeds attacker-influenceable values
    (repo names, issue titles) — render as PLAIN TEXT ONLY (C4 §4).
    """

    approval_id: str
    expires_at: str
    summary: str = Field(max_length=500)


class TraceEntryOut(BaseModel):
    stage: str
    offset_ms: int
    detail: dict[str, Any] | None = None

    @field_validator("detail")
    @classmethod
    def _enums_and_numbers_only(cls, value: dict[str, Any] | None) -> dict[str, Any] | None:
        """C5 §1 / M1's rule. Prose in a trace detail is how model output reaches
        a surface that is rendered and grepped, so it is refused here."""
        if value is None:
            return value
        for key, item in value.items():
            _check_detail_value(key, item)
        return value


def _check_detail_value(key: str, item: Any) -> None:
    if isinstance(item, bool) or isinstance(item, (int, float)) or item is None:
        return
    if isinstance(item, str):
        if not _ENUMISH.match(item):
            raise ValueError(
                f"trace detail {key!r} must carry enums and numbers only — "
                "never prose and never LLM output (C5 §1)"
            )
        return
    if isinstance(item, (list, tuple)):
        for element in item:
            _check_detail_value(key, element)
        return
    if isinstance(item, dict):
        for nested_key, nested in item.items():
            _check_detail_value(f"{key}.{nested_key}", nested)
        return
    raise ValueError(f"trace detail {key!r} has unsupported type {type(item).__name__}")


class ChatUsage(BaseModel):
    """Summed across every provider attempt, INCLUDING failed ones (M1's A-2
    rule) — which is why the turn tallies from the same records `llm_calls`
    stores rather than from the last successful call."""

    input_tokens: int
    output_tokens: int
    cost_usd: float


class ChatResponse(BaseModel):
    """C5 OpenAPI `ChatResponse`, with the exactly-one rule enforced."""

    request_id: str
    conversation_id: str
    outcome: Outcome
    message: MessageOut | None = None
    task: ChatTaskOut | None = None
    failure: ChatFailure | None = None
    approval: ApprovalRef | None = None
    trace: list[TraceEntryOut] = Field(default_factory=list)
    usage: ChatUsage

    @model_validator(mode="after")
    def _exactly_one_outcome_payload(self) -> ChatResponse:
        expected = {"ok": "message", "failed": "failure", "parked": "approval"}[self.outcome]
        present = {
            "message": self.message,
            "failure": self.failure,
            "approval": self.approval,
        }
        if present[expected] is None:
            raise ValueError(f"outcome={self.outcome!r} requires {expected!r} to be set")
        for name, value in present.items():
            if name != expected and value is not None:
                raise ValueError(
                    f"outcome={self.outcome!r} requires {name!r} to be null "
                    "(C5's exactly-one rule)"
                )
        return self


# --------------------------------------------------------------------------- #
# NDJSON frames (ADR-027). The `done` frame is authoritative; tokens are a
# projection, so a dropped token frame cannot corrupt the answer.
# --------------------------------------------------------------------------- #
class StageFrame(BaseModel):
    type: Literal["stage"] = "stage"
    stage: str
    offset_ms: int


class TokenFrame(BaseModel):
    type: Literal["token"] = "token"
    token: str


class HeartbeatFrame(BaseModel):
    type: Literal["heartbeat"] = "heartbeat"
    offset_ms: int


class DoneFrame(BaseModel):
    type: Literal["done"] = "done"
    envelope: ChatResponse


# --------------------------------------------------------------------------- #
# C5 §3's error bodies
# --------------------------------------------------------------------------- #
ErrorKind = Literal["unauthenticated", "forbidden_client", "not_found", "validation_error"]


class ErrorBody(BaseModel):
    kind: ErrorKind
    message: str


class ErrorResponse(BaseModel):
    error: ErrorBody


def error_payload(kind: ErrorKind, message: str) -> dict[str, Any]:
    """The 401/403/404/422 body, built in one place.

    `message` is a fixed string chosen by the handler — never an echo of the
    request, and never a credential (C5 §3: an invalid bearer is exactly the
    value most worth not logging, and equally worth not reflecting).
    """
    return ErrorResponse(error=ErrorBody(kind=kind, message=message)).model_dump()
