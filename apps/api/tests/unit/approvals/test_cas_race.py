"""The compare-and-swap proof: genuinely concurrent transitions, two connections.

C4 contract test 5 simulates the decide race with two sequential calls, which is
all an in-memory fake can do. That version cannot distinguish a real CAS from a
read-modify-write — a ``SELECT`` then an ``UPDATE`` passes it perfectly, and
loses the update the moment two requests actually interleave. So this module
runs the race for real: two coroutines on two separate database connections,
started together with ``asyncio.gather``, against one approval.

``engine.begin()`` checks out its own connection per call, so the two decides
are two concurrent transactions in the database's eyes — on Postgres the second
one's ``UPDATE … WHERE status='pending'`` blocks on the first's row lock, then
re-evaluates the predicate after the commit and matches zero rows. That
re-evaluation is the whole safety property, and it is a property of the
database, not of this code, which is why it has to be tested ON a database.

Run against every engine the machine offers (``factory.engine_urls()``), so the
test id records which engines the proof actually ran on.

Verified to have teeth: with the ``T.c.status == 'pending'`` guard removed from
``decide``'s UPDATE, ``test_concurrent_decides_produce_exactly_one_winner``
fails with two winners. A test that cannot fail proves nothing.
"""

from __future__ import annotations

import asyncio

import pytest

from sunil.core.approvals.base import ApprovalStatus, StateConflict

from tests.fakes.clock import FakeClock
from tests.unit.approvals import factory
from tests.unit.approvals.test_real_service_contract import binding, park_request

#: How many racers pile onto one approval. More than two, because a two-way
#: race can be won by luck; ten cannot.
RACERS = 10


@pytest.fixture(params=[pytest.param(u, id=factory.label(u)) for u in factory.engine_urls()])
async def service(request):
    engine = await factory.make_engine(request.param)
    try:
        yield factory.make_service(engine, clock=FakeClock().now)
    finally:
        await engine.dispose()


async def test_concurrent_decides_produce_exactly_one_winner(service) -> None:
    """C4 §1's ``pending → approved|refused`` CAS under real concurrency.

    Ten simultaneous decisions, five approve and five refuse: exactly one row
    is returned and nine ``StateConflict``s come back, every one of them
    carrying the winner's status — so the loser's 409 shows the true state
    (C4 §5's reason for refusing decision idempotency) rather than echoing the
    losing caller's own intent.
    """
    parked = await service.park(park_request())

    results = await asyncio.gather(
        *[
            service.decide(parked.approval_id, "approve" if i % 2 else "refuse")
            for i in range(RACERS)
        ]
    )

    winners = [r for r in results if not isinstance(r, StateConflict)]
    losers = [r for r in results if isinstance(r, StateConflict)]
    assert len(winners) == 1, f"expected exactly one winner, got {len(winners)}"
    assert len(losers) == RACERS - 1

    winning_status = winners[0].status
    assert winning_status in {ApprovalStatus.APPROVED, ApprovalStatus.REFUSED}
    # Every loser reports the WINNER's status, not its own attempted decision.
    assert {loser.error.current_status for loser in losers} == {winning_status}

    row = await service.get(parked.approval_id)
    assert row.status == winning_status
    assert row.decided_at is not None


async def test_concurrent_consumes_spend_the_approval_exactly_once(service) -> None:
    """C4 §1's ``approved → consumed`` CAS — the single-use property, which is
    the one this service exists to guarantee. Ten concurrent consumes with the
    correct binding: exactly one ``ok=True``, and the other nine
    ``not_approved``. Two winners here would mean an owner's single approval
    authorised two privileged side effects.
    """
    parked = await service.park(park_request())
    await service.decide(parked.approval_id, "approve")

    results = await asyncio.gather(
        *[service.consume(parked.approval_id, binding=binding()) for _ in range(RACERS)]
    )

    assert [r.ok for r in results].count(True) == 1
    assert {r.reason for r in results if not r.ok} == {"not_approved"}
    row = await service.get(parked.approval_id)
    assert row.status == ApprovalStatus.CONSUMED
    assert row.consumed_at is not None


async def test_a_sweep_racing_a_decide_cannot_produce_two_transitions(service) -> None:
    """The pair C4 §1 leaves adjacent: the TTL sweeper's ``pending → expired``
    and the owner's ``pending → approved``, both live at the same instant on an
    approval exactly at its expiry boundary. Whoever wins, the row ends in ONE
    state and the other caller is told so — a row that ended ``approved`` after
    a sweep counted it as expired would have been double-counted, and the task
    would be finalised as expired while the continuation ran.
    """
    parked = await service.park(park_request())
    clock = FakeClock()
    clock.advance(hours=72)  # exactly expires_at: both guards are live
    service.clock = clock.now

    decided, swept = await asyncio.gather(
        service.decide(parked.approval_id, "approve"),
        service.sweep(),
    )

    row = await service.get(parked.approval_id)
    # At the boundary the decide guard (`expires_at > now`) is false and the
    # sweep guard (`expires_at <= now`) is true, so expiry must win outright.
    assert row.status == ApprovalStatus.EXPIRED
    assert isinstance(decided, StateConflict)
    assert decided.error.current_status == ApprovalStatus.EXPIRED
    assert swept in (0, 1)  # 0 if the lazy expiry in decide got there first
