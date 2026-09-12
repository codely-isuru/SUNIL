"""C4 §3's startup reconciliation — the three rules, and the never-re-execute
guarantee (Security review 2026-09-10 items 1–2).

Rule 3 is the security condition in this file: a ``consumed`` approval whose
task never finalised means the process died between the consume CAS and task
finalisation. The tool call may or may not have fired. The reconciliation
therefore finalises the task ``failed`` / ``continuation_interrupted`` and
**never re-executes** — because the consume CAS is spent, and single-use is
precisely the property that has to survive a crash. The test that matters most
here is the negative one: the continuation scheduler must not be called for a
``consumed`` row, ever.
"""

from __future__ import annotations

from datetime import timedelta

import pytest

from sunil.core.approvals.base import ApprovalStatus
from sunil.core.approvals.service import (
    AUDIT_RECONCILED,
    FAILURE_APPROVAL_EXPIRED,
    FAILURE_CONTINUATION_INTERRUPTED,
)

from tests.fakes.clock import FakeClock
from tests.unit.approvals import factory
from tests.unit.approvals.test_real_service_contract import binding, park_request


class RecordingTasks:
    """A stand-in for the spine's task gateway (C4 §3's two questions)."""

    def __init__(self, finalised: set[str] | None = None) -> None:
        self.finalised: set[str] = set(finalised or ())
        self.calls: list[tuple[str, str]] = []

    async def is_finalised(self, task_id: str) -> bool:
        return task_id in self.finalised

    async def finalise_failed(self, task_id: str, *, failure_kind: str) -> None:
        self.calls.append((task_id, failure_kind))
        self.finalised.add(task_id)


class RecordingScheduler:
    """ADR-031's resume path, recorded rather than run."""

    def __init__(self) -> None:
        self.scheduled: list[str] = []

    async def schedule(self, approval_id: str) -> None:
        self.scheduled.append(approval_id)


class RecordingAudit:
    def __init__(self) -> None:
        self.rows: list[dict] = []

    async def record(self, *, kind, approval_id, detail, conn=None) -> None:
        self.rows.append({"kind": kind, "approval_id": approval_id, "detail": detail})

    def kinds_for(self, approval_id: str) -> list[str]:
        return [r["kind"] for r in self.rows if r["approval_id"] == approval_id]


@pytest.fixture(params=[pytest.param(u, id=factory.label(u)) for u in factory.engine_urls()])
async def wired(request):
    engine = await factory.make_engine(request.param)
    clock = FakeClock()
    tasks = RecordingTasks()
    scheduler = RecordingScheduler()
    audit = RecordingAudit()
    try:
        service = factory.make_service(
            engine, clock=clock.now, tasks=tasks, scheduler=scheduler, audit=audit
        )
        yield service, clock, tasks, scheduler, audit
    finally:
        await engine.dispose()


async def _park(service, clock, task_id: str) -> str:
    req = park_request()
    parked = await service.park(req.model_copy(update={"task_id": task_id}))
    clock.advance(seconds=1)
    return parked.approval_id


# --------------------------------------------------------------------------- #
# Rule 1 — approved + unfinalised task + within grace → re-schedule
# --------------------------------------------------------------------------- #
async def test_rule_1_reschedules_an_approved_row_within_grace(wired) -> None:
    """C4 §3 rule 1 (ADR-031, unchanged) — the crash-during-resume case an
    approval is *supposed* to survive: the owner said yes, the process died
    before the continuation ran, the grace window is still open, so the
    continuation is re-scheduled and the approval stays consumable."""
    service, clock, tasks, scheduler, audit = wired
    approval_id = await _park(service, clock, "task-live")
    await service.decide(approval_id, "approve")
    clock.advance(minutes=30)  # inside the 1 h grace

    report = await service.reconcile_on_startup()

    assert report.rescheduled == [approval_id]
    assert scheduler.scheduled == [approval_id]
    assert tasks.calls == []
    assert (await service.get(approval_id)).status == ApprovalStatus.APPROVED


async def test_rule_1_skips_an_approved_row_whose_task_is_already_finalised(
    wired,
) -> None:
    """A finalised task has nothing to resume into. Re-scheduling it would run
    a continuation whose task is already closed, appending work to a finished
    story."""
    service, clock, tasks, scheduler, _ = wired
    approval_id = await _park(service, clock, "task-done")
    await service.decide(approval_id, "approve")
    tasks.finalised.add("task-done")

    report = await service.reconcile_on_startup()

    assert report.rescheduled == []
    assert scheduler.scheduled == []


# --------------------------------------------------------------------------- #
# Rule 2 — approved past grace → expired + task failed approval_expired
# --------------------------------------------------------------------------- #
async def test_rule_2_expires_a_stale_approved_row_and_fails_its_task(wired) -> None:
    """C4 §3 rule 2 (Security review item 1) — the downtime case: an approval
    decided before a long outage must not be silently spendable when the
    process comes back. It expires, and its task is finalised
    ``approval_expired``; the continuation is NOT scheduled."""
    service, clock, tasks, scheduler, audit = wired
    approval_id = await _park(service, clock, "task-stale")
    await service.decide(approval_id, "approve")
    clock.advance(hours=2)  # well past the 1 h grace

    report = await service.reconcile_on_startup()

    assert report.expired == [approval_id]
    assert report.rescheduled == []
    assert scheduler.scheduled == []
    assert tasks.calls == [("task-stale", FAILURE_APPROVAL_EXPIRED)]
    assert (await service.get(approval_id)).status == ApprovalStatus.EXPIRED
    assert "approval_expired" in audit.kinds_for(approval_id)


async def test_rule_2_runs_before_rule_1_so_a_stale_row_is_never_resumed(
    wired,
) -> None:
    """Ordering is load-bearing, not incidental. If rule 1 read the approved
    rows first it would hand a stale approval to the scheduler, and the
    continuation would then fail its consume CAS on the grace bound — a
    pointless resume that also finalises the task twice. Rule 2 therefore
    transitions the stale rows before rule 1 looks."""
    service, clock, tasks, scheduler, _ = wired
    stale = await _park(service, clock, "task-stale")
    live = await _park(service, clock, "task-live")
    await service.decide(stale, "approve")
    clock.advance(hours=2)
    await service.decide(live, "approve")

    report = await service.reconcile_on_startup()

    assert report.expired == [stale]
    assert report.rescheduled == [live]
    assert scheduler.scheduled == [live]


# --------------------------------------------------------------------------- #
# Rule 3 — consumed + unfinalised task → failed, and NEVER re-executed
# --------------------------------------------------------------------------- #
async def test_rule_3_finalises_an_interrupted_continuation(wired) -> None:
    """C4 §3 rule 3 — ``consumed`` + unfinalised task → task finalised
    ``failed`` with ``failure.kind="continuation_interrupted"`` plus an
    ``audit_events`` row of kind ``continuation_reconciled``."""
    service, clock, tasks, scheduler, audit = wired
    approval_id = await _park(service, clock, "task-crashed")
    await service.decide(approval_id, "approve")
    await service.consume(approval_id, binding=binding())

    report = await service.reconcile_on_startup()

    assert report.interrupted == [approval_id]
    assert tasks.calls == [("task-crashed", FAILURE_CONTINUATION_INTERRUPTED)]
    assert AUDIT_RECONCILED in audit.kinds_for(approval_id)


async def test_rule_3_never_re_executes_the_approved_call(wired) -> None:
    """**The security condition.** A ``consumed`` approval is spent; the tool
    call may already have fired. Re-scheduling the continuation would turn a
    crash into a duplicate privileged side effect — the single outcome an
    approval exists to prevent — so the scheduler must never see a consumed row,
    and the reconciliation must not resurrect the approval's status either."""
    service, clock, tasks, scheduler, audit = wired
    approval_id = await _park(service, clock, "task-crashed")
    await service.decide(approval_id, "approve")
    await service.consume(approval_id, binding=binding())

    await service.reconcile_on_startup()

    assert scheduler.scheduled == []
    assert (await service.get(approval_id)).status == ApprovalStatus.CONSUMED
    # The audit row records the decision not to re-run, so the reason is
    # legible in the trail rather than only in this test.
    row = next(r for r in audit.rows if r["kind"] == AUDIT_RECONCILED)
    assert row["detail"]["re_executed"] is False
    assert row["detail"]["failure_kind"] == FAILURE_CONTINUATION_INTERRUPTED


async def test_rule_3_leaves_a_finalised_task_alone(wired) -> None:
    """The normal, non-crash case: consume happened, the continuation finished,
    the task is finalised. Reconciliation must do nothing — otherwise every
    clean restart would rewrite completed tasks as failed."""
    service, clock, tasks, scheduler, audit = wired
    approval_id = await _park(service, clock, "task-ok")
    await service.decide(approval_id, "approve")
    await service.consume(approval_id, binding=binding())
    tasks.finalised.add("task-ok")

    report = await service.reconcile_on_startup()

    assert report.interrupted == []
    assert tasks.calls == []
    assert AUDIT_RECONCILED not in audit.kinds_for(approval_id)


async def test_reconciliation_is_idempotent(wired) -> None:
    """Two boots in a row (a crash loop) must not double-finalise or
    double-audit anything: the second pass sees the tasks finalised and the
    stale rows already expired."""
    service, clock, tasks, scheduler, audit = wired
    stale = await _park(service, clock, "task-stale")
    spent = await _park(service, clock, "task-crashed")
    await service.decide(stale, "approve")
    await service.decide(spent, "approve")
    await service.consume(spent, binding=binding())
    clock.advance(hours=2)

    first = await service.reconcile_on_startup()
    second = await service.reconcile_on_startup()

    assert first.total == 2
    assert second.total == 0
    assert len(tasks.calls) == 2


# --------------------------------------------------------------------------- #
# The sweeper's task-finalisation side (C4 §1)
# --------------------------------------------------------------------------- #
async def test_sweeping_a_pending_row_finalises_its_task_as_expired(wired) -> None:
    """C4 §1's TTL row: "(task finalised: failure.kind=approval_expired)". The
    sweeper is the only thing that notices an approval nobody answered, so it
    owns telling the task."""
    service, clock, tasks, _, _ = wired
    approval_id = await _park(service, clock, "task-ignored")
    clock.advance(hours=73)

    assert await service.sweep() == 1

    assert tasks.calls == [("task-ignored", FAILURE_APPROVAL_EXPIRED)]
    assert (await service.get(approval_id)).status == ApprovalStatus.EXPIRED


async def test_refusal_finalises_the_task_as_refused(wired) -> None:
    """C4 §3 — refuse → no execution, task finalised ``failed`` with
    ``failure.kind="approval_refused"``."""
    service, clock, tasks, scheduler, _ = wired
    approval_id = await _park(service, clock, "task-refused")

    await service.decide(approval_id, "refuse", "not this time")
    await service.finalise_refusal(approval_id)

    assert tasks.calls == [("task-refused", "approval_refused")]
    assert scheduler.scheduled == []
    row = await service.get(approval_id)
    assert row.status == ApprovalStatus.REFUSED
    assert row.decision_reason == "not this time"


async def test_grace_window_boundary_is_exclusive_for_resume(wired) -> None:
    """The boundary C4 §1 states twice and in opposite directions: consume
    needs ``decided_at + grace > now`` (exclusive) while expiry triggers on
    ``decided_at + grace <= now`` (inclusive). At exactly the boundary the row
    must expire, not resume — otherwise a row could be both."""
    service, clock, tasks, scheduler, _ = wired
    approval_id = await _park(service, clock, "task-boundary")
    await service.decide(approval_id, "approve")
    clock.advance(hours=1)  # exactly decided_at + grace

    report = await service.reconcile_on_startup()

    assert report.expired == [approval_id]
    assert report.rescheduled == []
    assert scheduler.scheduled == []
    assert tasks.calls == [("task-boundary", FAILURE_APPROVAL_EXPIRED)]
    assert timedelta(hours=1) == timedelta(hours=service.config.consume_grace_hours)
