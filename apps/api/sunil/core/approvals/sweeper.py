"""The scheduled runner around the approvals service — ``ARCHITECTURE_V2.md``
§2's ``core/approvals/sweeper.py``.

``DatabaseApprovalsService.sweep()`` performs C4 §1's two transitions
(``pending`` past TTL → ``expired``, ``approved`` past grace → ``expired``).
This module is the thing that *calls* it on C4 §1's schedule — **startup and
every 60 s** — and it is a separate module because the two have different
failure postures, and mixing them is how one becomes the other:

* **A sweep is best-effort and recurring.** ``ARCHITECTURE_V2.md`` §8's failure
  table: "approvals sweeper missed → lazy expiry at read/decide covers it". So a
  sweep that raises is reported and swallowed, and the loop keeps its schedule.
  A tick that propagated would kill the task and convert one transient database
  blip into a permanently dead sweeper — and lazy expiry only covers rows
  somebody reads, so ``approved``-past-grace rows nobody touches again would sit
  spendable past their grace window, which is the exact hole the 2026-09-10
  security review's item 1 closed.
* **The startup reconciliation is a one-shot safety property** (C4 §3 /
  ADR-031: a consumed-but-unfinalised continuation is failed
  ``continuation_interrupted`` and never re-executed). A failure there is NOT
  swallowed: an API that booted having silently skipped it would leave
  interrupted continuations looking runnable, and "never re-execute a consumed
  approval" is not a property worth degrading quietly.

Scheduling primitives are injected (``sleep``), so the tests drive the loop
deterministically instead of waiting real seconds — a sweeper tested with
``asyncio.sleep(0.1)`` and a tolerance is a flaky test generator.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import Any, Protocol

logger = logging.getLogger(__name__)

#: C4 §1's schedule ("startup + every 60 s").
DEFAULT_INTERVAL_S = 60


class Sweepable(Protocol):
    """The slice of the C4 service this runner needs. Narrow on purpose: the
    sweeper has no business reaching for ``park`` or ``decide``."""

    async def sweep(self) -> int: ...

    async def reconcile_on_startup(self) -> Any: ...


class ApprovalSweeper:
    """Runs the approvals sweep on C4 §1's schedule.

    Wire it from the app's lifespan: ``await sweeper.start()`` on startup,
    ``await sweeper.stop()`` on shutdown.
    """

    def __init__(
        self,
        service: Sweepable,
        *,
        interval_s: float = DEFAULT_INTERVAL_S,
        on_error: Callable[[BaseException], None] | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._service = service
        self._interval_s = interval_s
        self._on_error = on_error or self._log_error
        self._sleep = sleep
        self._task: asyncio.Task | None = None

    @staticmethod
    def _log_error(exc: BaseException) -> None:
        # No approval field is logged — a summary is untrusted text and an
        # approval id is not needed to act on "the sweep failed".
        logger.warning("approvals sweep failed: %s", type(exc).__name__)

    async def run_once(self) -> int:
        """One sweep. Returns the number of rows transitioned, or 0 if the
        sweep failed — and NEVER raises (see the module docstring)."""
        try:
            return await self._service.sweep()
        except Exception as exc:  # noqa: BLE001 - containment is the point
            self._on_error(exc)
            return 0

    async def start(self) -> None:
        """Reconcile once, then start the periodic loop.

        Reconciliation happens BEFORE the first sweep and before the loop task
        exists, so a consumed-but-unfinalised continuation is resolved while
        nothing else is changing rows underneath it. A reconciliation failure
        propagates and the loop is never started.
        """
        if self._task is not None:
            raise RuntimeError("sweeper already started")
        await self._service.reconcile_on_startup()
        self._task = asyncio.create_task(self._loop(), name="approvals-sweeper")

    async def _loop(self) -> None:
        while True:
            await self.run_once()
            await self._sleep(self._interval_s)

    async def stop(self) -> None:
        """Cancel the loop and wait for it. Idempotent, and safe before
        ``start()`` — it also runs on a shutdown that follows a failed
        startup."""
        task, self._task = self._task, None
        if task is None:
            return
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
