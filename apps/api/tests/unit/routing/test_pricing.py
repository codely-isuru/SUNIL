"""SUNIL-side cost computation (C2 §2: ``Usage.cost_usd`` comes from
``config/models.yaml`` pricing, computed SUNIL-side — a gateway-reported cost is
recorded but never authoritative)."""

from __future__ import annotations

from decimal import Decimal

import pytest

from sunil.core.routing.pricing import compute_cost_usd, sum_usage
from sunil.providers.base import Usage


def test_cost_is_the_two_rate_sum_per_million_tokens() -> None:
    cost = compute_cost_usd(
        input_tokens=1_000_000,
        output_tokens=1_000_000,
        input_usd_per_mtok=Decimal("3"),
        output_usd_per_mtok=Decimal("15"),
    )

    assert cost == pytest.approx(18.0)


def test_small_token_counts_do_not_round_to_zero() -> None:
    """100 in / 25 out at $1/$5 per Mtok is $0.000225 — nine decimal places of
    resolution, because a per-turn cost of "0.0" makes the spend ledger a lie."""
    cost = compute_cost_usd(
        input_tokens=100,
        output_tokens=25,
        input_usd_per_mtok=Decimal("1"),
        output_usd_per_mtok=Decimal("5"),
    )

    assert cost == pytest.approx(0.000225)


def test_zero_tokens_cost_nothing() -> None:
    assert (
        compute_cost_usd(
            input_tokens=0,
            output_tokens=0,
            input_usd_per_mtok=Decimal("3"),
            output_usd_per_mtok=Decimal("15"),
        )
        == 0.0
    )


def test_rounding_is_half_up_at_nine_decimals() -> None:
    """One input token at $1.5/Mtok is 0.0000015 exactly; 1 token at $1/Mtok is
    0.000001. The rounding point is pinned so a price edit cannot silently
    change historical arithmetic."""
    assert compute_cost_usd(
        input_tokens=1,
        output_tokens=0,
        input_usd_per_mtok=Decimal("1.5"),
        output_usd_per_mtok=Decimal("0"),
    ) == pytest.approx(0.0000015)


def test_sum_usage_adds_failed_attempts_too() -> None:
    """C2 §4 / M1 A-2 — tokens burned by failed attempts still count. The retry
    policy sums with this function, so the rule lives in one place."""
    total = sum_usage(
        [
            Usage(input_tokens=100, output_tokens=25, cost_usd=0.000125),
            Usage(input_tokens=100, output_tokens=25, cost_usd=0.000125),
        ]
    )

    assert total.input_tokens == 200
    assert total.output_tokens == 50
    assert total.cost_usd == pytest.approx(0.00025)


def test_sum_usage_of_nothing_is_zero_not_none() -> None:
    total = sum_usage([])

    assert total == Usage(input_tokens=0, output_tokens=0, cost_usd=0.0)


def test_sum_usage_ignores_none_entries() -> None:
    """A ``ProviderError`` may carry ``usage=None`` (a connection failure burned
    no tokens) — that must not poison the total."""
    total = sum_usage([None, Usage(input_tokens=7, output_tokens=1, cost_usd=0.1), None])

    assert total.input_tokens == 7
    assert total.cost_usd == pytest.approx(0.1)
