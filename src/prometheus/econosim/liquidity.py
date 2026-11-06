"""Bid/ask spread and liquidity cost model (LED-09: "define market
bid/ask spread and liquidity assumptions... no zero-cost trades unless
explicit frictionless baseline").

Every trade in this repository's econosim ledger (`Household.consume`,
`Firm.pay_wages`, market clearing/settlement) executes at a single
price with no spread at all -- not because frictionless trading was a
deliberate baseline anywhere, but because no bid/ask spread concept
existed to apply. `LiquidityAssumptions` closes that gap as a pure,
composable quoting/cost model (no ledger side effects, the same
"caller composes it" pattern `econosim.insolvency.allocate_recovery`
already uses for loss allocation): a buyer pays the ASK (mid * (1 +
spread/2)), a seller receives the BID (mid * (1 - spread/2)), and the
caller decides where the spread's proceeds go (a market-maker account,
if one exists, or simply a friction cost that reduces both parties'
combined wealth versus trading at the frictionless mid).

"No zero-cost trades unless explicit frictionless baseline" is enforced
directly in `__post_init__`, not left as a convention a caller might
forget: `spread_bps == 0` requires setting `frictionless=True`
explicitly, and `frictionless=True` requires `spread_bps == 0` -- a
caller cannot get a zero-cost quote by accident, only by a flag that
states the choice in the same line.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class LiquidityAssumptions:
    spread_bps: float
    """The full round-trip bid/ask spread, in basis points of mid price
    (100 bps = 1%); a buy-then-immediately-sell round trip at these
    quotes costs exactly this fraction of notional."""

    frictionless: bool = False
    """Must be set True to allow spread_bps == 0 -- see this module's
    own docstring for why that is required, not merely permitted."""

    def __post_init__(self) -> None:
        if self.spread_bps < 0:
            raise ValueError("spread_bps must be non-negative")
        if self.spread_bps == 0.0 and not self.frictionless:
            raise ValueError(
                "spread_bps == 0 requires frictionless=True to be set explicitly -- "
                "no zero-cost trades unless explicit frictionless baseline (LED-09)"
            )
        if self.frictionless and self.spread_bps != 0.0:
            raise ValueError(
                f"frictionless=True requires spread_bps == 0, got {self.spread_bps}"
            )


def ask_price(mid_price: float, assumptions: LiquidityAssumptions) -> float:
    """The price a BUYER pays: at or above mid, by half the spread."""
    if mid_price <= 0:
        raise ValueError("mid_price must be positive")
    return mid_price * (1.0 + assumptions.spread_bps / 2.0 / 10_000.0)


def bid_price(mid_price: float, assumptions: LiquidityAssumptions) -> float:
    """The price a SELLER receives: at or below mid, by half the
    spread."""
    if mid_price <= 0:
        raise ValueError("mid_price must be positive")
    return mid_price * (1.0 - assumptions.spread_bps / 2.0 / 10_000.0)


def round_trip_cost(notional: float, assumptions: LiquidityAssumptions) -> float:
    """The cost (in currency units, not bps) of buying then immediately
    selling `notional` worth of the asset at these quotes -- exactly
    `notional * spread_bps / 10,000`, since the buyer overpays by half
    the spread and the seller is underpaid by the other half."""
    if notional < 0:
        raise ValueError("notional must be non-negative")
    return notional * assumptions.spread_bps / 10_000.0
