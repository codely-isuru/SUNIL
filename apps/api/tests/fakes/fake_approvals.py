"""``FakeApprovalsService`` — C4 §6's fake specification, verbatim.

Source of truth: ``docs/contracts/C4-approvals.md`` §6 (v1.0.0, FROZEN
2026-09-10). This module is THE approvals fake for every stream: C1 §6's table
points at it ("C4 §6's spec verbatim, no C1-specific variant") and Stream D
builds the dashboard against it (§6: "provides the HTTP layer's store").

It implements the ``ApprovalsService`` protocol (``park`` / ``consume``, C4 §4)
and adds the three fake-only helpers the HTTP layer and the sweeper need
(``decide`` / ``sweep`` / ``list_approvals``, C4 §6 items 2, 4, 5).

Deliberate design notes where the contract is silent (each recorded as a finding
in ``docs/tasks/P0-fakes.md``):

* ``decide`` and ``sweep`` are declared in §6 with positional signatures and no
  ``async`` marker (C1 §6.4 test 5 calls ``fake_approvals.decide(approval_id,
  "approve", None, now)``), so they are synchronous. Only the two protocol
  methods are ``async``.
* ``decide`` returns ``Approval | StateConflict`` — §6.2's wording is "return
  ``state_conflict(current_status=…)``". The HTTP layer maps a returned
  ``StateConflict`` to 409 (C4 §5) and a returned ``None`` (unknown id) to 404.
* ``consume`` reads the injected clock, because C4 §4's frozen signature carries
  no ``now`` parameter — the real service reads the database clock in the same
  place.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Literal

from sunil.core.approvals.base import (
    Approval,
    ApprovalBinding,
    ApprovalListResponse,
    ApprovalRequestedEvent,
    ApprovalsService,
    ApprovalStatus,
    ConsumeResult,
    ParkedApproval,
    ParkRequest,
    StateConflict,
    StateConflictError,
)

from tests.fakes.clock import FakeClock, from_iso, to_iso

#: C4 §6: ``expires_at = created_at + 72h`` (mirrors SUNIL_APPROVAL_TTL_HOURS).
TTL_HOURS = 72


def _park_order(approval_id: str) -> int:
    """Numeric park order from an ``apr-N`` id.

    Numeric, never lexicographic: C3 §5 records why (``mem-10`` sorts before
    ``mem-2`` as text). ``created_at`` already totally orders rows minted by the
    default clock; this key only decides ties under a frozen injected clock.
    """
    return int(approval_id.rsplit("-", 1)[1])


class FakeApprovalsService:
    """C4 §6 fake. In-memory, deterministic, no HTTP, no database."""

    def __init__(
        self, consume_grace_hours: int = 1, clock: FakeClock | None = None
    ) -> None:
        self.consume_grace_hours = consume_grace_hours
        self.clock = clock if clock is not None else FakeClock()
        self.approvals: dict[str, Approval] = {}
        self.webhook_sent: list[dict] = []

    # -- C4 §4 protocol ---------------------------------------------------- #
    async def park(self, req: ParkRequest) -> ParkedApproval:
        """C4 §6.1 — new approval, ``status="pending"`` set explicitly, returns
        ``ParkedApproval``; appends the ``ApprovalRequestedEvent`` payload to
        ``webhook_sent``."""
        now = self.clock.now()
        approval_id = f"apr-{len(self.approvals) + 1}"
        created_at = to_iso(now)
        expires_at = to_iso(now + timedelta(hours=TTL_HOURS))

        self.approvals[approval_id] = Approval(
            id=approval_id,
            status=ApprovalStatus.PENDING,  # explicit; never a default (C4 §1)
            created_at=created_at,
            expires_at=expires_at,
            agent_id=req.agent_id,
            tool=req.tool,
            operation=req.operation,
            args_hash=req.args_hash,
            params_redacted=req.params_redacted,
            request_id=req.request_id,
            conversation_id=req.conversation_id,
            task_id=req.task_id,
            summary=req.summary,
        )
        self.webhook_sent.append(
            ApprovalRequestedEvent(
                approval_id=approval_id,
                agent_id=req.agent_id,
                tool=req.tool,
                operation=req.operation,
                summary=req.summary,
                created_at=created_at,
                expires_at=expires_at,
            ).model_dump()
        )
        self.clock.advance(seconds=1)  # C4 §6: +1 s per park
        return ParkedApproval(approval_id=approval_id, expires_at=expires_at)

    async def consume(
        self, approval_id: str, *, binding: ApprovalBinding
    ) -> ConsumeResult:
        """C4 §6.3, in this order — unknown id → ``not_found``; status ≠
        ``approved`` → ``not_approved``; ``approved`` but past
        ``consume_grace_hours`` → lazy ``expired`` + ``not_approved``; binding
        tuple ≠ stored tuple → ``binding_mismatch`` with the approval left
        ``approved`` (a mismatch must not burn the approval); match within grace
        → CAS to ``consumed``."""
        row = self.approvals.get(approval_id)
        if row is None:
            return ConsumeResult(ok=False, reason="not_found")
        if row.status != ApprovalStatus.APPROVED:
            return ConsumeResult(ok=False, reason="not_approved")

        now = self.clock.now()
        if row.decided_at is not None and now >= from_iso(row.decided_at) + timedelta(
            hours=self.consume_grace_hours
        ):
            row.status = ApprovalStatus.EXPIRED
            return ConsumeResult(ok=False, reason="not_approved")

        stored = ApprovalBinding(
            agent_id=row.agent_id,
            tool=row.tool,
            operation=row.operation,
            args_hash=row.args_hash,
        )
        if binding != stored:
            return ConsumeResult(ok=False, reason="binding_mismatch")

        row.status = ApprovalStatus.CONSUMED
        row.consumed_at = to_iso(now)
        return ConsumeResult(ok=True, reason="consumed")

    # -- C4 §6 fake-only helpers (the HTTP layer + sweeper) ---------------- #
    def decide(
        self,
        approval_id: str,
        decision: Literal["approve", "refuse"],
        reason: str | None,
        now,
    ) -> Approval | StateConflict | None:
        """C4 §6.2 — ``pending`` + ``now < expires_at`` → transition, set
        ``decided_at=now``, ``decided_by="owner"``, return the row. ``pending`` +
        ``now >= expires_at`` → transition to ``expired`` first, then return
        ``state_conflict(current_status="expired")``. Any other status →
        ``state_conflict`` with it. Unknown id → ``None`` (HTTP 404)."""
        row = self.approvals.get(approval_id)
        if row is None:
            return None

        if row.status == ApprovalStatus.PENDING:
            if now >= from_iso(row.expires_at):
                row.status = ApprovalStatus.EXPIRED
                return self._conflict(row)
            row.status = (
                ApprovalStatus.APPROVED
                if decision == "approve"
                else ApprovalStatus.REFUSED
            )
            row.decided_at = to_iso(now)
            row.decided_by = "owner"
            row.decision_reason = reason
            return row

        return self._conflict(row)

    def sweep(self, now) -> int:
        """C4 §6.4 — transitions every ``pending`` with ``expires_at <= now`` AND
        every ``approved`` with ``decided_at + consume_grace_hours <= now`` to
        ``expired``; returns the total count."""
        grace = timedelta(hours=self.consume_grace_hours)
        swept = 0
        for row in self.approvals.values():
            if row.status == ApprovalStatus.PENDING and now >= from_iso(row.expires_at):
                row.status = ApprovalStatus.EXPIRED
                swept += 1
            elif (
                row.status == ApprovalStatus.APPROVED
                and row.decided_at is not None
                and now >= from_iso(row.decided_at) + grace
            ):
                row.status = ApprovalStatus.EXPIRED
                swept += 1
        return swept

    def list_approvals(
        self,
        *,
        status: ApprovalStatus | None = None,
        limit: int = 50,
        cursor: str | None = None,
    ) -> ApprovalListResponse:
        """C4 §6.5 — filter by status, order ``created_at`` desc then id desc;
        cursor = the last row's id; ``next_cursor=None`` when the page is short.

        An unknown cursor raises ``ValueError`` (the HTTP layer's 422) rather
        than silently serving page one.
        """
        rows = [
            row
            for row in self.approvals.values()
            if status is None or row.status == status
        ]
        rows.sort(key=lambda r: (r.created_at, _park_order(r.id)), reverse=True)

        if cursor is not None:
            ids = [row.id for row in rows]
            if cursor not in ids:
                raise ValueError(f"unknown cursor: {cursor}")
            rows = rows[ids.index(cursor) + 1 :]

        page = rows[:limit]
        next_cursor = page[-1].id if len(page) == limit and len(rows) > limit else None
        return ApprovalListResponse(approvals=page, next_cursor=next_cursor)

    # -- internals --------------------------------------------------------- #
    @staticmethod
    def _conflict(row: Approval) -> StateConflict:
        return StateConflict(
            error=StateConflictError(
                message=f"approval {row.id} is {row.status.value}, not pending",
                current_status=row.status,
            )
        )


#: Static conformance witness (F2) — FakeApprovalsService satisfies C4 §4's
#: ApprovalsService structurally; inheriting it would have made a forgotten
#: `consume` return None (the backend review's proof).
_check: ApprovalsService = FakeApprovalsService()
