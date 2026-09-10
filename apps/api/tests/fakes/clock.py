"""Deterministic test clock shared by the Phase 0 fakes.

The contracts call for an "injectable clock" (C4 §6) and for fixed timestamps
(C3 §5: ``created_at`` = ``2026-01-01T00:00:00Z`` plus ``write_index`` seconds)
without naming a type; this is that mechanism. Whole seconds only, so every
rendered timestamp is byte-stable across runs and machines.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

#: C4 §6 / C3 §5 default epoch for the fakes.
DEFAULT_START = "2026-01-01T00:00:00Z"


def to_iso(moment: datetime) -> str:
    """Render an aware datetime as the contracts' ISO-8601 UTC form (``…Z``)."""
    return moment.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def from_iso(text: str) -> datetime:
    """Parse a contract ISO-8601 UTC timestamp (``…Z`` accepted since 3.11)."""
    return datetime.fromisoformat(text)


class FakeClock:
    """A monotonic, hand-advanced clock starting at ``DEFAULT_START``."""

    def __init__(self, start: str = DEFAULT_START) -> None:
        self._now = from_iso(start)

    def now(self) -> datetime:
        return self._now

    def iso(self) -> str:
        return to_iso(self._now)

    def advance(self, *, seconds: int = 0, minutes: int = 0, hours: int = 0) -> None:
        self._now += timedelta(seconds=seconds, minutes=minutes, hours=hours)
