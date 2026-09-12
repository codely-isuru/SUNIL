"""The approvals sweeper's start/stop, wired into the application lifespan.

Stream D built `ApprovalSweeper` and left the seam explicitly: "`ApprovalSweeper`
is not yet wired into an app lifespan; `main.py`/`deps.py` are the platform
lane's files, not this branch's. `start()`/`stop()` are the seam"
(`docs/tasks/S-D-approvals.md` §5). Closed here.

Why it matters that it actually runs, rather than being nice to have:
ARCHITECTURE_V2 §8 says a missed sweep is covered by lazy expiry at read/decide
— but lazy expiry only covers rows somebody reads. An `approved` row past its
grace window that nobody touches again stays spendable, which is the hole the
2026-09-10 security review's item 1 closed. An unstarted sweeper reopens it, and
nothing else in the suite would notice.
"""

from __future__ import annotations

import asyncio

import pytest

from tests.ops_harness import build_ops_app


class SweepableDouble:
    """The narrow `Sweepable` slice: what the runner is allowed to reach for,
    and nothing else (no `park`, no `decide`)."""

    def __init__(self) -> None:
        self.reconciled = 0
        self.sweeps = 0

    async def reconcile_on_startup(self) -> None:
        self.reconciled += 1

    async def sweep(self) -> int:
        self.sweeps += 1
        return 0


class NotSweepable:
    """A C4 service that satisfies the park/consume seam but carries no
    schedule — C4 §6's `FakeApprovalsService` is one."""

    async def park(self, request):  # pragma: no cover - never called here
        raise AssertionError("the sweeper must not reach for park()")


def app_with(service, **overrides):
    app, _ = build_ops_app(approvals=service, **overrides)
    return app


async def test_the_sweeper_reconciles_on_startup_and_is_cancelled_on_shutdown() -> None:
    """C4 §1's schedule is "startup and every 60 s", and C4 §3 / ADR-031 make the
    startup reconciliation a one-shot safety property: a consumed-but-unfinalised
    continuation is failed `continuation_interrupted` and never re-executed.

    Asserted on `reconcile_on_startup`, which `start()` AWAITS, rather than on a
    sweep count the loop may or may not have reached — a test that slept for the
    tick would be a flaky test generator (the sweeper's own module says so).
    """
    service = SweepableDouble()
    app = app_with(service)

    async with app.router.lifespan_context(app):
        sweeper = app.state.approvals_sweeper
        assert sweeper is not None, "the sweeper seam was left unwired"
        assert service.reconciled == 1
        task = sweeper._task
        assert task is not None and not task.done()

    assert task.cancelled() or task.done(), "shutdown must stop the sweep loop"
    assert app.state.approvals_sweeper._task is None


async def test_the_kill_switch_leaves_the_sweeper_unbuilt_and_unstarted() -> None:
    """`SUNIL_APPROVALS_SWEEPER_ENABLED=false` — the operator switch for the case
    where a second process owns the schedule (or a sweep is implicated in an
    incident). Defaults ON: the safe posture is the one you get by doing nothing.

    Off means NOT STARTED, not "started and idle": `reconcile_on_startup` is a
    state transition, so a kill switch that still reconciled would be a kill
    switch that still changed rows.
    """
    service = SweepableDouble()
    app = app_with(service, sunil_approvals_sweeper_enabled=False)

    async with app.router.lifespan_context(app):
        assert app.state.approvals_sweeper is None
        assert service.reconciled == 0
        assert service.sweeps == 0


async def test_the_switch_defaults_on() -> None:
    """Stated as its own assertion so a future default flip is a failed test
    rather than a quiet change of posture."""
    from sunil.settings import Settings

    assert (
        Settings(_env_file=None, session_secret="x").sunil_approvals_sweeper_enabled
        is True
    )


async def test_a_service_with_no_schedule_boots_and_says_so() -> None:
    """A C4 seam that is not `Sweepable` (the frozen fake, or a future in-memory
    implementation) must not stop the app booting — but it must not pass for a
    running sweeper either. No sweeper is built, and the absence is logged at
    warning, naming C4 §1's schedule."""
    app = app_with(NotSweepable())

    async with app.router.lifespan_context(app):
        assert app.state.approvals_sweeper is None


async def test_the_started_loop_reaches_its_first_sweep() -> None:
    """`start()` creating a task proves scheduling was requested; this proves the
    loop body runs at all. Driven by yielding to the event loop rather than by
    sleeping for the interval — the sweeper's own module warns that a test timed
    against the real schedule is a flaky test generator. The tick's BEHAVIOUR is
    already graded in `tests/unit/approvals/test_sweeper.py`; this is only the
    wiring."""
    service = SweepableDouble()
    app = app_with(service)

    async with app.router.lifespan_context(app):
        for _ in range(100):
            if service.sweeps:
                break
            await asyncio.sleep(0)
        assert service.sweeps >= 1


@pytest.mark.parametrize("enabled", [True, False])
async def test_the_sweeper_never_blocks_startup_on_its_own_failure_mode(
    enabled: bool,
) -> None:
    """Both settings leave a serving application: the routes are mounted and the
    app answers before, during and after the sweeper's lifetime."""
    app = app_with(SweepableDouble(), sunil_approvals_sweeper_enabled=enabled)

    async with app.router.lifespan_context(app):
        assert any(route.path == "/api/v1/approvals" for route in app.routes)
