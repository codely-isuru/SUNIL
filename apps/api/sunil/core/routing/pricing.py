"""SUNIL-side cost arithmetic (C2 §2).

``Usage.cost_usd`` is computed here from ``config/models.yaml`` prices —
**never** taken from the gateway. A gateway-reported cost is recorded as a fact
about the gateway; the authoritative number is ours, because the price table is
versioned (``pricing_version``) and stamped onto the call record, so a later
price edit cannot rewrite the cost of a historical call.

``Decimal`` throughout, because binary floats cannot represent a price table
exactly and this is money; the conversion to the contract's ``float`` field
happens once, at the end, at a pinned rounding point.
"""

from __future__ import annotations

from collections.abc import Iterable
from decimal import ROUND_HALF_UP, Decimal

from sunil.providers.base import Usage

_PER_MTOK = Decimal(1_000_000)

#: Cost resolution. 1e-9 USD (a nano-dollar) keeps a 100-token call from
#: rounding to 0.0 at every price point in the table — a spend ledger of zeroes
#: is worse than no ledger.
_QUANTUM = Decimal("0.000000001")


def compute_cost_usd(
    *,
    input_tokens: int,
    output_tokens: int,
    input_usd_per_mtok: Decimal,
    output_usd_per_mtok: Decimal,
) -> float:
    """``(in/1e6 * in_price) + (out/1e6 * out_price)``, half-up at 1e-9 USD.

    This function does not know or care whether the attempt succeeded: a failed
    attempt that consumed tokens still costs money (C2 §4, M1 A-2 rule).
    """
    cost = (
        Decimal(input_tokens) / _PER_MTOK * Decimal(input_usd_per_mtok)
        + Decimal(output_tokens) / _PER_MTOK * Decimal(output_usd_per_mtok)
    )
    return float(cost.quantize(_QUANTUM, rounding=ROUND_HALF_UP))


def sum_usage(usages: Iterable[Usage | None]) -> Usage:
    """Total usage across attempts, INCLUDING failed ones (C2 §4 / M1 A-2).

    ``None`` entries are skipped, not treated as an error: a connect failure or
    timeout burned no tokens and legitimately reports ``usage=None``. The total
    is a real ``Usage``, never ``None`` — "we do not know what this turn cost"
    must never be representable as an absent number.
    """
    input_tokens = 0
    output_tokens = 0
    cost = Decimal(0)
    for usage in usages:
        if usage is None:
            continue
        input_tokens += usage.input_tokens
        output_tokens += usage.output_tokens
        cost += Decimal(str(usage.cost_usd))
    return Usage(
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cost_usd=float(cost.quantize(_QUANTUM, rounding=ROUND_HALF_UP)),
    )
