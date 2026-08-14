"""`sunil.core.routing.retry` — bounded retry primitives (ADR-000 Q6,
§5.3)."""

from __future__ import annotations

from sunil.core.routing.retry import MAX_ATTEMPTS, TurnDeadlineExceeded, backoff_seconds


def test_max_attempts_is_three_per_adr_000_q6() -> None:
    assert MAX_ATTEMPTS == 3


def test_backoff_bases_are_1_2_4_seconds_with_full_jitter() -> None:
    # rand() pinned to 1.0 isolates the base from the jitter.
    assert backoff_seconds(1, rand=lambda: 1.0) == 1.0
    assert backoff_seconds(2, rand=lambda: 1.0) == 2.0
    assert backoff_seconds(3, rand=lambda: 1.0) == 4.0


def test_full_jitter_scales_the_base_not_replaces_it() -> None:
    assert backoff_seconds(1, rand=lambda: 0.5) == 0.5
    assert backoff_seconds(2, rand=lambda: 0.25) == 0.5


def test_backoff_never_indexes_past_the_last_base() -> None:
    """A fourth-or-later failed attempt should not raise `IndexError` —
    defensive, since `MAX_ATTEMPTS` bounds the router's own loop to 3, but
    this function should not silently rely on being called in range."""
    assert backoff_seconds(10, rand=lambda: 1.0) == 4.0


def test_turn_deadline_exceeded_carries_both_numbers() -> None:
    error = TurnDeadlineExceeded(remaining_s=3.2, needed_s=20.0)

    assert error.remaining_s == 3.2
    assert error.needed_s == 20.0
    assert "3.2" in str(error)
    assert "20.0" in str(error)
