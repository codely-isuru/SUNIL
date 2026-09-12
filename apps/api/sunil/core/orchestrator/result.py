"""`TurnResult` — what a turn hands back, in `core`'s own vocabulary.

The C5 envelope models live in `sunil/api/schemas.py`, and **`core/` never
imports `sunil.api`** (ARCHITECTURE_V2 §2's import law, enforced by
`tests/unit/test_import_law.py`). So the orchestrator returns this plain-data
result and `sunil/api/envelope.py` maps it onto the wire shape — one mapping
function, in the layer that owns the contract.

That is not ceremony: it is what keeps a wire-format change (a new envelope
field, a renamed key) from reaching into the orchestrator, and what lets
`tests/fakes/stub_turn_executor.py` satisfy the same seam without the route
caring which side produced the outcome.

The fields mirror the envelope one-for-one, including the **exactly-one rule**
(`ok`→message, `failed`→failure, `parked`→approval): it is re-checked at
construction here AND enforced by `ChatResponse` at serialisation, so neither
layer can quietly emit a half-built turn.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

TurnOutcome = Literal["ok", "failed", "parked"]


@dataclass(frozen=True)
class TurnMessage:
    id: str
    content: str
    created_at: str


@dataclass(frozen=True)
class TurnTask:
    id: str
    status: str
    assigned_agent: str


@dataclass(frozen=True)
class TurnApproval:
    approval_id: str
    expires_at: str
    summary: str


@dataclass(frozen=True)
class TurnFailure:
    kind: str
    known_projects: tuple[tuple[str, str], ...] | None = None  # (key, display_name)


@dataclass(frozen=True)
class TurnTraceEntry:
    stage: str
    offset_ms: int
    detail: dict[str, Any] | None


@dataclass(frozen=True)
class TurnUsage:
    input_tokens: int
    output_tokens: int
    cost_usd: float


@dataclass(frozen=True)
class TurnResult:
    request_id: str
    conversation_id: str
    outcome: TurnOutcome
    usage: TurnUsage
    message: TurnMessage | None = None
    task: TurnTask | None = None
    failure: TurnFailure | None = None
    approval: TurnApproval | None = None
    trace: tuple[TurnTraceEntry, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        expected = {"ok": self.message, "failed": self.failure, "parked": self.approval}
        if expected[self.outcome] is None:
            raise ValueError(
                f"outcome={self.outcome!r} was built without its payload — C5's "
                "exactly-one rule holds in core as well as on the wire"
            )
        others = [
            value
            for name, value in (
                ("message", self.message),
                ("failure", self.failure),
                ("approval", self.approval),
            )
            if value is not None and value is not expected[self.outcome]
        ]
        if others:
            raise ValueError(
                f"outcome={self.outcome!r} carries more than one payload (C5's "
                "exactly-one rule)"
            )
