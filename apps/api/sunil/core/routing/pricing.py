"""Cost computation, micro-USD, from the pinned price table (§4.4, §13.1).

`BigInteger` micro-USD, never `Numeric` (§7.2 — `Numeric` is lossy and
warns on SQLite). Rounding happens once, here, to the nearest micro-USD —
never at the API edge, which formats dollars for display only.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

from sunil.providers.base import ModelCapabilities

_MICRO = Decimal(1_000_000)


def compute_cost_micro_usd(
    *, input_tokens: int, output_tokens: int, capabilities: ModelCapabilities
) -> int:
    """`(in/1e6 * in_price) + (out/1e6 * out_price)`, rounded to the
    nearest micro-USD integer.

    A failed attempt that consumed tokens still costs money (§13.1) — this
    function does not know or care whether the attempt succeeded; the
    caller (the Model Router) computes cost the same way either way.
    """
    cost_usd = (
        Decimal(input_tokens) / _MICRO * capabilities.input_usd_per_mtok
        + Decimal(output_tokens) / _MICRO * capabilities.output_usd_per_mtok
    )
    return int((cost_usd * _MICRO).to_integral_value(rounding=ROUND_HALF_UP))
