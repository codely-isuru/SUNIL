"""Bounded retry primitives for the Model Router (ADR-000 Q6, §4.5, §5.3).

**3 provider attempts max per logical request**, full-jitter exponential
backoff (bases 1s/2s/4s). **The turn deadline is checked before every
attempt** — an attempt whose own timeout would exceed the remaining
`SUNIL_TURN_DEADLINE_S` budget is never started: "a retry that cannot
finish is not a retry, it is a way to blow the latency budget quietly"
(§5.3).
"""

from __future__ import annotations

import random
from collections.abc import Callable

MAX_ATTEMPTS = 3

# Backoff base in seconds, indexed by "this many attempts have already
# failed" — 1 failed attempt -> 1s base, 2 -> 2s, 3 or more -> 4s
# (ADR-000 Q6). `sleep = random() * base` (full jitter).
_BACKOFF_BASE_SECONDS: tuple[float, ...] = (1.0, 2.0, 4.0)


class TurnDeadlineExceeded(Exception):
    """The remaining per-turn deadline (`SUNIL_TURN_DEADLINE_S`, §5.3)
    cannot accommodate another attempt.

    Deliberately **not** a `ProviderError` — the provider was never
    called this time, so there is nothing to record as an attempt. This
    lets the orchestrator (T11b) set `error_kind=turn_deadline_exceeded`
    precisely, distinct from `ProviderExhaustedError`'s
    `retries_exhausted` (§11.3 both map to `failure.kind=provider_error`,
    but the trace `detail`/`tasks.failure_kind` must say which).
    """

    def __init__(self, *, remaining_s: float, needed_s: float) -> None:
        self.remaining_s = remaining_s
        self.needed_s = needed_s
        super().__init__(
            f"turn deadline: only {remaining_s:.1f}s remaining, "
            f"this attempt needs up to {needed_s:.1f}s"
        )


def backoff_seconds(failed_attempts: int, *, rand: Callable[[], float] = random.random) -> float:
    """Full jitter: `sleep = random() * base`.

    `failed_attempts` is how many attempts have failed *so far* (1 before
    the second attempt is made, 2 before the third). `rand` is injectable
    so a unit test can assert the exact base without depending on a real
    random draw.
    """
    index = min(max(failed_attempts - 1, 0), len(_BACKOFF_BASE_SECONDS) - 1)
    return rand() * _BACKOFF_BASE_SECONDS[index]
