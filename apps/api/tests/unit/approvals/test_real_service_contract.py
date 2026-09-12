"""Real-service behavioural parity with C4 §6's contract suite.

Every test in this module is parametrised over BOTH implementations — C4 §6's
``FakeApprovalsService`` (which ``tests/contracts/test_c4_approvals.py`` already
grades) and Stream D's real ``DatabaseApprovalsService`` on a live database —
through the thin adapter in ``harness.py``. A test that passes here has passed
identically against the fake QA pinned and against the implementation, which is
the parity claim; a test that passes only against the fake is a failure of this
module, not of the contract suite.

Numbering follows C4 §6's contract tests 1–8 so the mapping is checkable by
eye. ``tests/contracts/`` is untouched (Stream D task brief).

Database: ``SUNIL_TEST_DATABASE_URL`` when set (Postgres), plus in-memory
SQLite always — see ``factory.py``. The suite therefore reports which engines it
actually exercised in the test ids (``db-postgresql``, ``db-sqlite``).
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from sunil.core.approvals.base import (
    ApprovalBinding,
    ApprovalStatus,
    ParkRequest,
    StateConflict,
)

from tests.fakes.clock import FakeClock
from tests.unit.approvals import factory
from tests.unit.approvals.harness import DbHarness, FakeHarness, RecordingNotifier

ARGS_HASH = "a" * 64
OTHER_HASH = "b" * 64
SUMMARY = "fake_tool.write_item requires approval"
CONTINUATION: dict = {"plan": [], "cursor": 0}


def park_request(
    *,
    agent_id: str = "project_manager",
    tool: str = "fake_tool",
    operation: str = "write_item",
    args_hash: str = ARGS_HASH,
    summary: str = SUMMARY,
    continuation: dict | None = None,
) -> ParkRequest:
    return ParkRequest(
        agent_id=agent_id,
        tool=tool,
        operation=operation,
        args_hash=args_hash,
        params_redacted={"key": "demo", "value": "1"},
        request_id="req-1",
        conversation_id="conv-1",
        task_id="task-1",
        summary=summary,
        continuation=CONTINUATION if continuation is None else continuation,
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


# --------------------------------------------------------------------------- #
# The parametrised harness: one fake + one per available engine
# --------------------------------------------------------------------------- #
def _harness_params() -> list:
    params = [pytest.param(None, id="fake")]
    for url in factory.engine_urls():
        params.append(pytest.param(url, id=f"db-{factory.label(url)}"))
    return params


@pytest.fixture(params=_harness_params())
async def approvals(request):
    """A harness over the fake or over the real service on a real engine."""
    clock = FakeClock()
    url = request.param
    if url is None:
        yield FakeHarness(clock)
        return
    engine = await factory.make_engine(url)
    try:
        service = factory.make_service(
            engine, clock=clock.now, notifier=RecordingNotifier()
        )
        yield DbHarness(service, clock)
    finally:
        await engine.dispose()


# --------------------------------------------------------------------------- #
# C4 contract test 1 — park → approve → consume, single-use
# --------------------------------------------------------------------------- #
async def test_c4_1_park_decide_consume_is_single_use(approvals) -> None:
    """C4 contract test 1 — park → pending; decide approve → approved; consume
    with matching binding → consumed; second consume → ``not_approved``."""
    parked = await approvals.park(park_request())

    row = await approvals.get(parked.approval_id)
    assert row.status == ApprovalStatus.PENDING  # explicit, never a default (§1)
    assert row.expires_at == "2026-01-04T00:00:00Z"  # created_at + 72 h
    assert parked.expires_at == row.expires_at
    assert (row.decided_at, row.decided_by, row.consumed_at) == (None, None, None)

    decided = await approvals.decide(parked.approval_id, "approve")
    assert not isinstance(decided, StateConflict)
    assert decided.status == ApprovalStatus.APPROVED
    assert decided.decided_by == "owner"
    assert decided.decided_at is not None

    first = await approvals.consume(parked.approval_id, binding=binding())
    assert (first.ok, first.reason) == (True, "consumed")
    row = await approvals.get(parked.approval_id)
    assert row.status == ApprovalStatus.CONSUMED
    assert row.consumed_at is not None

    second = await approvals.consume(parked.approval_id, binding=binding())
    assert (second.ok, second.reason) == (False, "not_approved")
    assert (await approvals.get(parked.approval_id)).status == ApprovalStatus.CONSUMED


# --------------------------------------------------------------------------- #
# C4 contract test 2 — decide on a non-pending row conflicts
# --------------------------------------------------------------------------- #
async def test_c4_2_decide_on_non_pending_conflicts_with_current_status(
    approvals,
) -> None:
    """C4 contract test 2 — decide on approved/refused/consumed/expired → 409
    with ``current_status`` correct in all four cases."""
    a = (await approvals.park(park_request())).approval_id
    b = (await approvals.park(park_request())).approval_id
    c = (await approvals.park(park_request())).approval_id

    await approvals.decide(a, "approve")
    conflict = await approvals.decide(a, "approve")
    assert isinstance(conflict, StateConflict)
    assert conflict.error.kind == "state_conflict"
    assert conflict.error.current_status == ApprovalStatus.APPROVED

    await approvals.decide(b, "refuse", "no thanks")
    conflict = await approvals.decide(b, "approve")
    assert isinstance(conflict, StateConflict)
    assert conflict.error.current_status == ApprovalStatus.REFUSED

    await approvals.consume(a, binding=binding())
    conflict = await approvals.decide(a, "refuse")
    assert isinstance(conflict, StateConflict)
    assert conflict.error.current_status == ApprovalStatus.CONSUMED

    approvals.clock.advance(hours=73)
    assert await approvals.sweep() >= 1
    assert (await approvals.get(c)).status == ApprovalStatus.EXPIRED
    conflict = await approvals.decide(c, "approve")
    assert isinstance(conflict, StateConflict)
    assert conflict.error.current_status == ApprovalStatus.EXPIRED


async def test_c4_2_decide_on_an_unknown_id_is_none_not_an_exception(approvals) -> None:
    """C4 §6.2 (normative for the real service, v1.0.1) — unknown ``approval_id``
    → ``None``, which the HTTP layer maps to 404. ``decide`` never raises for
    absence or conflict, so status-code mapping lives in the HTTP layer only."""
    assert await approvals.decide("apr-nope", "approve") is None


# --------------------------------------------------------------------------- #
# C4 contract test 3 — a binding mismatch burns nothing
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
async def test_c4_3_binding_mismatch_burns_nothing(approvals, field, value) -> None:
    """C4 contract test 3 — each of the four binding fields changed in turn →
    ``binding_mismatch`` and the approval stays ``approved``; the SAME approval
    then consumes successfully with the correct binding."""
    aid = (await approvals.park(park_request())).approval_id
    await approvals.decide(aid, "approve")

    wrong = await approvals.consume(aid, binding=binding(**{field: value}))
    assert (wrong.ok, wrong.reason) == (False, "binding_mismatch")
    row = await approvals.get(aid)
    assert row.status == ApprovalStatus.APPROVED
    assert row.consumed_at is None

    right = await approvals.consume(aid, binding=binding())
    assert (right.ok, right.reason) == (True, "consumed")
    assert (await approvals.get(aid)).status == ApprovalStatus.CONSUMED


async def test_c4_3_unknown_id_is_not_found(approvals) -> None:
    """C4 §6.3 — unknown id → ``not_found`` (the fourth ConsumeResult reason)."""
    result = await approvals.consume("apr-nope", binding=binding())
    assert (result.ok, result.reason) == (False, "not_found")


# --------------------------------------------------------------------------- #
# C4 contract test 4 — TTL expiry, swept exactly once
# --------------------------------------------------------------------------- #
async def test_c4_4_ttl_expiry_and_sweep_counts_once(approvals) -> None:
    """C4 contract test 4 — park, advance 73 h, decide → 409 ``expired``; sweep
    counts it exactly once. As in the contract suite, "exactly once" is asserted
    as sweep idempotence on both paths (lazily-expired row never re-counted; an
    untouched pending row counted once and then never again)."""
    lazily = (await approvals.park(park_request())).approval_id
    untouched = (await approvals.park(park_request())).approval_id
    approvals.clock.advance(hours=73)

    conflict = await approvals.decide(lazily, "approve")
    assert isinstance(conflict, StateConflict)
    assert conflict.error.current_status == ApprovalStatus.EXPIRED
    assert (await approvals.get(lazily)).status == ApprovalStatus.EXPIRED

    assert await approvals.sweep() == 1
    assert (await approvals.get(untouched)).status == ApprovalStatus.EXPIRED
    assert await approvals.sweep() == 0


async def test_c4_4_pending_exactly_at_expiry_is_not_decidable(approvals) -> None:
    """The boundary the CAS guard states: ``expires_at > now`` to decide, so a
    row whose ``expires_at`` equals ``now`` is already past it (§1's sweeper
    guard is the complement, ``expires_at <= now``). Without this the two guards
    could overlap and a row could be both decidable and sweepable."""
    aid = (await approvals.park(park_request())).approval_id

    approvals.clock.advance(hours=72)  # exactly expires_at

    conflict = await approvals.decide(aid, "approve")
    assert isinstance(conflict, StateConflict)
    assert conflict.error.current_status == ApprovalStatus.EXPIRED


# --------------------------------------------------------------------------- #
# C4 contract test 5 — exactly one decide wins
# --------------------------------------------------------------------------- #
async def test_c4_5_second_decide_loses(approvals) -> None:
    """C4 contract test 5 — two decides (sequential calls simulating the race) →
    exactly one wins, the second gets 409 and changes nothing. The genuinely
    concurrent, two-connection version of this is ``test_cas_race.py``."""
    aid = (await approvals.park(park_request())).approval_id

    first = await approvals.decide(aid, "approve")
    second = await approvals.decide(aid, "refuse")

    assert not isinstance(first, StateConflict)
    assert first.status == ApprovalStatus.APPROVED
    assert isinstance(second, StateConflict)
    assert second.error.current_status == ApprovalStatus.APPROVED
    assert (await approvals.get(aid)).status == ApprovalStatus.APPROVED


# --------------------------------------------------------------------------- #
# C4 contract test 6 — the webhook payload carries no params
# --------------------------------------------------------------------------- #
async def test_c4_6_webhook_payload_carries_no_params(approvals) -> None:
    """C4 contract test 6 — the ``approval.requested`` payload contains NO
    ``params_redacted`` key (redaction by shape, §2), and no params VALUE
    anywhere in it."""
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
    assert "demo" not in repr(payload)
    assert "continuation" not in payload


# --------------------------------------------------------------------------- #
# C4 contract test 7 — grace-bounded consume
# --------------------------------------------------------------------------- #
async def test_c4_7_stale_approved_is_not_consumable_after_grace(approvals) -> None:
    """C4 contract test 7 (Security review 2026-09-10 item 1) — park, approve,
    advance past the grace window, consume with the CORRECT binding →
    ``not_approved`` and the row is ``expired``; a second park+approve consumed
    within grace still succeeds."""
    stale_id = (await approvals.park(park_request())).approval_id
    await approvals.decide(stale_id, "approve")

    approvals.clock.advance(hours=1, seconds=1)
    stale = await approvals.consume(stale_id, binding=binding())
    assert (stale.ok, stale.reason) == (False, "not_approved")
    assert (await approvals.get(stale_id)).status == ApprovalStatus.EXPIRED

    fresh_id = (await approvals.park(park_request())).approval_id
    await approvals.decide(fresh_id, "approve")
    fresh = await approvals.consume(fresh_id, binding=binding())
    assert (fresh.ok, fresh.reason) == (True, "consumed")


async def test_c4_7_sweep_expires_a_stale_approved_row(approvals) -> None:
    """C4 contract test 7, second clause — ``sweep`` also expires a stale
    ``approved`` row it reaches first (§1's ``approved → expired`` transition)."""
    aid = (await approvals.park(park_request())).approval_id
    await approvals.decide(aid, "approve")

    approvals.clock.advance(hours=1, seconds=1)
    assert await approvals.sweep() == 1
    assert (await approvals.get(aid)).status == ApprovalStatus.EXPIRED
    assert await approvals.sweep() == 0


async def test_c4_7_approved_within_grace_survives_a_sweep(approvals) -> None:
    """The other side of the grace bound — ``decided_at + grace <= now`` is the
    sweep guard, so 59 minutes in is untouched and exactly 1 h in is swept."""
    inside = (await approvals.park(park_request())).approval_id
    await approvals.decide(inside, "approve")

    approvals.clock.advance(minutes=59)
    assert await approvals.sweep() == 0
    assert (await approvals.get(inside)).status == ApprovalStatus.APPROVED

    approvals.clock.advance(minutes=1)  # exactly at the boundary — inclusive
    assert await approvals.sweep() == 1
    assert (await approvals.get(inside)).status == ApprovalStatus.EXPIRED


async def test_c4_7_binding_mismatch_row_is_reaped_by_the_sweeper(approvals) -> None:
    """§1's ``approved → expired`` row also exists to catch ``binding_mismatch``
    rows nobody re-consumed — the exact sentence in the transition table. A
    mismatch must not burn the approval (test 3) AND must not leave it
    spendable for ever (this test)."""
    aid = (await approvals.park(park_request())).approval_id
    await approvals.decide(aid, "approve")
    mismatch = await approvals.consume(aid, binding=binding(tool="github"))
    assert mismatch.reason == "binding_mismatch"

    approvals.clock.advance(hours=1)
    assert await approvals.sweep() == 1
    assert (await approvals.get(aid)).status == ApprovalStatus.EXPIRED


# --------------------------------------------------------------------------- #
# C4 contract test 8 — fail-closed park material
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "kwargs",
    [
        {"continuation": {}},
        {"summary": ""},
        {"summary": "x" * 501},
    ],
    ids=["empty-continuation", "empty-summary", "over-long-summary"],
)
def test_c4_8_empty_park_material_is_rejected_by_the_model(kwargs: dict) -> None:
    """C4 contract test 8 (v1.1.0, F3) — the seam's own model refuses to mint a
    never-resumable approval. Implementation-independent by construction: the
    real service cannot relax it, because it is the constructor that refuses."""
    with pytest.raises(ValidationError):
        park_request(**kwargs)


async def test_c4_8_the_real_service_persists_the_continuation(approvals) -> None:
    """The service-side half of test 8: a parked approval's ``continuation`` is
    RETRIEVABLE, because C4 §1's restart-safety rule ("the park INSERT commits in
    the same transaction as the persisted continuation state") is worthless if
    the value is dropped on the floor. The fake keeps it in ``self.parked``; the
    real service persists it in the row and exposes it through
    ``continuation_for``."""
    parked = await approvals.park(park_request(continuation={"cursor": 7}))

    assert await approvals.service_continuation(parked.approval_id) == {"cursor": 7}
    # …and it never appears on the HTTP-facing row (C4 §4).
    row = await approvals.get(parked.approval_id)
    assert not hasattr(row, "continuation")


# --------------------------------------------------------------------------- #
# C4 §6.5 — listing, both readings QA pinned
# --------------------------------------------------------------------------- #
async def test_c4_listing_filters_orders_and_pages(approvals) -> None:
    """C4 §6.5 — filter by status, newest first, cursor = the last row's id."""
    ids = [(await approvals.park(park_request())).approval_id for _ in range(3)]
    await approvals.decide(ids[1], "approve")

    page = await approvals.list(status=ApprovalStatus.PENDING)
    assert [a.id for a in page.approvals] == [ids[2], ids[0]]
    assert page.next_cursor is None

    first = await approvals.list(limit=2)
    assert [a.id for a in first.approvals] == [ids[2], ids[1]]
    assert first.next_cursor == ids[1]

    second = await approvals.list(limit=2, cursor=first.next_cursor)
    assert [a.id for a in second.approvals] == [ids[0]]
    assert second.next_cursor is None


async def test_c4_listing_full_final_page_still_returns_a_cursor(approvals) -> None:
    """C4 §6.5 as QA pinned it (finding F8): ``next_cursor=None`` is specified
    for the SHORT page and nothing else, so an exactly-full final page still
    returns a cursor and the client learns it is done by asking once more."""
    ids = [(await approvals.park(park_request())).approval_id for _ in range(4)]

    first = await approvals.list(limit=2)
    assert [r.id for r in first.approvals] == [ids[3], ids[2]]
    assert first.next_cursor == ids[2]

    final = await approvals.list(limit=2, cursor=first.next_cursor)
    assert [r.id for r in final.approvals] == [ids[1], ids[0]]
    assert final.next_cursor == ids[0]  # full page, though nothing remains

    beyond = await approvals.list(limit=2, cursor=final.next_cursor)
    assert beyond.approvals == []
    assert beyond.next_cursor is None  # the short page is the terminator


async def test_c4_listing_unknown_cursor_is_rejected(approvals) -> None:
    """C4 §6.5 as the fake pins it — an unknown cursor raises rather than
    silently serving page one (the HTTP layer's 422). A cursor that resolves to
    nothing is a client bug; answering it with page 1 would make a paging loop
    restart for ever."""
    await approvals.park(park_request())

    with pytest.raises(ValueError):
        await approvals.list(cursor="apr-not-a-real-cursor")
