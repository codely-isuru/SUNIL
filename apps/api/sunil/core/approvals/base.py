"""C4 — Approvals: the in-process seam types (frozen contract transcription).

Source of truth: ``docs/contracts/C4-approvals.md`` v1.0.0 (FROZEN, Phase 0
2026-09-10) §4 "In-process seam (injected into the Tool Manager — C1 §2.2)", plus
``docs/contracts/C4-approvals-openapi.yaml`` for the persisted ``Approval`` shape
and the ``ApprovalStatus`` enum.

Zero business logic lives here: protocols, models and enums only. The park /
consume / decide implementation is Stream D's ``core/approvals/service.py``
(ARCHITECTURE_V2 §2); the QA fake is ``tests/fakes/fake_approvals.py`` (C4 §6).

Ownership reminder (C4 §1 + ADR-031 Amendment 1): both protocol methods have
exactly one caller — the Tool Manager (C1 §2.1 step 3). The continuation
executor never issues the consume CAS itself.

Module-path note: C4 names no module for these types, and ARCHITECTURE_V2 §2
lists only ``service.py``/``sweeper.py``/``notify.py`` under ``core/approvals/``.
``base.py`` is chosen for consistency with C1 (``core/tool_framework/base.py``)
and C2 (``providers/base.py``), leaving ``service.py`` free for the
implementation. Recorded as a finding in ``docs/tasks/P0-fakes.md``.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field


class ApprovalStatus(StrEnum):
    """C4 OpenAPI ``ApprovalStatus`` — the single source of lifecycle truth.

    Rows are INSERTed with an explicit ``pending``; the column has NO schema
    default, so a creation path that forgets the status fails loudly instead of
    minting a decided row (central-memory lesson 2026-08-17).
    """

    PENDING = "pending"
    APPROVED = "approved"
    REFUSED = "refused"
    EXPIRED = "expired"
    CONSUMED = "consumed"


# --------------------------------------------------------------------------- #
# C4 §4 — the in-process seam (transcribed verbatim)
# --------------------------------------------------------------------------- #
class ParkRequest(BaseModel):
    """C4 §4 ``ParkRequest``."""

    agent_id: str
    tool: str
    operation: str
    args_hash: str
    params_redacted: dict
    request_id: str
    conversation_id: str
    task_id: str
    summary: str  # built by SUNIL code, never LLM output
    continuation: dict  # opaque persisted plan-cursor state (ADR-031)


class ParkedApproval(BaseModel):
    """C4 §4 ``ParkedApproval``."""

    approval_id: str
    expires_at: str


class ApprovalBinding(BaseModel):
    """C4 §4 ``ApprovalBinding`` — an approval authorises exactly one execution
    of ``(agent_id, tool, operation, args_hash)`` (C4 §1, single-use binding)."""

    agent_id: str
    tool: str
    operation: str
    args_hash: str


class ConsumeResult(BaseModel):
    """C4 §4 ``ConsumeResult``. ``ok=False`` maps to C1 ``approval_invalid``."""

    ok: bool
    reason: Literal["consumed", "not_found", "not_approved", "binding_mismatch"] | None


class ApprovalsService(Protocol):
    """C4 §4 ``ApprovalsService`` — the seam injected into the Tool Manager
    (C1 §2.2). ``consume`` performs the binding check and the
    ``approved → consumed`` CAS (grace-bounded, C4 §1) in one transaction."""

    async def park(self, req: ParkRequest) -> ParkedApproval: ...

    async def consume(
        self, approval_id: str, *, binding: ApprovalBinding
    ) -> ConsumeResult: ...


# --------------------------------------------------------------------------- #
# C4 OpenAPI — the persisted row and the conflict shape
# --------------------------------------------------------------------------- #
class Approval(BaseModel):
    """C4 OpenAPI ``Approval`` — one approval with full (redacted) detail.

    ``summary`` and every ``params_redacted`` value embed attacker-influenceable
    strings: the dashboard MUST render them as PLAIN TEXT ONLY, never HTML,
    markdown or DOM markup (C4 §4, Security review 2026-09-10 item 8).
    """

    id: str
    status: ApprovalStatus
    created_at: str
    expires_at: str  # created_at + SUNIL_APPROVAL_TTL_HOURS (default 72)
    agent_id: str
    tool: str
    operation: str
    args_hash: str  # sha256 hex of canonical JSON of the VALIDATED params (C1)
    params_redacted: dict
    request_id: str
    conversation_id: str
    task_id: str
    summary: str = Field(max_length=500)
    decided_at: str | None = None
    decided_by: str | None = None
    decision_reason: str | None = Field(default=None, max_length=1000)
    consumed_at: str | None = None


class ApprovalListResponse(BaseModel):
    """C4 OpenAPI ``ApprovalListResponse``."""

    approvals: list[Approval]
    next_cursor: str | None


class DecisionRequest(BaseModel):
    """C4 OpenAPI ``DecisionRequest`` (``additionalProperties: false``)."""

    model_config = ConfigDict(extra="forbid")

    decision: Literal["approve", "refuse"]
    reason: str | None = Field(default=None, max_length=1000)


class StateConflictError(BaseModel):
    """The inner object of C4 OpenAPI ``StateConflict`` — the ONLY conflict shape
    (C4 §5: expiry at decision time is a 409 with ``current_status=expired``, not
    a separate 410)."""

    kind: Literal["state_conflict"] = "state_conflict"
    message: str
    current_status: ApprovalStatus


class StateConflict(BaseModel):
    """C4 OpenAPI ``StateConflict`` — the 409 body."""

    error: StateConflictError


class ApprovalRequestedEvent(BaseModel):
    """C4 OpenAPI ``ApprovalRequestedEvent`` — the ``approval.requested`` webhook
    payload. Redacted summary only: never params, never prompts (C4 §2)."""

    event: Literal["approval.requested"] = "approval.requested"
    approval_id: str
    agent_id: str
    tool: str
    operation: str
    summary: str = Field(max_length=500)
    created_at: str
    expires_at: str
