"""Security wave-1 condition **C-1**, at the chokepoint: the consume CAS and the
`tool_calls` attempt row commit in ONE transaction, in production wiring.

`tests/unit/approvals/test_consume_audit_transaction.py` proves the C4 SEAM is
atomic in both directions. C-1's finding is that the seam had **zero production
callers**: `core/tool_framework/manager.py` called `consume()` with no
`attempt_audit`, and the attempt row was written at step 4 by
`core/audit/hooks.py`, which commits in its own session. Same on the park path.

So this module is the missing half — the same property asserted through the REAL
`ToolManager`, the REAL `DatabaseApprovalsService` and the REAL
`DbToolAuditHook`, on one engine. Everything here is production code except the
adapter and the permission grant.

The two states C-1 names, and how each is made unreachable:

* **spent but unrecorded** — the approval is `consumed` and a privileged call may
  have fired, with no `tool_calls` row saying what was attempted. C4 §3's
  reconciliation rule 3 leans on that row existing ("the C1 §2.1 step-4 attempt
  row … is the record of what was attempted"), and it is the only record a crash
  leaves behind. Injecting a crash exactly where the old code's window was — after
  the consume commits, before the attempt write — can no longer produce it,
  because there is no longer a moment at which the consume is committed and the
  row is not.
* **recorded but unspent** — an attempt row for a call no approval authorised.
  Ruled out in the other direction: the callback runs only after the CAS matched,
  inside its transaction.

The park path gets the same treatment via `park(conn=…)`: C4 §1's restart-safety
rule already required the continuation to commit with the row, and C1 §2.1 step 4
adds the attempt row to that transaction.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker
from sqlalchemy.pool import StaticPool

from sunil.core.approvals.table import approvals_table
from sunil.core.audit.hooks import DbToolAuditHook
from sunil.core.tool_framework.base import (
    ParkContext,
    ToolErrorKind,
    TraceContext,
)
from sunil.core.tool_framework.manager import ToolManager
from sunil.core.tool_framework.transaction import TransactionalApprovals
from sunil.db.base import Base
from sunil.db.models import ToolCall

from tests.fakes.clock import FakeClock
from tests.fakes.fake_hooks import FakePermissionHook
from tests.fakes.fake_tool_adapter import FakeToolAdapter
from tests.unit.approvals import factory

TRACE = TraceContext(request_id="req-1", task_id="task-1", conversation_id="conv-1")
PARK = ParkContext(summary="fake_tool.write_item requires approval", continuation={"cursor": 1})
AGENT = "project_manager"


class AuditWriteFailed(RuntimeError):
    """What a crashed audit write looks like from inside the transaction."""


class _CrashingAudit(DbToolAuditHook):
    """The real hook, with the in-transaction write replaced by a crash.

    This is the injected fault C-1 describes: the process dies between the
    consume commit and the attempt write. Under the OLD wiring those were two
    transactions, so the consume stood and the row never existed. Under this one
    there is nothing to crash between.
    """

    async def attempt_on(self, conn, record) -> str:  # type: ignore[override]
        raise AuditWriteFailed("audit sink unavailable")


@pytest.fixture(params=[pytest.param(u, id=factory.label(u)) for u in factory.engine_urls()])
async def wired(request):
    """The real chokepoint over one engine carrying BOTH schemas."""
    engine = await factory.make_engine(request.param)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    sessionmaker = async_sessionmaker(engine, expire_on_commit=False)
    approvals = factory.make_service(engine, clock=FakeClock().now)
    try:
        yield _Wiring(engine=engine, sessionmaker=sessionmaker, approvals=approvals)
    finally:
        await engine.dispose()


class _Wiring:
    def __init__(self, *, engine, sessionmaker, approvals) -> None:
        self.engine = engine
        self.sessionmaker = sessionmaker
        self.approvals = approvals
        self.adapter = FakeToolAdapter()
        self.permissions = FakePermissionHook()
        self.permissions.grant(AGENT, "fake_tool", "write_item", "ask_user")

    def manager(self, *, audit_class=DbToolAuditHook) -> ToolManager:
        audit = audit_class(self.sessionmaker, validated_plan_id="plan-1")
        return ToolManager(
            [self.adapter],
            self.permissions,
            self.approvals,
            audit,
            transaction=TransactionalApprovals(approvals=self.approvals, audit=audit),
        )

    async def execute(self, *, approval: str | None = None, audit_class=DbToolAuditHook):
        return await self.manager(audit_class=audit_class).execute(
            AGENT,
            "fake_tool",
            "write_item",
            {"key": "k", "value": "v"},
            trace=TRACE,
            approval=approval,
            park_context=None if approval else PARK,
        )

    async def tool_calls(self) -> list[ToolCall]:
        async with self.sessionmaker() as session:
            rows = (await session.execute(select(ToolCall))).scalars().all()
        return list(rows)

    async def approval_rows(self) -> list:
        async with self.engine.connect() as conn:
            return list(
                (
                    await conn.execute(
                        select(approvals_table.c.id, approvals_table.c.status)
                    )
                ).fetchall()
            )

    async def park(self) -> str:
        parked = await self.execute()
        assert parked.error_kind == ToolErrorKind.APPROVAL_REQUIRED.value
        return (await self.tool_calls())[0].approval_id


# --------------------------------------------------------------------------- #
# The continuation path — C1 §2.1 step 4's transactional rule
# --------------------------------------------------------------------------- #
async def test_a_continuation_writes_exactly_one_attempt_row_and_consumes(wired) -> None:
    """The happy path, and the "step 4 skips the duplicate" half of the fix: the
    attempt row is written by the consume transaction, so the pipeline must not
    write a SECOND one immediately after. One execute, one attempt row."""
    approval_id = await wired.park()
    await wired.approvals.decide(approval_id, "approve")

    result = await wired.execute(approval=approval_id)

    assert result.ok, result.error_message
    rows = await wired.tool_calls()
    continuation = [row for row in rows if row.outcome == "ok"]
    assert len(continuation) == 1
    assert continuation[0].approval_id == approval_id
    assert continuation[0].permission_decision == "ask_user"
    assert continuation[0].validated_plan_id == "plan-1"
    assert [r.status for r in await wired.approval_rows()] == ["consumed"]


async def test_a_crash_where_the_old_window_was_cannot_spend_the_approval(wired) -> None:
    """**The C-1 regression test.** The injected fault is exactly the crash the
    condition describes — between the consume commit and the attempt write.

    Under the old wiring (`consume()` with no `attempt_audit`, the row written
    afterwards by a hook that commits in its own session) this left the approval
    `consumed` with no `tool_calls` row: spent but unrecorded, and C4 §3's
    reconciliation rule 3 would then finalise the task on a record that does not
    exist. Now the write is inside the CAS's transaction, so the same fault rolls
    the consume back with it: nothing spent, nothing recorded, and the owner's
    single-use approval is still theirs to spend.

    The failure propagates rather than becoming a `ToolResult`: the pipeline
    cannot record this outcome — the audit trail is what just failed — and a
    swallowed error would leave the manager believing it holds an authorisation
    it does not.
    """
    approval_id = await wired.park()
    await wired.approvals.decide(approval_id, "approve")
    rows_before = len(await wired.tool_calls())

    with pytest.raises(AuditWriteFailed):
        await wired.execute(approval=approval_id, audit_class=_CrashingAudit)

    assert [r.status for r in await wired.approval_rows()] == ["approved"]
    assert len(await wired.tool_calls()) == rows_before
    # …and because nothing burned, the real continuation still succeeds.
    retry = await wired.execute(approval=approval_id)
    assert retry.ok
    assert [r.status for r in await wired.approval_rows()] == ["consumed"]


async def test_a_failed_consume_writes_no_attempt_row_through_the_callback(wired) -> None:
    """The other direction — recorded but unspent. A binding the approval does
    not match must leave the callback unrun; the early-exit row the pipeline then
    writes is the `approval_invalid` one, not an attempt for an authorised call.
    """
    approval_id = await wired.park()
    await wired.approvals.decide(approval_id, "approve")

    result = await wired.manager().execute(
        AGENT,
        "fake_tool",
        "write_item",
        {"key": "k", "value": "DIFFERENT"},
        trace=TRACE,
        approval=approval_id,
    )

    assert result.error_kind == ToolErrorKind.APPROVAL_INVALID.value
    assert [r.status for r in await wired.approval_rows()] == ["approved"]
    assert [row.outcome for row in await wired.tool_calls() if row.approval_id] == [
        "error",
        "error",
    ]


# --------------------------------------------------------------------------- #
# The park path — C1 §2.1 step 4's park clause, C4 §1's restart safety
# --------------------------------------------------------------------------- #
async def test_the_park_and_its_attempt_row_commit_together(wired) -> None:
    """A park writes the approval (with its continuation) and the attempt row
    naming the minted id, and both are visible once `execute` returns."""
    result = await wired.execute()

    assert result.error_kind == ToolErrorKind.APPROVAL_REQUIRED.value
    parked = await wired.approval_rows()
    rows = await wired.tool_calls()
    assert [r.status for r in parked] == ["pending"]
    assert len(rows) == 1
    assert rows[0].approval_id == parked[0].id
    assert rows[0].outcome == "error"  # finalised with approval_required


async def test_a_crash_writing_the_park_attempt_row_leaves_no_approval(wired) -> None:
    """C-1's park half. The approval INSERT and the attempt row share the park
    transaction, so a failure writing the row cannot leave a parked approval the
    trail has no attempt for — an approval the owner could approve, for a call
    `tool_calls` never recorded anyone making."""
    with pytest.raises(AuditWriteFailed):
        await wired.execute(audit_class=_CrashingAudit)

    assert await wired.approval_rows() == []
    assert await wired.tool_calls() == []


async def test_the_number_of_attempt_rows_is_the_number_of_execute_calls(wired) -> None:
    """The duplicate-suppression claim, counted end to end: park + continuation
    is two `execute` calls and therefore exactly two `tool_calls` rows — not
    three, which is what a step 4 that still ran after a transactional consume
    would produce."""
    approval_id = await wired.park()
    await wired.approvals.decide(approval_id, "approve")
    await wired.execute(approval=approval_id)

    async with wired.sessionmaker() as session:
        count = (await session.execute(select(func.count()).select_from(ToolCall.__table__))).scalar_one()

    assert count == 2
