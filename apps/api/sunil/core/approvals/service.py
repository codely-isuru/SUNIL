"""``DatabaseApprovalsService`` — C4 v1.1.0 on the database.

This is the real implementation of C4 §4's seam plus the service-layer methods
C4 §6 declares normatively for it (``decide`` / ``sweep`` / ``list_approvals``),
and the ADR-031 startup reconciliation. ``tests/fakes/fake_approvals.py`` is the
in-memory twin; ``tests/unit/approvals/test_real_service_contract.py`` runs C4
§6's behaviours against BOTH through one adapter, so "the fake and the service
agree" is a tested claim rather than a hope.

Three design rules run through the whole module.

**1. Every transition is a compare-and-swap, in SQL.**
``UPDATE approvals SET … WHERE id = :id AND status = :expected … RETURNING *``.
Zero rows returned ⇒ somebody else got there first ⇒ the caller is told the
current status. There is no read-then-write anywhere in this file: a
``SELECT`` followed by an ``UPDATE`` is a lost-update race no matter how short
the gap, and C4 §1's transition table is written as guarded UPDATEs precisely so
that the guard and the write are one statement. The one-winner property is
proved against a real engine by ``tests/unit/approvals/test_cas_race.py`` with
two genuinely concurrent connections.

**2. ``now`` is a bound parameter, not SQL ``now()``.**
C4 §1 writes the CAS with ``now()``; this implementation passes ``:now`` from a
single injected clock instead. That is deliberate and it is not a weakening:
the *guard* is what makes the transition safe (``status = :expected``), and the
timestamp only decides which of two mutually exclusive outcomes applies
(decidable vs expired). Binding it means the TTL, the grace window and the
sweeper can be tested at their exact boundaries — 59 minutes in and 60 minutes
in — instead of with ``sleep``. A single clock also removes a real hazard of
``now()``: in Postgres, ``now()`` is transaction start time, so a long
transaction and the sweeper can disagree about whether the same row is expired.

**3. The seam is transactional, and the Tool Manager's audit row rides inside
it.** C1 §2.1 step 4 requires the attempt-audit row to commit in the same
transaction as the consume CAS (Security review 2026-09-10 item 3, two-phase
audit). ``consume`` therefore takes an optional ``attempt_audit`` callback which
is awaited **with the same connection, before the transaction commits**: if the
CAS did not match, the callback never runs on the consumed path; if the callback
raises, the whole transaction — CAS included — rolls back. There is no window
in which an approval is spent but unrecorded, in either direction. The extra
keyword is optional, so the class still satisfies C4 §4's frozen
``ApprovalsService`` protocol structurally.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from typing import Any, Literal, Protocol

from sqlalchemy import or_, select, tuple_, update
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from sunil.core.approvals.base import (
    Approval,
    ApprovalBinding,
    ApprovalListResponse,
    ApprovalRequestedEvent,
    ApprovalStatus,
    ConsumeResult,
    ParkedApproval,
    ParkRequest,
    StateConflict,
    StateConflictError,
)
from sunil.core.approvals.config import ApprovalsConfig
from sunil.core.approvals.ids import ulid_approval_id
from sunil.core.approvals.notify import ApprovalNotifier, NullNotifier
from sunil.core.approvals.table import approvals_table as T

logger = logging.getLogger(__name__)

#: C5 ``failure.kind`` values this service finalises tasks with (C4 §3).
FAILURE_APPROVAL_REFUSED = "approval_refused"
FAILURE_APPROVAL_EXPIRED = "approval_expired"
FAILURE_CONTINUATION_INTERRUPTED = "continuation_interrupted"

#: The audit kinds this service writes (C4 §3 rule 3 names the third by name).
AUDIT_PARKED = "approval_parked"
AUDIT_DECIDED = "approval_decided"
AUDIT_CONSUMED = "approval_consumed"
AUDIT_EXPIRED = "approval_expired"
AUDIT_RECONCILED = "continuation_reconciled"
AUDIT_RESCHEDULED = "continuation_rescheduled"

#: Columns the HTTP-facing ``Approval`` model is built from. ``continuation`` is
#: NOT among them — C4 §4: it never leaves this service over HTTP. Listing the
#: projection explicitly (rather than ``SELECT *``) is what makes that
#: structural instead of a habit.
ROW_COLUMNS = (
    T.c.id,
    T.c.status,
    T.c.created_at,
    T.c.expires_at,
    T.c.agent_id,
    T.c.tool,
    T.c.operation,
    T.c.args_hash,
    T.c.params_redacted,
    T.c.request_id,
    T.c.conversation_id,
    T.c.task_id,
    T.c.summary,
    T.c.decided_at,
    T.c.decided_by,
    T.c.decision_reason,
    T.c.consumed_at,
)


# --------------------------------------------------------------------------- #
# Collaborator seams — protocols, so this module imports no spine package
# --------------------------------------------------------------------------- #
class AuditSink(Protocol):
    """Where transition audit rows go. ``audit_events`` belongs to the spine
    lane, so the approvals service writes through a seam and the spine supplies
    the implementation at integration."""

    async def record(
        self,
        *,
        kind: str,
        approval_id: str | None,
        detail: dict,
        conn: AsyncConnection | None = None,
    ) -> None: ...


class TaskGateway(Protocol):
    """The two things this service needs to know and do about a parked task
    (C4 §3). ``tasks`` is the spine's table; the approvals service must not
    reach into it directly, and the reconciliation rules are phrased in terms
    of these two questions."""

    async def is_finalised(self, task_id: str) -> bool: ...

    async def finalise_failed(self, task_id: str, *, failure_kind: str) -> None: ...


class ContinuationScheduler(Protocol):
    """ADR-031's resume path. ``schedule`` re-enters
    ``ToolManager.execute(..., approval=<approval_id>)`` — the manager then
    recomputes the binding and calls ``consume`` (C4 §3, one consume owner)."""

    async def schedule(self, approval_id: str) -> None: ...


#: The C1 §2.1 step-4 callback: given the connection the consume CAS just ran
#: on, write the attempt-audit row. Awaited before commit.
AttemptAudit = Callable[[AsyncConnection], Awaitable[None]]


class ReconciliationReport:
    """What a startup re-scan did, per C4 §3's three rules — returned rather
    than only logged so a boot check can assert on it."""

    __slots__ = ("rescheduled", "expired", "interrupted")

    def __init__(self) -> None:
        self.rescheduled: list[str] = []
        self.expired: list[str] = []
        self.interrupted: list[str] = []

    @property
    def total(self) -> int:
        return len(self.rescheduled) + len(self.expired) + len(self.interrupted)

    def __repr__(self) -> str:  # pragma: no cover - diagnostics
        return (
            f"ReconciliationReport(rescheduled={self.rescheduled!r}, "
            f"expired={self.expired!r}, interrupted={self.interrupted!r})"
        )


# --------------------------------------------------------------------------- #
# Timestamp edge
# --------------------------------------------------------------------------- #
def to_iso(moment: datetime) -> str:
    """The contract's ISO-8601 UTC form (``…Z``), whole seconds."""
    return moment.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _aware(moment: datetime | None) -> datetime | None:
    """SQLite hands back naive datetimes even from a ``timezone=True`` column;
    Postgres hands back aware ones. Normalise at the edge so the comparison
    logic above never has to care which engine it is on — a naive/aware mix is
    a ``TypeError`` at the worst possible moment (inside a CAS)."""
    if moment is None:
        return None
    return moment if moment.tzinfo is not None else moment.replace(tzinfo=UTC)


class DatabaseApprovalsService:
    """C4's approvals service on a SQLAlchemy 2 async engine."""

    def __init__(
        self,
        *,
        engine: AsyncEngine,
        config: ApprovalsConfig | None = None,
        clock: Callable[[], datetime] | None = None,
        id_factory: Callable[[datetime], str] = ulid_approval_id,
        notifier: ApprovalNotifier | None = None,
        audit: AuditSink | None = None,
        tasks: TaskGateway | None = None,
        scheduler: ContinuationScheduler | None = None,
    ) -> None:
        self.engine = engine
        self.config = config or ApprovalsConfig()
        self.clock = clock or (lambda: datetime.now(UTC))
        self.id_factory = id_factory
        self.notifier = notifier or NullNotifier()
        self.audit = audit
        self.tasks = tasks
        self.scheduler = scheduler
        #: Events for approvals parked inside a CALLER-owned transaction, held
        #: until :meth:`notify_parked` is called post-commit (C4 §2). Per
        #: instance, never class-level: a shared dict would leak one request's
        #: park material into another's notify.
        self._pending_events: dict[str, dict] = {}

    # -- helpers ----------------------------------------------------------- #
    @property
    def _grace(self) -> timedelta:
        return timedelta(hours=self.config.consume_grace_hours)

    def _now(self) -> datetime:
        moment = self.clock()
        if moment.tzinfo is None:  # a naive clock would silently mean UTC-ish
            raise ValueError("the approvals clock must return an aware datetime")
        return moment

    @staticmethod
    def _model(row: Any) -> Approval:
        """Map one result row onto the C4 ``Approval`` model."""
        return Approval(
            id=row.id,
            status=ApprovalStatus(row.status),
            created_at=to_iso(_aware(row.created_at)),
            expires_at=to_iso(_aware(row.expires_at)),
            agent_id=row.agent_id,
            tool=row.tool,
            operation=row.operation,
            args_hash=row.args_hash,
            params_redacted=row.params_redacted,
            request_id=row.request_id,
            conversation_id=row.conversation_id,
            task_id=row.task_id,
            summary=row.summary,
            decided_at=(
                None if row.decided_at is None else to_iso(_aware(row.decided_at))
            ),
            decided_by=row.decided_by,
            decision_reason=row.decision_reason,
            consumed_at=(
                None if row.consumed_at is None else to_iso(_aware(row.consumed_at))
            ),
        )

    @staticmethod
    def _conflict(row: Any) -> StateConflict:
        status = ApprovalStatus(row.status)
        return StateConflict(
            error=StateConflictError(
                message=f"approval {row.id} is {status.value}, not pending",
                current_status=status,
            )
        )

    async def _audit(
        self,
        kind: str,
        approval_id: str | None,
        detail: dict,
        conn: AsyncConnection | None = None,
    ) -> None:
        if self.audit is None:
            return
        await self.audit.record(
            kind=kind, approval_id=approval_id, detail=detail, conn=conn
        )

    # ------------------------------------------------------------------ #
    # C4 §4 protocol — park
    # ------------------------------------------------------------------ #
    async def park(
        self, req: ParkRequest, *, conn: AsyncConnection | None = None
    ) -> ParkedApproval:
        """C4 §1 / §4 — INSERT with an **explicit** ``status='pending'``.

        ``req`` is a ``ParkRequest``, so the fail-closed bounds on ``summary``
        and ``continuation`` (C4 §4, v1.1.0 F3) have already been enforced by
        the model: this method cannot be reached with park material that would
        mint a never-resumable approval.

        ``conn`` lets the Tool Manager park **inside its own transaction** —
        C4 §1's restart-safety rule and C1 §2.1 step 4's park-path clause
        ("on the park path it commits in the park transaction"). Called without
        it, the insert gets its own transaction. Either way the continuation is
        a column on the inserted row, so there is no ordering to get wrong.

        The webhook fires only after the transaction the row was written in has
        committed (C4 §2), which is why the notify call is outside ``_park_row``
        and is skipped when the caller owns the transaction — the caller has not
        committed yet, so the service announces nothing it cannot vouch for. A
        caller-owned park therefore returns the event for the caller to send
        post-commit via :meth:`notify_parked`.
        """
        now = self._now()
        values, event = self._park_values(req, now)
        if conn is not None:
            await conn.execute(T.insert().values(**values))
            await self._audit(
                AUDIT_PARKED, values["id"], {"tool": req.tool, "operation": req.operation}, conn
            )
            self._pending_events[values["id"]] = event
        else:
            async with self.engine.begin() as owned:
                await owned.execute(T.insert().values(**values))
                await self._audit(
                    AUDIT_PARKED,
                    values["id"],
                    {"tool": req.tool, "operation": req.operation},
                    owned,
                )
            await self.notifier.notify_requested(event)
        return ParkedApproval(
            approval_id=values["id"], expires_at=to_iso(values["expires_at"])
        )

    async def notify_parked(self, approval_id: str) -> None:
        """Send the ``approval.requested`` event for an approval parked inside a
        caller-owned transaction. The caller calls this AFTER its commit, which
        is the only moment at which the announcement is honest (C4 §2)."""
        event = self._pending_events.pop(approval_id, None)
        if event is not None:
            await self.notifier.notify_requested(event)

    def _park_values(self, req: ParkRequest, now: datetime) -> tuple[dict, dict]:
        approval_id = self.id_factory(now)
        expires_at = now + timedelta(hours=self.config.ttl_hours)
        values = {
            "id": approval_id,
            # Explicit, never a schema default (C4 §1; lesson 2026-08-17).
            "status": ApprovalStatus.PENDING.value,
            "created_at": now,
            "expires_at": expires_at,
            "agent_id": req.agent_id,
            "tool": req.tool,
            "operation": req.operation,
            "args_hash": req.args_hash,
            "params_redacted": req.params_redacted,
            "request_id": req.request_id,
            "conversation_id": req.conversation_id,
            "task_id": req.task_id,
            "summary": req.summary,
            "continuation": req.continuation,
        }
        event = ApprovalRequestedEvent(
            approval_id=approval_id,
            agent_id=req.agent_id,
            tool=req.tool,
            operation=req.operation,
            summary=req.summary,
            created_at=to_iso(now),
            expires_at=to_iso(expires_at),
        ).model_dump()
        return values, event

    # ------------------------------------------------------------------ #
    # C4 §4 protocol — consume (the single-use CAS)
    # ------------------------------------------------------------------ #
    async def consume(
        self,
        approval_id: str,
        *,
        binding: ApprovalBinding,
        attempt_audit: AttemptAudit | None = None,
    ) -> ConsumeResult:
        """C4 §1 / §6.3 — the ``approved → consumed`` CAS, grace-bounded.

        Order of outcomes is C4 §6.3's, and the order matters: a stale approval
        with the WRONG binding must read as ``not_approved`` (it is out of
        time), not ``binding_mismatch`` (which promises the row is still
        spendable). Precedence, therefore: absent → not approved → past grace →
        binding → consume.

        ``attempt_audit`` is C1 §2.1 step 4's two-phase audit row. It is awaited
        on the same connection inside the same transaction as the CAS, so:
        CAS matched + callback succeeded ⇒ both committed; callback raised ⇒
        both rolled back and the approval is still spendable; CAS did not match
        ⇒ no consume happened and the caller writes its own early-exit row. The
        "spent but unrecorded" and "recorded but unspent" states are both
        unreachable.
        """
        now = self._now()
        async with self.engine.begin() as conn:
            row = (
                await conn.execute(
                    select(T.c.id, T.c.status, T.c.decided_at, *_BINDING_COLUMNS).where(
                        T.c.id == approval_id
                    )
                )
            ).first()
            if row is None:
                return ConsumeResult(ok=False, reason="not_found")
            if row.status != ApprovalStatus.APPROVED.value:
                return ConsumeResult(ok=False, reason="not_approved")

            decided_at = _aware(row.decided_at)
            if decided_at is not None and now >= decided_at + self._grace:
                # Lazy stale-approved expiry (C4 §1 + §6.3). Still a CAS: the
                # sweeper may be doing the same thing on another connection.
                await conn.execute(
                    update(T)
                    .where(
                        T.c.id == approval_id,
                        T.c.status == ApprovalStatus.APPROVED.value,
                    )
                    .values(status=ApprovalStatus.EXPIRED.value)
                )
                await self._audit(
                    AUDIT_EXPIRED,
                    approval_id,
                    {"cause": "consume_past_grace"},
                    conn,
                )
                return ConsumeResult(ok=False, reason="not_approved")

            stored = ApprovalBinding(
                agent_id=row.agent_id,
                tool=row.tool,
                operation=row.operation,
                args_hash=row.args_hash,
            )
            if binding != stored:
                # The approval stays `approved` — a mismatch must not burn it
                # (C4 §6.3). The sweeper reaps it when the grace window closes.
                return ConsumeResult(ok=False, reason="binding_mismatch")

            consumed = (
                await conn.execute(
                    update(T)
                    .where(
                        T.c.id == approval_id,
                        T.c.status == ApprovalStatus.APPROVED.value,
                        T.c.agent_id == binding.agent_id,
                        T.c.tool == binding.tool,
                        T.c.operation == binding.operation,
                        T.c.args_hash == binding.args_hash,
                        # C4 §1's `decided_at + :grace > now()`, rearranged so
                        # the comparison is column-vs-parameter and the
                        # (status, decided_at) index can serve it.
                        T.c.decided_at > now - self._grace,
                    )
                    .values(
                        status=ApprovalStatus.CONSUMED.value,
                        consumed_at=now,
                    )
                    .returning(T.c.id)
                )
            ).first()
            if consumed is None:
                # Somebody else consumed or expired it between the read above
                # and this statement. The guard is the authority, not the read.
                return ConsumeResult(ok=False, reason="not_approved")

            if attempt_audit is not None:
                # C1 §2.1 step 4: same transaction as the CAS. A raise here
                # rolls the consume back with it — deliberate.
                await attempt_audit(conn)
            await self._audit(AUDIT_CONSUMED, approval_id, {"tool": binding.tool}, conn)
        return ConsumeResult(ok=True, reason="consumed")

    # ------------------------------------------------------------------ #
    # C4 §6.2 — decide (the HTTP layer's one mutating call)
    # ------------------------------------------------------------------ #
    async def decide(
        self,
        approval_id: str,
        decision: Literal["approve", "refuse"],
        reason: str | None = None,
        *,
        decided_by: str = "owner",
    ) -> Approval | StateConflict | None:
        """C4 §6.2, normative for this service (v1.0.1) — returns
        ``Approval | StateConflict | None`` and **never raises** for absence or
        conflict, so HTTP status mapping lives in the route and nowhere else.

        The transition is one guarded UPDATE: ``status='pending' AND expires_at
        > :now``. Zero rows means one of three things, and the follow-up SELECT
        tells them apart: the row is gone (``None`` → 404), the row was pending
        but out of time (expire it, then 409 ``expired``), or somebody already
        decided it (409 with the real status). The follow-up read is not a race:
        the UPDATE already failed, so there is nothing left to lose — and every
        status it can report is terminal except ``pending``, which the lazy
        expiry then settles with another CAS.
        """
        now = self._now()
        target = (
            ApprovalStatus.APPROVED if decision == "approve" else ApprovalStatus.REFUSED
        )
        async with self.engine.begin() as conn:
            decided = (
                await conn.execute(
                    update(T)
                    .where(
                        T.c.id == approval_id,
                        T.c.status == ApprovalStatus.PENDING.value,
                        T.c.expires_at > now,
                    )
                    .values(
                        status=target.value,
                        decided_at=now,
                        decided_by=decided_by,
                        decision_reason=reason,
                    )
                    .returning(*ROW_COLUMNS)
                )
            ).first()
            if decided is not None:
                await self._audit(
                    AUDIT_DECIDED,
                    approval_id,
                    {"decision": decision, "decided_by": decided_by},
                    conn,
                )
                return self._model(decided)

            current = (
                await conn.execute(
                    select(T.c.id, T.c.status).where(T.c.id == approval_id)
                )
            ).first()
            if current is None:
                return None
            if current.status == ApprovalStatus.PENDING.value:
                # Pending but past expires_at: expire it first, then conflict
                # with `expired` — C4 §6.2, and §5's rule that expiry at
                # decision time is a 409, never a 410.
                await conn.execute(
                    update(T)
                    .where(
                        T.c.id == approval_id,
                        T.c.status == ApprovalStatus.PENDING.value,
                        T.c.expires_at <= now,
                    )
                    .values(status=ApprovalStatus.EXPIRED.value)
                )
                await self._audit(
                    AUDIT_EXPIRED, approval_id, {"cause": "decide_past_ttl"}, conn
                )
                current = (
                    await conn.execute(
                        select(T.c.id, T.c.status).where(T.c.id == approval_id)
                    )
                ).first()
            return self._conflict(current)

    # ------------------------------------------------------------------ #
    # C4 §6.4 — the sweeper's transition pair
    # ------------------------------------------------------------------ #
    async def sweep(self, now: datetime | None = None) -> int:
        """C4 §6.4 / §1 — expire every ``pending`` past its TTL AND every
        ``approved`` past its grace window; return the total.

        Two UPDATEs rather than one with an ``OR``, because they are two
        different transitions with two different guards and two different audit
        causes — and because each one wants its own index
        (``(status, expires_at)`` and ``(status, decided_at)``).

        Idempotent by construction: both guards name the source status, so a
        second sweep over the same rows matches nothing and returns 0. That is
        what C4 contract test 4's "counts it exactly once" is asserting.
        """
        at = now or self._now()
        async with self.engine.begin() as conn:
            pending = (
                await conn.execute(
                    update(T)
                    .where(
                        T.c.status == ApprovalStatus.PENDING.value,
                        T.c.expires_at <= at,
                    )
                    .values(status=ApprovalStatus.EXPIRED.value)
                    .returning(T.c.id)
                )
            ).fetchall()
            stale = (
                await conn.execute(
                    update(T)
                    .where(
                        T.c.status == ApprovalStatus.APPROVED.value,
                        T.c.decided_at <= at - self._grace,
                    )
                    .values(status=ApprovalStatus.EXPIRED.value)
                    .returning(T.c.id)
                )
            ).fetchall()
            for row in pending:
                await self._audit(
                    AUDIT_EXPIRED, row.id, {"cause": "sweep_pending_ttl"}, conn
                )
            for row in stale:
                await self._audit(
                    AUDIT_EXPIRED, row.id, {"cause": "sweep_approved_grace"}, conn
                )
        swept = [r.id for r in pending] + [r.id for r in stale]
        await self._finalise_expired_tasks(swept)
        return len(swept)

    async def _finalise_expired_tasks(self, approval_ids: list[str]) -> None:
        """C4 §1 — an expired approval finalises its task ``failed`` with
        ``failure.kind=approval_expired``. Done outside the sweep transaction on
        purpose: the ``tasks`` table is the spine's, reached through a seam, and
        a slow or failing task gateway must not hold the sweeper's locks or
        undo an expiry that is already correct."""
        if not approval_ids or self.tasks is None:
            return
        async with self.engine.connect() as conn:
            rows = (
                await conn.execute(
                    select(T.c.id, T.c.task_id).where(T.c.id.in_(approval_ids))
                )
            ).fetchall()
        for row in rows:
            try:
                if not await self.tasks.is_finalised(row.task_id):
                    await self.tasks.finalise_failed(
                        row.task_id, failure_kind=FAILURE_APPROVAL_EXPIRED
                    )
            except Exception:  # noqa: BLE001
                logger.exception(
                    "failed to finalise task for expired approval %s", row.id
                )

    # ------------------------------------------------------------------ #
    # C4 §6.5 — listing (the dashboard queue)
    # ------------------------------------------------------------------ #
    async def list_approvals(
        self,
        *,
        status: ApprovalStatus | None = None,
        limit: int = 50,
        cursor: str | None = None,
    ) -> ApprovalListResponse:
        """C4 §6.5 — filter by status, order ``created_at`` desc then ``id``
        desc, keyset-paged on the last row's id.

        Both loose readings resolved as QA pinned them (fake finding F8, and the
        fake is what Stream D's dashboard was built against):

        * **``id desc`` is lexicographic** — the plain meaning of ordering a
          string column, and what ``ORDER BY created_at DESC, id DESC`` does
          here. Safe because every id this service mints is ``apr-`` + a
          26-character Crockford-base32 ULID: one alphabet, one width, so byte
          order and collation order cannot disagree (``ids.py``).
        * **``next_cursor`` is ``None`` only for a SHORT page.** An exactly-full
          final page still returns a cursor; the client discovers the end by
          asking once more and getting an empty page. No look-ahead query is
          issued, which is the whole reason the contract was pinned this way.

        The cursor is the previous page's last id, and it is resolved to its
        ``(created_at, id)`` pair before the keyset comparison — a row-value
        ``<`` on that pair is what makes the page boundary exact even when many
        rows share a ``created_at``. An unknown cursor raises ``ValueError``
        (the route's 422) rather than silently serving page one, which would
        make a paging loop restart for ever.
        """
        conditions = []
        if status is not None:
            conditions.append(T.c.status == status.value)

        async with self.engine.connect() as conn:
            if cursor is not None:
                anchor = (
                    await conn.execute(
                        select(T.c.created_at, T.c.id).where(T.c.id == cursor)
                    )
                ).first()
                if anchor is None:
                    raise ValueError(f"unknown cursor: {cursor}")
                conditions.append(
                    tuple_(T.c.created_at, T.c.id)
                    < tuple_(anchor.created_at, anchor.id)
                )

            rows = (
                await conn.execute(
                    select(*ROW_COLUMNS)
                    .where(*conditions)
                    .order_by(T.c.created_at.desc(), T.c.id.desc())
                    .limit(limit)
                )
            ).fetchall()

        page = [self._model(row) for row in rows]
        next_cursor = page[-1].id if len(page) == limit else None
        return ApprovalListResponse(approvals=page, next_cursor=next_cursor)

    async def get(self, approval_id: str) -> Approval | None:
        """One approval with full (redacted) detail — the C4 detail route.
        ``None`` → the route's 404. ``continuation`` is not in ``ROW_COLUMNS``,
        so it cannot reach the response by accident (C4 §4)."""
        async with self.engine.connect() as conn:
            row = (
                await conn.execute(select(*ROW_COLUMNS).where(T.c.id == approval_id))
            ).first()
        return None if row is None else self._model(row)

    async def continuation_for(self, approval_id: str) -> dict | None:
        """The persisted continuation (C4 §1 restart safety), for the resume
        path only. Deliberately a separate method from :meth:`get`: the HTTP
        layer calls ``get`` and cannot reach this, which is how "never leaves
        this service over HTTP" is enforced structurally rather than by review.
        """
        async with self.engine.connect() as conn:
            row = (
                await conn.execute(
                    select(T.c.continuation).where(T.c.id == approval_id)
                )
            ).first()
        return None if row is None else row.continuation

    # ------------------------------------------------------------------ #
    # C4 §3 — startup reconciliation (Security review items 1–2)
    # ------------------------------------------------------------------ #
    async def reconcile_on_startup(
        self, now: datetime | None = None
    ) -> ReconciliationReport:
        """C4 §3's three rules, exactly, each transition audited.

        1. ``approved`` + unfinalised task + within grace → re-schedule the
           continuation.
        2. ``approved`` + ``decided_at + grace <= now`` → CAS to ``expired`` and
           finalise the task ``failed`` / ``approval_expired``.
        3. ``consumed`` + unfinalised task → finalise the task ``failed`` /
           ``continuation_interrupted`` and write a ``continuation_reconciled``
           audit row. **It never re-executes.** The consume CAS is spent and
           single-use is the property that must survive a crash: the tool call
           may or may not have fired, and the C1 §2.1 step-4 attempt row — which
           committed in the same transaction as that CAS — is the record of what
           was attempted. Re-running it would turn a crash into a double side
           effect, which is the one outcome an approval exists to prevent.
        """
        at = now or self._now()
        report = ReconciliationReport()

        # Rule 2 first: expiring the stale rows before rule 1 reads them means
        # rule 1 cannot re-schedule a continuation that rule 2 is about to kill.
        async with self.engine.begin() as conn:
            stale = (
                await conn.execute(
                    update(T)
                    .where(
                        T.c.status == ApprovalStatus.APPROVED.value,
                        T.c.decided_at <= at - self._grace,
                    )
                    .values(status=ApprovalStatus.EXPIRED.value)
                    .returning(T.c.id, T.c.task_id)
                )
            ).fetchall()
            for row in stale:
                await self._audit(
                    AUDIT_EXPIRED,
                    row.id,
                    {"cause": "reconcile_approved_past_grace"},
                    conn,
                )
        for row in stale:
            report.expired.append(row.id)
            await self._finalise(row.task_id, FAILURE_APPROVAL_EXPIRED)

        async with self.engine.connect() as conn:
            live = (
                await conn.execute(
                    select(T.c.id, T.c.task_id).where(
                        T.c.status == ApprovalStatus.APPROVED.value,
                        or_(T.c.decided_at.is_(None), T.c.decided_at > at - self._grace),
                    )
                )
            ).fetchall()
            spent = (
                await conn.execute(
                    select(T.c.id, T.c.task_id).where(
                        T.c.status == ApprovalStatus.CONSUMED.value
                    )
                )
            ).fetchall()

        # Rule 1 — approved, in grace, task not finalised → resume.
        for row in live:
            if self.tasks is not None and await self.tasks.is_finalised(row.task_id):
                continue
            report.rescheduled.append(row.id)
            await self._audit(AUDIT_RESCHEDULED, row.id, {"task_id": row.task_id})
            if self.scheduler is not None:
                await self.scheduler.schedule(row.id)

        # Rule 3 — consumed, task not finalised → finalise failed, NEVER resume.
        for row in spent:
            if self.tasks is None or await self.tasks.is_finalised(row.task_id):
                continue
            report.interrupted.append(row.id)
            await self._finalise(row.task_id, FAILURE_CONTINUATION_INTERRUPTED)
            await self._audit(
                AUDIT_RECONCILED,
                row.id,
                {
                    "task_id": row.task_id,
                    "failure_kind": FAILURE_CONTINUATION_INTERRUPTED,
                    "re_executed": False,
                },
            )
        return report

    async def _finalise(self, task_id: str, failure_kind: str) -> None:
        if self.tasks is None:
            return
        if await self.tasks.is_finalised(task_id):
            return
        await self.tasks.finalise_failed(task_id, failure_kind=failure_kind)

    # ------------------------------------------------------------------ #
    # C4 §3 — refuse finalises the task
    # ------------------------------------------------------------------ #
    async def finalise_refusal(self, approval_id: str) -> None:
        """C4 §3 — a refusal executes nothing and finalises the task ``failed``
        with ``failure.kind="approval_refused"``. Called by the decision route
        after a successful refuse transition."""
        async with self.engine.connect() as conn:
            row = (
                await conn.execute(select(T.c.task_id).where(T.c.id == approval_id))
            ).first()
        if row is not None:
            await self._finalise(row.task_id, FAILURE_APPROVAL_REFUSED)


_BINDING_COLUMNS = (T.c.agent_id, T.c.tool, T.c.operation, T.c.args_hash)
