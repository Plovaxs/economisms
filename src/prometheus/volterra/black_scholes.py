"""Black-Scholes closed-form European option pricing and analytical Greeks.

  V_t + 0.5*sigma^2*S^2*V_SS + (r-q)*S*V_S - r*V = 0

All Greeks are reported per unit of their input (e.g. vega is price change
per 1.00 = 100 percentage points of volatility, theta is price change per
1.00 year), not rescaled to "per 1% vol" / "per calendar day" conventions --
callers rescale at the display layer if needed.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from scipy.stats import norm

from prometheus.volterra.instruments import EuropeanOption
from prometheus.volterra.market import MarketSnapshot


@dataclass(frozen=True, slots=True)
class Greeks:
    delta: float
    gamma: float
    vega: float
    theta: float
    rho: float


def _d1_d2(market: MarketSnapshot, option: EuropeanOption) -> tuple[float, float]:
    s, k, r, q, sigma, t = (
        market.spot,
        option.strike,
        market.risk_free_rate,
        market.dividend_yield,
        market.volatility,
        option.maturity,
    )
    d1 = (math.log(s / k) + (r - q + 0.5 * sigma**2) * t) / (sigma * math.sqrt(t))
    d2 = d1 - sigma * math.sqrt(t)
    return d1, d2


def black_scholes_price(market: MarketSnapshot, option: EuropeanOption) -> float:
    s, k, r, q, t = (
        market.spot,
        option.strike,
        market.risk_free_rate,
        market.dividend_yield,
        option.maturity,
    )
    d1, d2 = _d1_d2(market, option)
    if option.option_type == "call":
        return s * math.exp(-q * t) * norm.cdf(d1) - k * math.exp(-r * t) * norm.cdf(d2)
    return k * math.exp(-r * t) * norm.cdf(-d2) - s * math.exp(-q * t) * norm.cdf(-d1)


def black_scholes_greeks(market: MarketSnapshot, option: EuropeanOption) -> Greeks:
    s, k, r, q, sigma, t = (
        market.spot,
        option.strike,
        market.risk_free_rate,
        market.dividend_yield,
        market.volatility,
        option.maturity,
    )
    d1, d2 = _d1_d2(market, option)
    pdf_d1 = norm.pdf(d1)
    disc_q = math.exp(-q * t)
    disc_r = math.exp(-r * t)

    gamma = disc_q * pdf_d1 / (s * sigma * math.sqrt(t))
    vega = s * disc_q * pdf_d1 * math.sqrt(t)

    if option.option_type == "call":
        delta = disc_q * norm.cdf(d1)
        theta = (
            -(s * disc_q * pdf_d1 * sigma) / (2 * math.sqrt(t))
            - r * k * disc_r * norm.cdf(d2)
            + q * s * disc_q * norm.cdf(d1)
        )
        rho = k * t * disc_r * norm.cdf(d2)
    else:
        delta = disc_q * (norm.cdf(d1) - 1.0)
        theta = (
            -(s * disc_q * pdf_d1 * sigma) / (2 * math.sqrt(t))
            + r * k * disc_r * norm.cdf(-d2)
            - q * s * disc_q * norm.cdf(-d1)
        )
        rho = -k * t * disc_r * norm.cdf(-d2)

    return Greeks(delta=delta, gamma=gamma, vega=vega, theta=theta, rho=rho)


def put_call_parity_residual(market: MarketSnapshot, strike: float, maturity: float) -> float:
    """C - P - (S*e^{-qT} - K*e^{-rT}); should be ~0 up to floating-point
    error for any valid Black-Scholes market/strike/maturity (PRI-03)."""
    call = black_scholes_price(market, EuropeanOption(strike, maturity, "call"))
    put = black_scholes_price(market, EuropeanOption(strike, maturity, "put"))
    forward_value = market.spot * math.exp(
        -market.dividend_yield * maturity
    ) - strike * math.exp(-market.risk_free_rate * maturity)
    return (call - put) - forward_value
