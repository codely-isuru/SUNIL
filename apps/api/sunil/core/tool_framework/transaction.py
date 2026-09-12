"""``TransactionalApprovals`` — C1 §2.1 step 4's transactional rule, wired.

C1 §2.1 step 4: *"on the continuation path the attempt row MUST commit in the
same DB transaction as the consume CAS"*, and on the park path it commits in the
park transaction. C4's service has offered both halves since Stream D landed —
``consume(..., attempt_audit=…)`` and ``park(..., conn=…)`` — and the Security
wave-1 review's condition **C-1** found that nothing called them: the chokepoint
consumed in one transaction and the audit hook wrote the row in another, so a
crash between the two left the approval ``consumed`` with no ``tool_calls`` row.
Spent but unrecorded — the one state C4 §3's reconciliation rule 3 cannot cope
with, because it treats that row as the record of what was attempted.

This class is the caller. It exists as a separate object, injected into the Tool
Manager, for three reasons:

1. **The manager does not sniff for capabilities.** A pipeline that branched on
   ``hasattr(approvals, …)`` would silently fall back to the unsafe path the day
   a seam changed shape. Wiring decides once, at boot, whether the transactional
   path is available (``api/wiring.py``); the manager sees either a collaborator
   or ``None``, and ``None`` means the injected seams are in-memory fakes with no
   transaction to share.
2. **One hook instance per plan execution.** The audit hook carries
   ADR-004 Amendment 1's ``validated_plan_id``, so it is minted per plan — and
   therefore so is this, alongside the manager the same factory builds.
3. **The failure propagates.** Neither method catches: if the attempt write
   fails the whole transaction rolls back, and the caller must learn that its
   authorisation was NOT spent. Converting that into a ``ToolResult`` would
   require writing an audit row through the sink that just failed.
"""

from __future__ import annotations

from typing import Any, Protocol

from sqlalchemy.ext.asyncio import AsyncConnection

from sunil.core.approvals.base import (
    ApprovalBinding,
    ConsumeResult,
    ParkedApproval,
    ParkRequest,
)
from sunil.core.tool_framework.base import ToolCallAttempt


class TransactionalAuditHook(Protocol):
    """A ``C1 §2.2`` audit hook that can also write its attempt row on a
    connection the CALLER owns. Structural, not inherited: the two-phase hook's
    own ``attempt``/``finalise`` are unchanged, and a hook without this method is
    simply not eligible for the transactional path."""

    async def attempt_on(self, conn: AsyncConnection, record: ToolCallAttempt) -> str: ...


class TransactionalApprovals:
    """Binds a C4 service's transaction to the C1 step-4 attempt row.

    ``approvals`` must be the real service (it needs ``engine``, ``park(conn=)``
    and ``consume(attempt_audit=)``); ``audit`` must offer ``attempt_on``. Both
    are checked at construction, so a misconfiguration is a boot failure rather
    than a silently non-transactional call path.
    """

    def __init__(self, *, approvals: Any, audit: TransactionalAuditHook) -> None:
        engine = getattr(approvals, "engine", None)
        if engine is None:
            raise TypeError(
                "TransactionalApprovals needs a database-backed C4 service (no "
                "`engine`): C1 §2.1 step 4's rule is about a shared DB transaction, "
                "and there is nothing to share with an in-memory one"
            )
        if not callable(getattr(audit, "attempt_on", None)):
            raise TypeError(
                "TransactionalApprovals needs an audit hook with attempt_on(conn, "
                "record): the attempt row has to be written on the caller's "
                "connection to commit with the CAS (C1 §2.1 step 4)"
            )
        self._approvals = approvals
        self._audit = audit
        self._engine = engine

    async def park_with_attempt(
        self, request: ParkRequest, record_for: Any
    ) -> tuple[ParkedApproval, str]:
        """Park the approval and write the attempt row in ONE transaction.

        ``record_for`` is a callable taking the minted approval id and returning
        the ``ToolCallAttempt``, because the row must carry an id that does not
        exist until the INSERT has run — and the trail's whole value on this path
        is that the row joins to the approval a later continuation will present.

        The notify fires after the commit, through the service's own
        :meth:`notify_parked`, because a webhook announcing a row that has not
        committed is a promise the service cannot vouch for (C4 §2).
        """
        async with self._engine.begin() as conn:
            parked = await self._approvals.park(request, conn=conn)
            audit_id = await self._audit.attempt_on(conn, record_for(parked.approval_id))
        await self._approvals.notify_parked(parked.approval_id)
        return parked, audit_id

    async def consume_with_attempt(
        self, approval_id: str, *, binding: ApprovalBinding, record: ToolCallAttempt
    ) -> tuple[ConsumeResult, str | None]:
        """Consume, writing the attempt row inside the CAS's transaction.

        Returns ``(result, audit_id)``. ``audit_id`` is ``None`` exactly when the
        CAS did not match — the callback never ran, so no attempt row exists and
        the caller writes its own early-exit row for the refusal instead. That
        asymmetry is the point: an attempt row must never describe a call no
        approval authorised.
        """
        written: list[str] = []

        async def attempt_audit(conn: AsyncConnection) -> None:
            written.append(await self._audit.attempt_on(conn, record))

        result = await self._approvals.consume(
            approval_id, binding=binding, attempt_audit=attempt_audit
        )
        return result, (written[0] if written else None)
