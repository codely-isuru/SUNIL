"""`sunil.core.routing.pricing` — cost computation, micro-USD (§4.4,
§13.1)."""

from __future__ import annotations

from sunil.core.routing.pricing import compute_cost_micro_usd

from .conftest import make_model_capabilities


def test_computes_exact_cost_for_round_numbers() -> None:
    # sonnet-5 pricing: $2/MTok in, $10/MTok out (§4.4).
    capabilities = make_model_capabilities(input_usd_per_mtok="2", output_usd_per_mtok="10")

    cost = compute_cost_micro_usd(
        input_tokens=1_000_000, output_tokens=500_000, capabilities=capabilities
    )

    # 1_000_000/1e6 * $2 + 500_000/1e6 * $10 = $2 + $5 = $7 = 7_000_000 micro-USD.
    assert cost == 7_000_000


def test_zero_tokens_costs_zero() -> None:
    capabilities = make_model_capabilities()

    cost = compute_cost_micro_usd(input_tokens=0, output_tokens=0, capabilities=capabilities)

    assert cost == 0


def test_rounds_to_the_nearest_micro_usd_integer() -> None:
    capabilities = make_model_capabilities(input_usd_per_mtok="1", output_usd_per_mtok="1")

    # 3 input tokens at $1/MTok = 0.000003 USD = 3 micro-USD exactly.
    cost = compute_cost_micro_usd(input_tokens=3, output_tokens=0, capabilities=capabilities)

    assert cost == 3
    assert isinstance(cost, int)


def test_a_failed_attempts_tokens_still_cost_something() -> None:
    """§13.1: 'a failed attempt that consumed input tokens still costs
    money and still appears' — this function does not know or care
    whether the call that produced these token counts succeeded."""
    capabilities = make_model_capabilities(input_usd_per_mtok="2", output_usd_per_mtok="10")

    cost = compute_cost_micro_usd(input_tokens=500, output_tokens=0, capabilities=capabilities)

    assert cost > 0
