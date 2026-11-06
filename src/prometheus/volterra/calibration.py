"""Risk-neutral calibration: recovering an implied volatility from an
observed option price (PRI-05), rather than supplying volatility directly
to a MarketSnapshot as every other VOLTERRA entry point does.

Black-Scholes price is strictly increasing in sigma for sigma > 0 (vega is
strictly positive away from immediate expiry), so a quoted price has at
most one implied volatility. Before searching, the quote is checked
against the model's volatility-independent no-arbitrage bounds
(sigma -> 0+ and sigma -> infinity limits); a quote outside those bounds
has *no* rationalizing volatility at any level, and is rejected with a
named CalibrationError rather than handed to a root-finder that would
either fail to bracket a root or silently return a boundary value.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date

from scipy.optimize import brentq

from prometheus.volterra.black_scholes import black_scholes_price
from prometheus.volterra.instruments import EuropeanOption, OptionType
from prometheus.volterra.market import MarketSnapshot


class CalibrationError(ValueError):
    """Raised when no implied volatility can rationalize a quoted price, or
    the root-finding search otherwise fails."""


@dataclass(frozen=True, slots=True)
class ImpliedVolatilityResult:
    implied_volatility: float
    iterations: int
    price_error: float
    """black_scholes_price(calibrated market) - market_price, at the
    returned implied_volatility; a diagnostic of search precision, not a
    claim that the quote itself is noise-free (PRI-05's "implied-vol loss,
    parameter constraints and errors retained")."""


def _no_arbitrage_bounds(
    spot: float,
    strike: float,
    risk_free_rate: float,
    maturity: float,
    option_type: OptionType,
    dividend_yield: float,
) -> tuple[float, float]:
    discount_r = math.exp(-risk_free_rate * maturity)
    discount_q = math.exp(-dividend_yield * maturity)
    if option_type == "call":
        lower = max(0.0, spot * discount_q - strike * discount_r)
        upper = spot * discount_q
    else:
        lower = max(0.0, strike * discount_r - spot * discount_q)
        upper = strike * discount_r
    return lower, upper


def calibrate_implied_volatility(
    spot: float,
    strike: float,
    risk_free_rate: float,
    maturity: float,
    option_type: OptionType,
    market_price: float,
    dividend_yield: float = 0.0,
    vol_lower: float = 1e-6,
    vol_upper: float = 10.0,
    xtol: float = 1e-10,
) -> ImpliedVolatilityResult:
    if spot <= 0:
        raise ValueError("spot must be positive")
    if market_price <= 0:
        raise ValueError("market_price must be positive")
    if not vol_lower < vol_upper:
        raise ValueError("vol_lower must be < vol_upper")

    lower_bound, upper_bound = _no_arbitrage_bounds(
        spot, strike, risk_free_rate, maturity, option_type, dividend_yield
    )
    if not lower_bound < market_price < upper_bound:
        raise CalibrationError(
            f"quoted price {market_price!r} is outside the no-arbitrage bounds "
            f"({lower_bound!r}, {upper_bound!r}) for this {option_type}; no "
            "implied volatility exists at any level"
        )

    option = EuropeanOption(strike, maturity, option_type)
    iterations = 0

    def objective(sigma: float) -> float:
        nonlocal iterations
        iterations += 1
        market = MarketSnapshot(
            as_of=date.today(),
            spot=spot,
            risk_free_rate=risk_free_rate,
            volatility=sigma,
            dividend_yield=dividend_yield,
        )
        return black_scholes_price(market, option) - market_price

    try:
        root = brentq(objective, vol_lower, vol_upper, xtol=xtol)
    except ValueError as exc:
        raise CalibrationError(
            f"implied volatility search over [{vol_lower}, {vol_upper}] failed "
            f"to bracket a root: {exc}"
        ) from exc

    return ImpliedVolatilityResult(
        implied_volatility=float(root),
        iterations=iterations,
        price_error=float(objective(root)),
    )


@dataclass(frozen=True, slots=True)
class SmilePoint:
    strike: float
    market_price: float
    implied_volatility: float
    price_error: float


def calibrate_volatility_smile(
    spot: float,
    risk_free_rate: float,
    maturity: float,
    option_type: OptionType,
    quotes: list[tuple[float, float]],
    dividend_yield: float = 0.0,
) -> list[SmilePoint]:
    """Calibrate one implied volatility per (strike, market_price) quote at
    a shared spot/rate/maturity -- independently per strike (no smoothness
    or arbitrage-free-surface constraint is imposed across strikes; that is
    a separate, unimplemented concern -- PRI-11's calendar/butterfly checks
    apply to a *given* surface, not to fitting one)."""
    if not quotes:
        raise ValueError("quotes must be non-empty")
    points = []
    for strike, market_price in quotes:
        result = calibrate_implied_volatility(
            spot, strike, risk_free_rate, maturity, option_type, market_price, dividend_yield
        )
        points.append(
            SmilePoint(
                strike=strike,
                market_price=market_price,
                implied_volatility=result.implied_volatility,
                price_error=result.price_error,
            )
        )
    return points
