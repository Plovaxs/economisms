"""Leverage and position-size constraint projection for hedging policies
(HDG-07: "leverage, concentration and position constraints... all
proposed actions obey projected feasible region").

`HedgePolicyMLP` already tanh-squashes its raw output to [-1, 1]
(HDG-04), but that is a fixed architectural bound baked into the policy
itself, not a configurable, explicitly-checked leverage/position limit a
caller can state in economic terms ("no more than N shares," "no more
than L times capital in notional exposure") and have enforced on ANY
policy's proposed holdings -- baseline or learned alike, after the fact,
the same way a real trading desk's risk limits are enforced independently
of whatever strategy proposed the trade.

`project_onto_feasible_region` is that independent check: given a
proposed holding (in units of the underlying) and the spot price at the
decision time, it clips the holding to the INTERSECTION of a flat
position-size cap and a leverage-implied notional cap (capital *
max_leverage, converted to units via the current spot price) -- the
tighter of the two always applies. "Concentration" is not independently
meaningful here: this repository's hedging setup is single-underlying
per policy (one option, one hedge instrument), so there is nothing to
be concentrated relative to; it would only become meaningful with a
genuinely multi-instrument hedge book, which does not exist yet (the
multi-asset analogue, PortfolioConstraints.max_weight_per_asset in
titan.portfolio, OPT-06, already exists for that different setting).
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True, slots=True)
class PositionLimits:
    max_position: float
    max_leverage: float
    capital: float

    def __post_init__(self) -> None:
        if self.max_position <= 0:
            raise ValueError("max_position must be positive")
        if self.max_leverage <= 0:
            raise ValueError("max_leverage must be positive")
        if self.capital <= 0:
            raise ValueError("capital must be positive")


def project_onto_feasible_region(
    proposed_holdings: np.ndarray, spot: np.ndarray, limits: PositionLimits
) -> np.ndarray:
    """Clips `proposed_holdings` (any shape) to [-bound, bound] elementwise,
    where bound = min(max_position, capital * max_leverage / |spot|) --
    the tighter of a flat position-size cap and a leverage-implied
    notional cap, evaluated per element against its own paired spot
    price. `spot` must match `proposed_holdings`'s shape exactly: the
    leverage bound is price-dependent, so there is no single scalar
    spot that could stand in for a whole path/step grid."""
    proposed_holdings = np.asarray(proposed_holdings, dtype=float)
    spot = np.asarray(spot, dtype=float)
    if spot.shape != proposed_holdings.shape:
        raise ValueError(
            f"spot must have the same shape as proposed_holdings "
            f"({proposed_holdings.shape}), got {spot.shape}"
        )
    leverage_bound = limits.capital * limits.max_leverage / np.abs(spot)
    bound = np.minimum(limits.max_position, leverage_bound)
    return np.asarray(np.clip(proposed_holdings, -bound, bound), dtype=float)
