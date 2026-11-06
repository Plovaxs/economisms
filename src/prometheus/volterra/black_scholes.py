"""Black-Scholes closed-form European option pricing and analytical Greeks.

  V_t + 0.5*sigma^2*S^2*V_SS + (r-q)*S*V_S - r*V = 0

All Greeks are reported per unit of their input (e.g. vega is price change
per 1.00 = 100 percentage points of volatility, theta is price change per
1.00 year), not rescaled to "per 1% vol" / "per calendar day" conventions --
callers rescale at the display layer if needed.

SDE-12 ("test solver behavior on extreme but admissible inputs... no
silent NaN, Inf or unbounded accepted paths") property-based testing
found that even this, the simplest and most foundational VOLTERRA
pricer, was not immune: a sufficiently negative `risk_free_rate` with a
long `maturity` (confirmed directly: rate=-5, maturity=142) makes
`math.exp(-r*t)` itself overflow -- an uncaught `OverflowError`, not a
silent bad value, but still a crash on an input `MarketSnapshot`/
`EuropeanOption` validation does not reject. A second, subtler failure
mode at a nearby but distinct input (rate=-4.90625, maturity=144,
strike=27) is worse: `math.exp(-r*t)` alone stays just under float64's
overflow threshold, but the PRODUCT `strike * math.exp(-r*t)` pushes
past it to `inf`, and the original code multiplied that `inf` by
`norm.cdf(d2)`, which has independently underflowed to exactly `0.0` at
this same input (`d2` is enormously negative here) -- `inf * 0.0` is
`nan`, silently, with no exception at all. Economically the true
contribution of that term is unambiguously `0` (a risk-neutral exercise
probability that has underflowed to exactly zero contributes nothing,
regardless of how large the nominal discounted notional is), so
`_discounted_expectation` below checks the probability FIRST and
short-circuits to `0.0` before ever evaluating the discount factor --
both resolving the `nan` case correctly and avoiding the `OverflowError`
case whenever the weight on that unrepresentable term is exactly zero.
Only when the probability is genuinely nonzero AND the discount factor
is unrepresentable does it raise a clear `ValueError`, matching the
pattern already used in `volterra.barrier_options` and
`volterra.merton_pricer`.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from scipy.stats import norm

from prometheus.volterra.instruments import EuropeanOption
from prometheus.volterra.market import MarketSnapshot

_MAX_EXP_ARG = 700.0
"""Safely below float64's ~709.78 overflow threshold for math.exp --
same constant and rationale as `volterra.barrier_options._MAX_EXP_ARG`
and `volterra.merton_pricer._MAX_EXP_ARG`."""


def _discounted_expectation(
    notional: float, rate: float, maturity: float, probability: float
) -> float:
    """notional * exp(-rate*maturity) * probability -- see this module's
    docstring (SDE-12) for why the probability is checked first."""
    if probability == 0.0:
        return 0.0
    exponent = -rate * maturity
    if exponent > _MAX_EXP_ARG:
        raise ValueError(
            f"rate={rate} and maturity={maturity} push the discount factor "
            f"exp({exponent:.1f}) beyond what float64 can represent, and the "
            f"risk-neutral weight on this term ({probability}) is nonzero -- "
            "this input combination has no computable answer under this closed form"
        )
    return notional * math.exp(exponent) * probability


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
        return _discounted_expectation(s, q, t, norm.cdf(d1)) - _discounted_expectation(
            k, r, t, norm.cdf(d2)
        )
    return _discounted_expectation(k, r, t, norm.cdf(-d2)) - _discounted_expectation(
        s, q, t, norm.cdf(-d1)
    )


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
    disc_q_pdf = _discounted_expectation(1.0, q, t, pdf_d1)

    gamma = disc_q_pdf / (s * sigma * math.sqrt(t))
    vega = s * math.sqrt(t) * disc_q_pdf

    if option.option_type == "call":
        delta = _discounted_expectation(1.0, q, t, norm.cdf(d1))
        theta = (
            -(s * sigma / (2 * math.sqrt(t))) * disc_q_pdf
            - r * _discounted_expectation(k, r, t, norm.cdf(d2))
            + q * _discounted_expectation(s, q, t, norm.cdf(d1))
        )
        rho = _discounted_expectation(k * t, r, t, norm.cdf(d2))
    else:
        delta = _discounted_expectation(1.0, q, t, norm.cdf(d1) - 1.0)
        theta = (
            -(s * sigma / (2 * math.sqrt(t))) * disc_q_pdf
            + r * _discounted_expectation(k, r, t, norm.cdf(-d2))
            - q * _discounted_expectation(s, q, t, norm.cdf(-d1))
        )
        rho = -_discounted_expectation(k * t, r, t, norm.cdf(-d2))

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
