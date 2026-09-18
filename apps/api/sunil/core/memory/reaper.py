"""The `memories` reaper — deletion of expired rows, on its own schedule.

S2-C §7.4 (disposed by ruling R15): `memories` had no reaper. Expired rows were
FILTERED out of recall by the lazy TTL predicate and never removed, so the store
grew without bound and an expired memory remained readable by anything that
queried the table directly — a backup, a psql session, a future feature. A TTL
the owner set is a promise that the content goes away, and a filter is not a
deletion.

This module is the scheduled runner; the deletion itself belongs to the store
(`memory_providers/pgvector_provider.py::delete_expired`), so this file has no
SQL in it and the provider has no scheduling in it. **No contract movement**: C3
binds what recall may SEE, not storage hygiene, and `delete_expired` is not part
of the `MemoryProvider` Protocol.

Posture, deliberately asymmetric with `core/approvals/sweeper.py` — and this is
the argued part:

* **The tick is contained, exactly as the sweeper's is.** A tick that propagated
  would kill the task and convert one transient database blip into a permanently
  dead reaper. Nothing else deletes these rows (recall only filters them), so a
  dead reaper is unbounded growth, not a missed transition.
* **There is NO startup-propagating leg**, and that is not an omission. The
  sweeper propagates its startup reconciliation because that is a ONE-SHOT safety
  property — a consumed-but-unfinalised continuation must be failed before
  anything else runs, and an API that booted having skipped it leaves interrupted
  continuations looking runnable. Deletion has no equivalent: it is idempotent (a
  second pass over the same rows matches nothing), it is lazy-guarded (recall
  already hides what this deletes), and it is time-driven rather than
  boot-driven. A reap missed at boot costs nothing the next tick does not fix, so
  refusing to boot on it would buy a brand-new outage mode for no safety.

**The audit row carries a COUNT and nothing else.** A reaper that recorded which
memories it destroyed would copy the content of expired — often the most private
— memories into the audit trail, the one store retention cannot then clear.
A batch that deleted nothing writes no row at all: the trail records the event
(memories were destroyed), not the schedule.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import Protocol

logger = logging.getLogger(__name__)

#: The reaper's own cadence (R15: "same lifespan hook, own cadence"). Hourly,
#: not the approvals sweeper's 60 s: a TTL is measured in days, nothing observes
#: the deletion, and the cheapest correct schedule is the one that touches a
#: large table least often.
DEFAULT_INTERVAL_S = 3600


class ExpiredMemoryStore(Protocol):
    """The slice of the store this runner needs — narrow on purpose: the reaper
    has no business reaching for `write` or `recall`."""

    async def delete_expired(self) -> int: ...


class ReapAuditSink(Protocol):
    """Where the per-batch audit row goes. Injected rather than imported, like
    `MemoryService`'s sink, so this module does not reach into `core.audit` — and
    so the signature itself can only carry a count."""

    async def record_memory_reap(self, *, deleted: int) -> None: ...


class MemoryReaper:
    """Deletes expired `memories` rows on a schedule.

    Wire it from the app's lifespan: `await reaper.start()` on startup,
    `await reaper.stop()` on shutdown.
    """

    def __init__(
        self,
        store: ExpiredMemoryStore,
        *,
        interval_s: float = DEFAULT_INTERVAL_S,
        audit_sink: ReapAuditSink | None = None,
        on_error: Callable[[BaseException], None] | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._store = store
        self._interval_s = interval_s
        self._audit_sink = audit_sink
        self._on_error = on_error or self._log_error
        self._sleep = sleep
        self._task: asyncio.Task | None = None

    @staticmethod
    def _log_error(exc: BaseException) -> None:
        # The exception TYPE only: a database error's text can quote the row it
        # choked on, and these rows are memory content.
        logger.warning("memory reap failed: %s", type(exc).__name__)

    async def run_once(self) -> int:
        """One reap. Returns the number of rows deleted, or 0 if the reap failed
        — and NEVER raises (see the module docstring).

        The audit row is written AFTER the delete has returned, unlike a memory
        write's row: here the row states a completed fact ("n rows were
        destroyed"), and a count written before the delete could name rows that
        are still there.
        """
        try:
            deleted = await self._store.delete_expired()
        except Exception as exc:  # noqa: BLE001 - containment is the point
            self._on_error(exc)
            return 0

        if deleted and self._audit_sink is not None:
            try:
                await self._audit_sink.record_memory_reap(deleted=deleted)
            except Exception as exc:  # noqa: BLE001
                # The rows are already gone; a failed audit write must not make
                # the loop retry a deletion that succeeded.
                self._on_error(exc)
        return deleted

    async def start(self) -> None:
        """Start the periodic loop. Nothing propagates from here — see the
        module docstring's second bullet."""
        if self._task is not None:
            raise RuntimeError("memory reaper already started")
        self._task = asyncio.create_task(self._loop(), name="memory-reaper")

    async def _loop(self) -> None:
        while True:
            await self.run_once()
            await self._sleep(self._interval_s)

    async def stop(self) -> None:
        """Cancel the loop and wait for it. Idempotent, and safe before
        `start()` — it also runs on a shutdown that follows a failed startup."""
        task, self._task = self._task, None
        if task is None:
            return
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
