"""The `TraceContext` interface, and its concrete implementation.

T1 owns the *interface* — the `Protocol` and `NullTraceContext`. T4 owns
the concrete implementation (`LiveTraceContext`, this task's build), and
made one refinement to the Protocol itself while building it: `emit()` is
**async** and takes `summary`/`task_id`, matching
`ARCHITECTURE_V1.md` §8.1's own pseudocode
(`async def emit(self, stage, *, summary, detail=None, task_id=None)`) and
what an `audit_events` insert actually requires (`summary` is `NOT NULL`).
T1's original signature was synchronous with `stage`/`detail` only; no
other lane had started building against it yet (checked before making this
change), so this is recorded here rather than treated as a silent edit.

This split exists so BE-2 (T6's Model Router, T8's tool framework) can be
written and unit-tested against `NullTraceContext` from hour two, without
waiting for T4's emitter — only their *integration* tests need T4 merged
(`docs/M1_BUILD_PLAN.md` §1.2 note).
"""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any, Protocol, runtime_checkable

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from sunil.core.trace.emitter import emit_stage
from sunil.core.trace.stages import TraceStage


class DuplicateStageEmission(Exception):
    """Raised when a turn tries to emit a `TraceStage` a second time.

    Each of the twelve stages is emitted at most once per turn (§3.4) —
    this is what makes that a structural guarantee rather than a
    convention: retries belong in `detail`, never as a second stage event.
    """


@runtime_checkable
class TraceContext(Protocol):
    """What every component that advances a turn depends on.

    `emit()` is the *only* way a stage advances (ARCHITECTURE_V1.md §3.4) —
    there is no second path, which is what makes ET-6 provable rather than
    aspirational.
    """

    request_id: str
    user_id: str | None
    conversation_id: str | None

    async def emit(
        self,
        stage: TraceStage,
        *,
        summary: str,
        detail: dict[str, Any] | None = None,
        task_id: str | None = None,
    ) -> None:
        """Record that `stage` occurred for this turn.

        Implementations write to every configured sink. Each stage must be
        emitted at most once per turn (§3.4) — retries belong in `detail`.
        """
        ...

    def remaining_deadline_s(self) -> float:
        """Seconds left before `SUNIL_TURN_DEADLINE_S` is breached for this
        turn (§5.3). The Model Router (T6) and the tool framework (T8) must
        check this before starting any attempt: an attempt whose own
        timeout exceeds what remains is not started.
        """
        ...


class NullTraceContext:
    """A `TraceContext` that records emissions in memory and never breaches
    its deadline. Used by unit tests, and by any lane building ahead of
    T4's real emitter.
    """

    def __init__(
        self,
        *,
        request_id: str = "null",
        user_id: str | None = None,
        conversation_id: str | None = None,
    ) -> None:
        self.request_id = request_id
        self.user_id = user_id
        self.conversation_id = conversation_id
        self.emitted: list[tuple[TraceStage, str, dict[str, Any] | None, str | None]] = []

    async def emit(
        self,
        stage: TraceStage,
        *,
        summary: str,
        detail: dict[str, Any] | None = None,
        task_id: str | None = None,
    ) -> None:
        self.emitted.append((stage, summary, detail, task_id))

    def remaining_deadline_s(self) -> float:
        return float("inf")


class LiveTraceContext:
    """The concrete `TraceContext` (T4).

    Holds the per-turn state `ARCHITECTURE_V1.md` §8.1 names —
    `request_id`, `user_id`, `conversation_id`, `started_at` (monotonic),
    `seq` — and the §5.3 turn deadline. `emit()` is the one call site that
    advances a stage; it enforces "at most once per turn" itself
    (`DuplicateStageEmission`) rather than trusting callers to comply, and
    delegates the actual three-sink write to `core.trace.emitter.emit_stage()`.
    """

    def __init__(
        self,
        *,
        request_id: str,
        user_id: str | None,
        conversation_id: str | None,
        sessionmaker: async_sessionmaker[AsyncSession],
        turn_deadline_s: float,
        actor: str = "api",
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.request_id = request_id
        self.user_id = user_id
        self.conversation_id = conversation_id
        self._sessionmaker = sessionmaker
        self._turn_deadline_s = turn_deadline_s
        self._actor = actor
        self._clock = clock
        self._started_monotonic = clock()
        self._seq = 0
        self._emitted_stages: set[TraceStage] = set()

    def _offset_ms(self) -> int:
        return int((self._clock() - self._started_monotonic) * 1000)

    def remaining_deadline_s(self) -> float:
        """Never negative: a caller doing `if remaining < attempt_timeout`
        gets a clean "no budget left" rather than having to also handle a
        sign flip."""
        elapsed = self._clock() - self._started_monotonic
        return max(0.0, self._turn_deadline_s - elapsed)

    async def emit(
        self,
        stage: TraceStage,
        *,
        summary: str,
        detail: dict[str, Any] | None = None,
        task_id: str | None = None,
    ) -> None:
        if stage in self._emitted_stages:
            raise DuplicateStageEmission(
                f"stage {stage.value!r} already emitted for request "
                f"{self.request_id!r} — retries belong in `detail` "
                "(`provider_attempts`, `plan_attempts`), never a second "
                "stage event (§3.4)."
            )
        self._emitted_stages.add(stage)
        self._seq += 1

        await emit_stage(
            sessionmaker=self._sessionmaker,
            request_id=self.request_id,
            seq=self._seq,
            offset_ms=self._offset_ms(),
            stage=stage,
            task_id=task_id,
            actor=self._actor,
            summary=summary,
            detail=detail,
        )
