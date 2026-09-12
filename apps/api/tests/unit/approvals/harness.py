"""One uniform surface over ``FakeApprovalsService`` and the real
``DatabaseApprovalsService``, so C4 §6's contract behaviours can be run as the
SAME test bodies against both.

Why an adapter rather than importing ``tests/contracts/test_c4_approvals.py``'s
bodies directly: those bodies address rows as ``approvals.approvals["apr-1"]``
and hard-code the fake's ``apr-N`` id scheme, neither of which a database
service has (its ids are ULIDs, and its rows live in Postgres). The *behaviours*
are what the contract fixes, so the adapter normalises the two mechanical
differences — id capture and row lookup — and nothing else. Every assertion in
``test_real_service_contract.py`` therefore runs unchanged on both
implementations, which is the parity evidence Stream D owes QA.

The adapter adds no behaviour: each method is a direct delegation. The one
modelling choice is that :class:`DbHarness.park` advances the injected clock one
second per park, mirroring C4 §6's "``created_at`` from an injectable clock
(+1 s per park)" — the fake does that inside ``park``, and the real service
must not (its clock is the wall clock), so the harness does it for the real
service. That keeps ``created_at`` a total order in both, which is what the
§6.5 listing tests need.
"""

from __future__ import annotations

from typing import Literal

from sunil.core.approvals.base import (
    Approval,
    ApprovalBinding,
    ApprovalListResponse,
    ApprovalStatus,
    ConsumeResult,
    ParkedApproval,
    ParkRequest,
    StateConflict,
)
from sunil.core.approvals.service import DatabaseApprovalsService

from tests.fakes.clock import FakeClock
from tests.fakes.fake_approvals import FakeApprovalsService


class FakeHarness:
    """C4 §6's fake behind the uniform surface."""

    name = "fake"

    def __init__(self, clock: FakeClock, consume_grace_hours: int = 1) -> None:
        self.clock = clock
        self.service = FakeApprovalsService(
            consume_grace_hours=consume_grace_hours, clock=clock
        )

    async def park(self, req: ParkRequest) -> ParkedApproval:
        return await self.service.park(req)

    async def decide(
        self,
        approval_id: str,
        decision: Literal["approve", "refuse"],
        reason: str | None = None,
    ) -> Approval | StateConflict | None:
        # R7.1 atomic set (C4 v1.2.0): the service owns time; decide is awaitable.
        return await self.service.decide(approval_id, decision, reason)

    async def consume(
        self, approval_id: str, *, binding: ApprovalBinding
    ) -> ConsumeResult:
        return await self.service.consume(approval_id, binding=binding)

    async def sweep(self) -> int:
        return self.service.sweep(self.clock.now())

    async def get(self, approval_id: str) -> Approval | None:
        return self.service.approvals.get(approval_id)

    async def list(
        self,
        *,
        status: ApprovalStatus | None = None,
        limit: int = 50,
        cursor: str | None = None,
    ) -> ApprovalListResponse:
        return self.service.list_approvals(status=status, limit=limit, cursor=cursor)

    async def service_continuation(self, approval_id: str) -> dict | None:
        parked = self.service.parked.get(approval_id)
        return None if parked is None else parked.continuation

    @property
    def webhook_sent(self) -> list[dict]:
        return self.service.webhook_sent


class RecordingNotifier:
    """Captures ``approval.requested`` payloads instead of POSTing them, so the
    real service's webhook can be probed by the same redaction-by-shape test the
    fake's ``webhook_sent`` list satisfies (C4 contract test 6)."""

    def __init__(self) -> None:
        self.sent: list[dict] = []

    async def notify_requested(self, payload: dict) -> None:
        self.sent.append(payload)


class DbHarness:
    """The real ``DatabaseApprovalsService`` behind the uniform surface."""

    name = "db"

    def __init__(self, service: DatabaseApprovalsService, clock: FakeClock) -> None:
        self.clock = clock
        self.service = service

    async def park(self, req: ParkRequest) -> ParkedApproval:
        parked = await self.service.park(req)
        self.clock.advance(seconds=1)  # see module docstring
        return parked

    async def decide(
        self,
        approval_id: str,
        decision: Literal["approve", "refuse"],
        reason: str | None = None,
    ) -> Approval | StateConflict | None:
        return await self.service.decide(approval_id, decision, reason)

    async def consume(
        self, approval_id: str, *, binding: ApprovalBinding
    ) -> ConsumeResult:
        return await self.service.consume(approval_id, binding=binding)

    async def sweep(self) -> int:
        return await self.service.sweep()

    async def get(self, approval_id: str) -> Approval | None:
        return await self.service.get(approval_id)

    async def list(
        self,
        *,
        status: ApprovalStatus | None = None,
        limit: int = 50,
        cursor: str | None = None,
    ) -> ApprovalListResponse:
        return await self.service.list_approvals(
            status=status, limit=limit, cursor=cursor
        )

    async def service_continuation(self, approval_id: str) -> dict | None:
        return await self.service.continuation_for(approval_id)

    @property
    def webhook_sent(self) -> list[dict]:
        notifier = self.service.notifier
        assert isinstance(notifier, RecordingNotifier), (
            "the db harness must be wired with a RecordingNotifier"
        )
        return notifier.sent
