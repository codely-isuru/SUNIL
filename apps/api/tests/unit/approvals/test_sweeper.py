"""The scheduled runner around ``ApprovalsService.sweep`` — C4 §1's "TTL
sweeper (startup + every 60 s)".

``service.sweep()`` is the transition; this is the thing that *calls* it. The
distinction matters because ``ARCHITECTURE_V2.md`` §8's failure table says
"approvals sweeper missed → lazy expiry at read/decide covers it": the runner is
allowed to miss a tick, and is NOT allowed to die on one. Every test below is
that sentence made executable.

The double is local and deliberate: these tests grade the runner's scheduling
and error containment, not the service's SQL (which ``test_real_service_contract``
and ``test_cas_race`` already grade against a real database).
"""

from __future__ import annotations

import asyncio

import pytest

from sunil.core.approvals.service import ReconciliationReport
from sunil.core.approvals.sweeper import ApprovalSweeper

from tests.fakes.clock import FakeClock
from tests.unit.approvals import factory
from tests.unit.approvals.test_real_service_contract import park_request


class RecordingService:
    """Records calls; each ``sweep`` returns the next scripted value or raises
    the next scripted exception."""

    def __init__(self, results=None, reconcile_error: Exception | None = None):
        self.results = list(results or [])
        self.sweeps = 0
        self.reconciles = 0
        self.reconcile_error = reconcile_error

    async def sweep(self) -> int:
        self.sweeps += 1
        outcome = self.results.pop(0) if self.results else 0
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    async def reconcile_on_startup(self) -> ReconciliationReport:
        self.reconciles += 1
        if self.reconcile_error is not None:
            raise self.reconcile_error
        return ReconciliationReport()


async def test_run_once_returns_the_services_transition_count() -> None:
    service = RecordingService(results=[3])
    sweeper = ApprovalSweeper(service)

    assert await sweeper.run_once() == 3
    assert service.sweeps == 1


async def test_a_failing_sweep_does_not_propagate_and_is_reported() -> None:
    """§8's failure row: a missed sweep is covered by lazy expiry at
    read/decide. A sweep that raised out of the loop would take the runner with
    it and turn a transient database blip into a permanently dead sweeper —
    which is the one failure lazy expiry cannot paper over forever, because
    ``approved``-past-grace rows are only reaped here or at consume."""
    boom = RuntimeError("connection reset")
    service = RecordingService(results=[boom])
    seen: list[BaseException] = []
    sweeper = ApprovalSweeper(service, on_error=seen.append)

    assert await sweeper.run_once() == 0
    assert seen == [boom]


async def test_start_reconciles_once_before_the_first_sweep() -> None:
    """C4 §3 / ADR-031: the startup reconciliation runs BEFORE any sweep, and
    exactly once per start — a consumed-but-unfinalised continuation must be
    failed before the sweeper starts changing rows underneath it."""
    order: list[str] = []
    service = RecordingService()
    original_sweep = service.sweep
    original_reconcile = service.reconcile_on_startup

    async def sweep():
        order.append("sweep")
        return await original_sweep()

    async def reconcile():
        order.append("reconcile")
        return await original_reconcile()

    service.sweep = sweep
    service.reconcile_on_startup = reconcile

    ticks = asyncio.Event()

    async def fake_sleep(_seconds: float) -> None:
        ticks.set()
        await asyncio.sleep(3600)  # park until cancelled

    sweeper = ApprovalSweeper(service, interval_s=60, sleep=fake_sleep)
    await sweeper.start()
    await asyncio.wait_for(ticks.wait(), timeout=2)
    await sweeper.stop()

    assert order[:2] == ["reconcile", "sweep"]
    assert service.reconciles == 1


async def test_the_loop_keeps_ticking_after_a_failed_sweep() -> None:
    """The containment guarantee at loop level, not just at ``run_once``."""
    service = RecordingService(results=[RuntimeError("blip"), 1, 0])
    done = asyncio.Event()

    async def fake_sleep(_seconds: float) -> None:
        if service.sweeps >= 3:
            done.set()
            await asyncio.sleep(3600)
        await asyncio.sleep(0)

    sweeper = ApprovalSweeper(service, interval_s=0, sleep=fake_sleep,
                              on_error=lambda _e: None)
    await sweeper.start()
    await asyncio.wait_for(done.wait(), timeout=2)
    await sweeper.stop()

    assert service.sweeps >= 3


async def test_a_failing_startup_reconciliation_is_not_swallowed() -> None:
    """The opposite posture to a failed sweep, on purpose. A sweep is a
    recurring best-effort; the reconciliation is a one-shot safety property
    ("never re-execute a consumed approval"). Booting an API that silently
    skipped it would leave interrupted continuations looking runnable."""
    service = RecordingService(reconcile_error=RuntimeError("no database"))
    sweeper = ApprovalSweeper(service)

    with pytest.raises(RuntimeError, match="no database"):
        await sweeper.start()
    assert service.sweeps == 0


async def test_stop_is_idempotent_and_safe_before_start() -> None:
    """``stop()`` runs from a FastAPI lifespan shutdown, which also fires when
    startup failed half-way. It must not raise there."""
    sweeper = ApprovalSweeper(RecordingService())
    await sweeper.stop()
    await sweeper.stop()


# --------------------------------------------------------------------------- #
# The seam against the REAL service
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("url", factory.engine_urls(), ids=factory.label)
async def test_the_runner_drives_the_real_service_on_a_real_database(url) -> None:
    """``Sweepable`` is a structural Protocol, so a signature drift between the
    runner and ``DatabaseApprovalsService`` would only surface at runtime — in
    production, at 60-second intervals, on the path that expires approvals. This
    test is that wiring, exercised end to end: park a row, move the clock past
    its TTL, and let the RUNNER (not the service) expire it."""
    async for engine in factory.engine_for(url):
        clock = FakeClock()
        service = factory.make_service(engine, clock=clock.now, ttl_hours=72)
        parked = await service.park(park_request())
        clock.advance(hours=73)

        sweeper = ApprovalSweeper(service, interval_s=0)
        assert await sweeper.run_once() == 1
        assert (await service.get(parked.approval_id)).status == "expired"
        # C4 §6.4: a second sweep over the same rows matches nothing.
        assert await sweeper.run_once() == 0
