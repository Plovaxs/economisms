"""A risk-neutral market snapshot.

SDE-09 / the MarketState integration contract (section 02): every pricing
input is explicitly tagged with its measure, and VOLTERRA only ever accepts
"Q" -- constructing a snapshot tagged "P" raises immediately, so a
physical-measure calibration cannot be fed into a pricing call by accident.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from prometheus.numerics import require_finite


@dataclass(frozen=True, slots=True)
class MarketSnapshot:
    as_of: date
    spot: float
    risk_free_rate: float
    volatility: float
    dividend_yield: float = 0.0
    measure: str = "Q"

    def __post_init__(self) -> None:
        require_finite(
            spot=self.spot,
            risk_free_rate=self.risk_free_rate,
            volatility=self.volatility,
            dividend_yield=self.dividend_yield,
        )
        if self.measure != "Q":
            raise ValueError(
                f"VOLTERRA pricing requires a risk-neutral (Q) market snapshot, "
                f"got measure={self.measure!r}"
            )
        if self.spot <= 0:
            raise ValueError("spot must be positive")
        if self.volatility <= 0:
            raise ValueError("volatility must be positive")
