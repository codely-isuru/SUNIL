"""The `memories` reaper — R15's S2-C §7.4 row: expired rows are filtered out of
recall but were never deleted, so the store grew forever and a row whose TTL
expired in 2026 was still readable by anything that queried the table directly.

The runner mirrors `core/approvals/sweeper.py` — same injected `sleep`, same
contained tick — and DELIBERATELY DIFFERS in one way: it has no
startup-propagating leg. The approvals sweeper propagates its startup
reconciliation because that is a one-shot safety property ("never re-execute a
consumed approval"), and an API that booted having skipped it leaves interrupted
continuations looking runnable. Deletion has no such property: it is idempotent,
and C3's lazy TTL filter already guarantees an expired memory is never recalled.
So a reap missed at boot costs nothing that the next tick does not fix, while a
reaper that died on a transient blip would leak rows forever — contained tick,
and no startup leg to get the posture wrong with.

The double here grades the RUNNER (scheduling, containment, the audit call, the
kill switch). The SQL is graded against a real database in `test_reaper_sql.py`'s
Postgres leg, for the reason `test_sweeper.py` gives: two different jobs.
"""

from __future__ import annotations

import asyncio

import pytest

from sunil.core.memory.reaper import MemoryReaper


class RecordingStore:
    """Each `delete_expired` returns the next scripted count or raises the next
    scripted exception."""

    def __init__(self, results=None) -> None:
        self.results = list(results or [])
        self.calls = 0

    async def delete_expired(self) -> int:
        self.calls += 1
        outcome = self.results.pop(0) if self.results else 0
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


class RecordingAudit:
    """Captures the whole keyword payload, so a test can assert what the audit
    row is ALLOWED to contain as well as what it must."""

    def __init__(self) -> None:
        self.rows: list[dict] = []

    async def record_memory_reap(self, **payload) -> None:
        self.rows.append(payload)


async def test_run_once_returns_the_number_of_rows_deleted() -> None:
    store = RecordingStore(results=[4])
    reaper = MemoryReaper(store)

    assert await reaper.run_once() == 4
    assert store.calls == 1


async def test_a_reaped_batch_writes_one_audit_row_carrying_only_the_count() -> None:
    """The w2r3 condition, verbatim: an audit row per reap batch, **count only,
    never content**. A reaper that logged which memories it deleted would put the
    content of expired — often the most private — memories into the audit trail,
    which is the one place retention cannot then remove them from."""
    audit = RecordingAudit()
    reaper = MemoryReaper(RecordingStore(results=[7]), audit_sink=audit)

    await reaper.run_once()

    assert audit.rows == [{"deleted": 7}]


async def test_a_batch_that_deleted_nothing_writes_no_audit_row() -> None:
    """Most ticks delete nothing. A row per tick would bury the ones that matter
    in hourly noise — the trail records the EVENT (memories were destroyed), not
    the schedule."""
    audit = RecordingAudit()
    reaper = MemoryReaper(RecordingStore(results=[0]), audit_sink=audit)

    await reaper.run_once()

    assert audit.rows == []


async def test_a_failing_reap_does_not_propagate_and_is_reported() -> None:
    """Containment, the approvals sweeper's posture and its reasoning: a tick
    that propagated would kill the task and turn one transient database blip into
    a permanently dead reaper. Nothing else deletes these rows, so "dead reaper"
    is unbounded growth rather than a missed tick."""
    boom = RuntimeError("connection reset")
    seen: list[BaseException] = []
    reaper = MemoryReaper(RecordingStore(results=[boom]), on_error=seen.append)

    assert await reaper.run_once() == 0
    assert seen == [boom]


async def test_a_failed_reap_writes_no_audit_row() -> None:
    """An audit row saying zero memories were deleted, written because the delete
    FAILED, is a false statement about what happened."""
    audit = RecordingAudit()
    reaper = MemoryReaper(
        RecordingStore(results=[RuntimeError("blip")]),
        audit_sink=audit,
        on_error=lambda _e: None,
    )

    await reaper.run_once()

    assert audit.rows == []


async def test_the_loop_keeps_ticking_after_a_failed_reap() -> None:
    store = RecordingStore(results=[RuntimeError("blip"), 1, 0])
    done = asyncio.Event()

    async def fake_sleep(_seconds: float) -> None:
        if store.calls >= 3:
            done.set()
            await asyncio.sleep(3600)
        await asyncio.sleep(0)

    reaper = MemoryReaper(
        store, interval_s=0, sleep=fake_sleep, on_error=lambda _e: None
    )
    await reaper.start()
    await asyncio.wait_for(done.wait(), timeout=2)
    await reaper.stop()

    assert store.calls >= 3


async def test_start_has_no_propagating_leg_at_all() -> None:
    """The deliberate asymmetry with `ApprovalSweeper.start()`, asserted rather
    than described: a reaper whose very first reap fails still starts and still
    keeps its schedule. There is no one-shot safety property to protect here —
    deletion is idempotent and recall is already guarded by the lazy TTL filter —
    so a boot failure would be a new failure mode bought for nothing."""
    store = RecordingStore(results=[RuntimeError("no database"), 2])
    ticked = asyncio.Event()

    async def fake_sleep(_seconds: float) -> None:
        if store.calls >= 2:
            ticked.set()
            await asyncio.sleep(3600)
        await asyncio.sleep(0)

    reaper = MemoryReaper(
        store, interval_s=0, sleep=fake_sleep, on_error=lambda _e: None
    )

    await reaper.start()  # must not raise
    await asyncio.wait_for(ticked.wait(), timeout=2)
    await reaper.stop()

    assert store.calls >= 2


async def test_stop_is_idempotent_and_safe_before_start() -> None:
    """It runs from a lifespan shutdown, which also fires when startup failed
    half-way."""
    reaper = MemoryReaper(RecordingStore())
    await reaper.stop()
    await reaper.stop()


async def test_starting_twice_is_a_programming_error() -> None:
    """Two loops on one reaper is two schedules deleting the same rows — the same
    refusal `ApprovalSweeper` makes, for the same reason."""
    reaper = MemoryReaper(RecordingStore(), interval_s=0, sleep=_park)
    await reaper.start()
    try:
        with pytest.raises(RuntimeError, match="already started"):
            await reaper.start()
    finally:
        await reaper.stop()


async def _park(_seconds: float) -> None:
    await asyncio.sleep(3600)
