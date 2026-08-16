"""Request/response Pydantic models for the API's HTTP surface.

These shapes are the frozen §6 contract for the endpoints T5 owns
(`auth.py`, `health.py`); T11a adds the chat envelope's schemas in this
same file when it lands. Field names here are load-bearing — the frontend
and QA are building against them before the backend exists
(`docs/M1_BUILD_PLAN.md` §6).
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class LoginRequest(BaseModel):
    username: str
    password: str


class UserPublic(BaseModel):
    """`{id, name}` — never the password hash, never anything else from
    the `users` row."""

    id: str
    name: str


class LoginResponse(BaseModel):
    user: UserPublic


class SessionResponse(BaseModel):
    authenticated: bool
    user: UserPublic | None = None


class HealthResponse(BaseModel):
    status: str
    revision: str


# ---------------------------------------------------------------------------
# T11a — the chat envelope (`docs/M1_BUILD_PLAN.md` §6, the frozen contract).
# ---------------------------------------------------------------------------


class ChatRequest(BaseModel):
    """`POST /api/v1/chat` body. `message` is `string(1..8000)` per §6 —
    enforced here so an out-of-range body is a 422 before any turn
    machinery runs, not a defect discovered mid-turn."""

    message: str = Field(min_length=1, max_length=8000)
    conversation_id: str | None = None


class MessageOut(BaseModel):
    """`{id, role:"assistant", content, created_at}` — always the
    assistant's role in this envelope; the user's own message is
    persisted but never echoed back in the response (§6)."""

    id: str
    role: Literal["assistant"]
    content: str
    created_at: str


class ChatTaskOut(BaseModel):
    """`{id, status, assigned_agent}` — `status` is FR-065's lifecycle
    value at the moment the response is built, never `cancelled`
    (ADR-010 — M1 has no such state)."""

    id: str
    status: str
    assigned_agent: str


class KnownProjectOut(BaseModel):
    """`{key, display_name}` — byte-identical shape to `GET
    /api/v1/projects`'s own elements (§11.5 A-14), so the frontend has
    one type for both producers."""

    key: str
    display_name: str


class ChatFailure(BaseModel):
    """`{kind, known_projects?}` — `kind` is restricted to the four
    documented values (§6); `known_projects` is populated only for
    `unknown_project` and is `None` for the other three kinds."""

    kind: Literal["provider_error", "tool_failed", "plan_rejected", "unknown_project"]
    known_projects: list[KnownProjectOut] | None = None


class TraceEntryOut(BaseModel):
    """`{stage, offset_ms, detail}` — one of `trace[]`'s twelve entries.
    `detail`'s keys are the `ARCHITECTURE_V1.md` §3.4 contract, but this
    schema keeps it an open object rather than modelling every key: the
    client already degrades to a generic label when one is absent, and a
    strict schema here would break the moment a new key is added."""

    stage: str
    offset_ms: int
    detail: dict[str, object] | None = None


class ChatUsage(BaseModel):
    """`{input_tokens, output_tokens, cost_usd}` — summed across **every
    provider attempt** in the turn, including failed ones that consumed
    input tokens (§6; A-2's "provider attempts, not logical stages")."""

    input_tokens: int
    output_tokens: int
    cost_usd: float


class ChatResponse(BaseModel):
    """The full §6 envelope. `message`/`task` are `None` on a failed
    turn; `failure` is `None` on a successful one — the two are always
    opposite, never both populated and never both absent, but that
    invariant is enforced by whoever builds the response (T11b's
    `turn.py`), not by this schema, which only describes the wire shape.
    """

    request_id: str
    conversation_id: str
    outcome: Literal["ok", "failed"]
    message: MessageOut | None
    task: ChatTaskOut | None
    failure: ChatFailure | None
    trace: list[TraceEntryOut]
    usage: ChatUsage
