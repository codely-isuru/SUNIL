"""C4 — Approvals contract suite.

Source of truth: ``docs/contracts/C4-approvals.md`` v1.0.0 (FROZEN 2026-09-10) and
``docs/contracts/C4-approvals-openapi.yaml``. Every numbered test below is one of
C4 §6's seven contract tests, cited in its docstring; the fake under test is C4
§6's ``FakeApprovalsService`` (spec verbatim).

The HTTP status codes the contract quotes (409) are the Stream D mapping of the
``StateConflict`` shape this seam returns; §5 fixes the shape, and these tests
assert the shape. Nothing here touches HTTP.
"""

from __future__ import annotations

import pytest

from sunil.core.approvals.base import (
    ApprovalBinding,
    ApprovalStatus,
    ParkRequest,
    StateConflict,
)
from tests.fakes.clock import FakeClock
from tests.fakes.fake_approvals import FakeApprovalsService

pytestmark = pytest.mark.contract

ARGS_HASH = "a" * 64
OTHER_HASH = "b" * 64


def park_request(
    *,
    agent_id: str = "project_manager",
    tool: str = "fake_tool",
    operation: str = "write_item",
    args_hash: str = ARGS_HASH,
) -> ParkRequest:
    """A ParkRequest with every C4 §4 field populated."""
    return ParkRequest(
        agent_id=agent_id,
        tool=tool,
        operation=operation,
        args_hash=args_hash,
        params_redacted={"key": "demo", "value": "1"},
        request_id="req-1",
        conversation_id="conv-1",
        task_id="task-1",
        summary="fake_tool.write_item requires approval",
        continuation={"plan": [], "cursor": 0},
    )


def binding(
    *,
    agent_id: str = "project_manager",
    tool: str = "fake_tool",
    operation: str = "write_item",
    args_hash: str = ARGS_HASH,
) -> ApprovalBinding:
    return ApprovalBinding(
        agent_id=agent_id, tool=tool, operation=operation, args_hash=args_hash
    )


@pytest.fixture
def clock() -> FakeClock:
    """C4 §6: injectable clock, default start 2026-01-01T00:00:00Z."""
    return FakeClock()


@pytest.fixture
def approvals(clock: FakeClock) -> FakeApprovalsService:
    return FakeApprovalsService(consume_grace_hours=1, clock=clock)


# --------------------------------------------------------------------------- #
# C4 contract test 1
# --------------------------------------------------------------------------- #
async def test_c4_1_park_decide_consume_is_single_use(
    approvals: FakeApprovalsService, clock: FakeClock
) -> None:
    """C4 contract test 1 — park → pending; decide approve → approved; consume
    with matching binding → consumed; second consume → ``not_approved``
    (single-use proven)."""
    parked = await approvals.park(park_request())

    assert parked.approval_id == "apr-1"
    row = approvals.approvals["apr-1"]
    assert row.status == ApprovalStatus.PENDING
    # §1: status is written explicitly at creation, never a schema default.
    assert row.created_at == "2026-01-01T00:00:00Z"
    assert row.expires_at == "2026-01-04T00:00:00Z"  # created_at + 72h
    assert row.decided_at is None and row.decided_by is None
    assert row.consumed_at is None

    decided = approvals.decide("apr-1", "approve", None, clock.now())
    assert isinstance(decided, type(row))
    assert decided.status == ApprovalStatus.APPROVED
    assert decided.decided_by == "owner"
    assert decided.decided_at is not None

    first = await approvals.consume("apr-1", binding=binding())
    assert (first.ok, first.reason) == (True, "consumed")
    assert approvals.approvals["apr-1"].status == ApprovalStatus.CONSUMED
    assert approvals.approvals["apr-1"].consumed_at is not None

    second = await approvals.consume("apr-1", binding=binding())
    assert (second.ok, second.reason) == (False, "not_approved")
    assert approvals.approvals["apr-1"].status == ApprovalStatus.CONSUMED


# --------------------------------------------------------------------------- #
# C4 contract test 2
# --------------------------------------------------------------------------- #
async def test_c4_2_decide_on_non_pending_conflicts_with_current_status(
    approvals: FakeApprovalsService, clock: FakeClock
) -> None:
    """C4 contract test 2 — decide on approved/refused/expired/consumed → 409
    with ``current_status`` correct in all four cases."""
    # approved
    await approvals.park(park_request())
    approvals.decide("apr-1", "approve", None, clock.now())
    conflict = approvals.decide("apr-1", "approve", None, clock.now())
    assert isinstance(conflict, StateConflict)
    assert conflict.error.kind == "state_conflict"
    assert conflict.error.current_status == ApprovalStatus.APPROVED

    # refused
    await approvals.park(park_request())
    approvals.decide("apr-2", "refuse", "no thanks", clock.now())
    conflict = approvals.decide("apr-2", "approve", None, clock.now())
    assert isinstance(conflict, StateConflict)
    assert conflict.error.current_status == ApprovalStatus.REFUSED

    # consumed
    await approvals.consume("apr-1", binding=binding())
    conflict = approvals.decide("apr-1", "refuse", None, clock.now())
    assert isinstance(conflict, StateConflict)
    assert conflict.error.current_status == ApprovalStatus.CONSUMED

    # expired (TTL): a fresh row swept past its 72 h TTL
    await approvals.park(park_request())
    clock.advance(hours=73)
    assert approvals.sweep(clock.now()) >= 1
    assert approvals.approvals["apr-3"].status == ApprovalStatus.EXPIRED
    conflict = approvals.decide("apr-3", "approve", None, clock.now())
    assert isinstance(conflict, StateConflict)
    assert conflict.error.current_status == ApprovalStatus.EXPIRED


# --------------------------------------------------------------------------- #
# C4 contract test 3
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "field,value",
    [
        ("agent_id", "developer"),
        ("tool", "github"),
        ("operation", "issues.close"),
        ("args_hash", OTHER_HASH),
    ],
)
async def test_c4_3_binding_mismatch_burns_nothing(
    approvals: FakeApprovalsService, clock: FakeClock, field: str, value: str
) -> None:
    """C4 contract test 3 — consume with one field of the binding changed (each of
    the four) → ``binding_mismatch``, status still ``approved``; the SAME approval
    then consumes successfully with the correct binding (§6 rule 3: a mismatch
    must not burn the approval)."""
    await approvals.park(park_request())
    approvals.decide("apr-1", "approve", None, clock.now())

    wrong = await approvals.consume("apr-1", binding=binding(**{field: value}))
    assert (wrong.ok, wrong.reason) == (False, "binding_mismatch")
    assert approvals.approvals["apr-1"].status == ApprovalStatus.APPROVED
    assert approvals.approvals["apr-1"].consumed_at is None

    right = await approvals.consume("apr-1", binding=binding())
    assert (right.ok, right.reason) == (True, "consumed")
    assert approvals.approvals["apr-1"].status == ApprovalStatus.CONSUMED


async def test_c4_3_unknown_id_is_not_found(approvals: FakeApprovalsService) -> None:
    """C4 §6.3 — unknown id → ``not_found`` (the fourth ConsumeResult reason)."""
    result = await approvals.consume("apr-nope", binding=binding())
    assert (result.ok, result.reason) == (False, "not_found")


# --------------------------------------------------------------------------- #
# C4 contract test 4
# --------------------------------------------------------------------------- #
async def test_c4_4_ttl_expiry_and_sweep_counts_once(
    approvals: FakeApprovalsService, clock: FakeClock
) -> None:
    """C4 contract test 4 — expiry: park, advance clock 73 h, decide → 409
    ``expired``; sweep counts it exactly once.

    Note (recorded as a finding in docs/tasks/P0-fakes.md): §6.2 makes ``decide``
    expire the row lazily, so a sweep AFTER that decide legitimately counts zero.
    'Exactly once' is therefore asserted as sweep idempotence, on both paths: the
    lazily-expired row is never re-counted, and an untouched pending row is
    counted once and then never again.
    """
    await approvals.park(park_request())  # apr-1 — decided after expiry
    await approvals.park(park_request())  # apr-2 — never decided
    clock.advance(hours=73)

    conflict = approvals.decide("apr-1", "approve", None, clock.now())
    assert isinstance(conflict, StateConflict)
    assert conflict.error.current_status == ApprovalStatus.EXPIRED
    assert approvals.approvals["apr-1"].status == ApprovalStatus.EXPIRED

    # apr-1 is already expired, so only apr-2 remains for the sweeper.
    assert approvals.sweep(clock.now()) == 1
    assert approvals.approvals["apr-2"].status == ApprovalStatus.EXPIRED
    assert approvals.sweep(clock.now()) == 0


# --------------------------------------------------------------------------- #
# C4 contract test 5
# --------------------------------------------------------------------------- #
async def test_c4_5_concurrent_decides_exactly_one_wins(
    approvals: FakeApprovalsService, clock: FakeClock
) -> None:
    """C4 contract test 5 — two concurrent decides (sequential calls simulating
    the race) → exactly one wins, the second gets 409."""
    await approvals.park(park_request())

    first = approvals.decide("apr-1", "approve", None, clock.now())
    second = approvals.decide("apr-1", "refuse", None, clock.now())

    assert not isinstance(first, StateConflict)
    assert first.status == ApprovalStatus.APPROVED
    assert isinstance(second, StateConflict)
    assert second.error.current_status == ApprovalStatus.APPROVED
    # The loser changed nothing: the winner's decision stands.
    assert approvals.approvals["apr-1"].status == ApprovalStatus.APPROVED


# --------------------------------------------------------------------------- #
# C4 contract test 6
# --------------------------------------------------------------------------- #
async def test_c4_6_webhook_payload_carries_no_params(
    approvals: FakeApprovalsService,
) -> None:
    """C4 contract test 6 — webhook payload contains NO ``params_redacted`` key
    (redaction-by-shape probe, §2)."""
    await approvals.park(park_request())

    assert len(approvals.webhook_sent) == 1
    payload = approvals.webhook_sent[0]
    assert "params_redacted" not in payload
    assert payload["event"] == "approval.requested"
    assert set(payload) == {
        "event",
        "approval_id",
        "agent_id",
        "tool",
        "operation",
        "summary",
        "created_at",
        "expires_at",
    }
    # Redaction by shape, not by filtering: no value anywhere in the payload
    # carries a params value.
    assert "demo" not in repr(payload)


# --------------------------------------------------------------------------- #
# C4 contract test 7
# --------------------------------------------------------------------------- #
async def test_c4_7_stale_approved_is_not_consumable_after_grace(
    approvals: FakeApprovalsService, clock: FakeClock
) -> None:
    """C4 contract test 7 (Security review 2026-09-10 item 1) — park, approve,
    advance past ``consume_grace_hours``, consume with the CORRECT binding →
    ``ok=False, reason="not_approved"`` and the row is ``expired``; a second
    park+approve consumed within grace succeeds."""
    await approvals.park(park_request())
    approvals.decide("apr-1", "approve", None, clock.now())

    clock.advance(hours=1, seconds=1)  # past the 1 h grace
    stale = await approvals.consume("apr-1", binding=binding())
    assert (stale.ok, stale.reason) == (False, "not_approved")
    assert approvals.approvals["apr-1"].status == ApprovalStatus.EXPIRED

    await approvals.park(park_request())
    approvals.decide("apr-2", "approve", None, clock.now())
    fresh = await approvals.consume("apr-2", binding=binding())
    assert (fresh.ok, fresh.reason) == (True, "consumed")


async def test_c4_7_sweep_expires_a_stale_approved_row(
    approvals: FakeApprovalsService, clock: FakeClock
) -> None:
    """C4 contract test 7, second clause — ``sweep`` also expires a stale
    ``approved`` row it reaches first (§1's approved→expired transition)."""
    await approvals.park(park_request())
    approvals.decide("apr-1", "approve", None, clock.now())

    clock.advance(hours=1, seconds=1)
    assert approvals.sweep(clock.now()) == 1
    assert approvals.approvals["apr-1"].status == ApprovalStatus.EXPIRED
    assert approvals.sweep(clock.now()) == 0


async def test_c4_7_approved_within_grace_survives_a_sweep(
    approvals: FakeApprovalsService, clock: FakeClock
) -> None:
    """Guard for the other side of the grace bound: a sweep must NOT expire an
    approved row still inside its window (§1: ``decided_at + grace <= now``)."""
    await approvals.park(park_request())
    approvals.decide("apr-1", "approve", None, clock.now())

    clock.advance(hours=1)  # exactly at the boundary is inclusive per §1
    assert approvals.sweep(clock.now()) == 1

    approvals2 = FakeApprovalsService(consume_grace_hours=1, clock=(c2 := FakeClock()))
    await approvals2.park(park_request())
    approvals2.decide("apr-1", "approve", None, c2.now())
    c2.advance(seconds=59 * 60)  # 59 minutes — inside grace
    assert approvals2.sweep(c2.now()) == 0
    assert approvals2.approvals["apr-1"].status == ApprovalStatus.APPROVED


# --------------------------------------------------------------------------- #
# C4 §6.5 — listing (fake-spec coverage; Stream D's dashboard queue reads this)
# --------------------------------------------------------------------------- #
async def test_c4_listing_filters_orders_and_pages(
    approvals: FakeApprovalsService, clock: FakeClock
) -> None:
    """C4 §6.5 — listing: filter by status, order ``created_at`` desc then id
    desc; cursor = the last row's id; ``next_cursor=None`` when the page is
    short."""
    for _ in range(3):
        await approvals.park(park_request())
    approvals.decide("apr-2", "approve", None, clock.now())

    page = approvals.list_approvals(status=ApprovalStatus.PENDING)
    assert [a.id for a in page.approvals] == ["apr-3", "apr-1"]
    assert page.next_cursor is None

    first = approvals.list_approvals(limit=2)
    assert [a.id for a in first.approvals] == ["apr-3", "apr-2"]
    assert first.next_cursor == "apr-2"

    second = approvals.list_approvals(limit=2, cursor=first.next_cursor)
    assert [a.id for a in second.approvals] == ["apr-1"]
    assert second.next_cursor is None


async def test_c4_park_ids_and_clock_advance_in_park_order(
    approvals: FakeApprovalsService,
) -> None:
    """C4 §6 — ids ``apr-1``, ``apr-2``, … in park order; created_at +1 s per park."""
    a = await approvals.park(park_request())
    b = await approvals.park(park_request())

    assert (a.approval_id, b.approval_id) == ("apr-1", "apr-2")
    assert approvals.approvals["apr-1"].created_at == "2026-01-01T00:00:00Z"
    assert approvals.approvals["apr-2"].created_at == "2026-01-01T00:00:01Z"
    assert a.expires_at == "2026-01-04T00:00:00Z"
    assert b.expires_at == "2026-01-04T00:00:01Z"
