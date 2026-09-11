"""Security review condition: the consume CAS and the attempt-audit row commit
in ONE transaction (C1 §2.1 step 4, Security review 2026-09-10 item 3).

C1 §2.1 step 4's transactional rule: "on the continuation path the attempt row
MUST commit in the same DB transaction as the consume CAS of step 3". The fakes
"assert ordering, not atomicity" — so atomicity is exactly what has no coverage
anywhere else, and it is a security condition rather than a nicety: the two
failure modes it rules out are

* **spent but unrecorded** — the approval is ``consumed`` and a privileged call
  may have fired, with no ``tool_calls`` attempt row to say what was attempted.
  The reconciliation (C4 §3 rule 3) explicitly leans on that row existing:
  "the two-phase audit attempt row is the record of what was attempted".
* **recorded but unspent** — an attempt row for a call the approval never
  authorised, which would make the audit trail claim a side effect that an
  owner's single-use approval had not been spent on.

The seam is proved by writing into the SAME table through the callback's
connection and then checking, from a FRESH connection, that the approval status
and the audit row agree in every case — visibility from outside the transaction
is the only thing that distinguishes "one transaction" from "two".
"""

from __future__ import annotations

import pytest
from sqlalchemy import Column, MetaData, String, Table, select

from sunil.core.approvals.base import ApprovalStatus

from tests.fakes.clock import FakeClock
from tests.unit.approvals import factory
from tests.unit.approvals.test_real_service_contract import binding, park_request

#: A stand-in for the spine's `tool_calls` attempt row: its own metadata, so
#: this test needs no spine module (Stream D worktree rule).
ATTEMPTS_METADATA = MetaData()
attempts = Table(
    "stream_d_attempt_probe",
    ATTEMPTS_METADATA,
    Column("id", String(64), primary_key=True),
    Column("approval_id", String(64), nullable=False),
)


class AuditWriteFailed(RuntimeError):
    """What a real audit writer raises when the insert fails."""


@pytest.fixture(params=[pytest.param(u, id=factory.label(u)) for u in factory.engine_urls()])
async def wired(request):
    engine = await factory.make_engine(request.param)
    async with engine.begin() as conn:
        await conn.run_sync(ATTEMPTS_METADATA.drop_all)
        await conn.run_sync(ATTEMPTS_METADATA.create_all)
    try:
        yield factory.make_service(engine, clock=FakeClock().now), engine
    finally:
        await engine.dispose()


async def _approved(service):
    parked = await service.park(park_request())
    await service.decide(parked.approval_id, "approve")
    return parked.approval_id


async def _attempt_rows(engine, approval_id: str) -> list[str]:
    async with engine.connect() as conn:
        return [
            row.id
            for row in (
                await conn.execute(
                    select(attempts.c.id).where(attempts.c.approval_id == approval_id)
                )
            ).fetchall()
        ]


async def test_attempt_row_and_consume_commit_together(wired) -> None:
    """The success path: both land, and both are visible from outside."""
    service, engine = wired
    approval_id = await _approved(service)

    async def attempt_audit(conn) -> None:
        await conn.execute(
            attempts.insert().values(id="attempt-1", approval_id=approval_id)
        )

    result = await service.consume(
        approval_id, binding=binding(), attempt_audit=attempt_audit
    )

    assert (result.ok, result.reason) == (True, "consumed")
    assert (await service.get(approval_id)).status == ApprovalStatus.CONSUMED
    assert await _attempt_rows(engine, approval_id) == ["attempt-1"]


async def test_attempt_row_sees_the_consume_inside_the_transaction(wired) -> None:
    """Proof the callback really runs inside the CAS's transaction rather than
    after it: from the callback's connection the row is ALREADY ``consumed``,
    while a second, independent connection opened at the same moment still sees
    ``approved``. Same instant, two answers — which is only possible if the
    callback shares the uncommitted transaction.

    Postgres only, deliberately. The SQLite leg of this suite runs in-memory on
    a ``StaticPool``, where the "second connection" is physically the same
    connection (that is what makes an in-memory database usable at all), so it
    sees the uncommitted write and the test would assert the opposite of the
    truth. Isolation between transactions is a property of a real multi-
    connection engine, so it is proved on one; the atomicity tests below need no
    second connection and run on both.
    """
    service, engine = wired
    if engine.url.get_backend_name() == "sqlite":
        pytest.skip("in-memory SQLite StaticPool shares one connection — see docstring")
    approval_id = await _approved(service)
    seen_inside: list[str] = []
    seen_outside: list[str] = []

    async def attempt_audit(conn) -> None:
        from sunil.core.approvals.table import approvals_table as T

        inside = (
            await conn.execute(select(T.c.status).where(T.c.id == approval_id))
        ).scalar_one()
        seen_inside.append(inside)
        async with engine.connect() as other:
            outside = (
                await other.execute(select(T.c.status).where(T.c.id == approval_id))
            ).scalar_one()
        seen_outside.append(outside)
        await conn.execute(
            attempts.insert().values(id="attempt-1", approval_id=approval_id)
        )

    await service.consume(approval_id, binding=binding(), attempt_audit=attempt_audit)

    assert seen_inside == ["consumed"]
    assert seen_outside == ["approved"]


async def test_a_failing_attempt_audit_rolls_the_consume_back(wired) -> None:
    """The atomicity case that matters. If the audit write fails, the consume
    must NOT stand: the approval stays ``approved`` and therefore re-consumable,
    because an approval spent without a record of what it was spent on is the
    state the two-phase audit exists to make impossible.

    The exception propagates rather than being swallowed — the Tool Manager has
    to know its attempt row never landed, and the C1 pipeline's own error
    handling is where that belongs. Swallowing it here would leave the manager
    believing it had authorisation it no longer has.
    """
    service, engine = wired
    approval_id = await _approved(service)

    async def attempt_audit(conn) -> None:
        await conn.execute(
            attempts.insert().values(id="attempt-1", approval_id=approval_id)
        )
        raise AuditWriteFailed("audit sink unavailable")

    with pytest.raises(AuditWriteFailed):
        await service.consume(
            approval_id, binding=binding(), attempt_audit=attempt_audit
        )

    assert (await service.get(approval_id)).status == ApprovalStatus.APPROVED
    assert await _attempt_rows(engine, approval_id) == []
    # …and because nothing burned, the retry succeeds.
    retry = await service.consume(approval_id, binding=binding())
    assert (retry.ok, retry.reason) == (True, "consumed")


async def test_a_failed_cas_never_runs_the_attempt_callback(wired) -> None:
    """The other direction: no consume, no attempt row. A binding mismatch, a
    second consume and a stale approval must all leave the callback unrun —
    otherwise the audit trail would carry an attempt for a call that was never
    authorised."""
    service, engine = wired
    approval_id = await _approved(service)
    calls: list[str] = []

    async def attempt_audit(conn) -> None:
        calls.append("ran")
        await conn.execute(
            attempts.insert().values(id=f"attempt-{len(calls)}", approval_id=approval_id)
        )

    mismatch = await service.consume(
        approval_id, binding=binding(tool="github"), attempt_audit=attempt_audit
    )
    assert mismatch.reason == "binding_mismatch"
    assert calls == []

    first = await service.consume(approval_id, binding=binding())
    assert first.ok
    second = await service.consume(
        approval_id, binding=binding(), attempt_audit=attempt_audit
    )
    assert (second.ok, second.reason) == (False, "not_approved")
    assert calls == []
    assert await _attempt_rows(engine, approval_id) == []
