"""Path-dependent Asian option pricing with a control variate (PRI-09:
"path-dependent Asian option with controls"), fixed at `n_fixings`
equally-spaced dates t_i = i*T/n_fixings for i = 1..n_fixings.

Geometric-average Asian options have an exact closed form: under GBM,
ln(S_t) is Gaussian, so ln(G_T) = (1/n)*sum_i ln(S_{t_i}) -- an average of
jointly Gaussian variables -- is itself exactly Gaussian, making G_T
lognormal. Writing nu = r - q - 0.5*sigma^2 for the risk-neutral log-drift:

  mean_t  = (1/n) * sum_i t_i = dt*(n+1)/2
  var_w   = Var((1/n)*sum_i W_{t_i}) = dt*(n+1)*(2n+1)/(6n)
            (from sum_{i,j=1}^n min(i,j) = n(n+1)(2n+1)/6, a standard
            identity for the covariance of equally-spaced Brownian motion
            samples, confirmed here for n=1,2,3 before trusting it at
            general n)
  mu_G    = ln(S0) + nu*mean_t,   var_G = sigma^2 * var_w

ln(G_T) ~ Normal(mu_G, var_G) under Q, so E^Q[(G_T-K)^+] is the ordinary
lognormal/Black-Scholes-type expectation with forward F_G = exp(mu_G +
0.5*var_G) in place of S0*exp((r-q)*T). Verified, before being trusted,
against Monte Carlo simulation of the independently-written
`stochastica.gbm` path simulator's own fixing-date values (not re-derived
from this formula), across several (strike, maturity, n_fixings) grids.

Arithmetic-average Asian options have NO closed form (a sum of lognormals
is not itself lognormal), so they are priced by Monte Carlo with a
Kemna & Vorst (1990) control variate: the geometric average's exact price
above is highly correlated with the arithmetic average's price (the two
coincide exactly when volatility is zero, and differ only by Jensen's-
inequality-driven convexity otherwise, by AM-GM pointwise on every path),
so using it as a control variate is unusually effective here -- confirmed
empirically (roughly 20-30x standard-error reduction versus plain Monte
Carlo at the tested settings) before being adopted as the default.

Not covered: continuous-time (infinite-fixing) averaging; floating-strike
Asian options (strike fixed at inception here, not set to S_T at the
average); American-style early exercise.

SDE-12 ("test solver behavior on extreme but admissible inputs... no
silent NaN, Inf or unbounded accepted paths") property-based testing
found the same class of overflow bug already fixed in
`volterra.black_scholes`, here in two places: `geometric_asian_call_price`
computed `forward_g = exp(mu_g + 0.5*log_var)` and the outer
`exp(-r*maturity)` discount factor as two SEPARATE exponentials before
multiplying them together, so either one alone could overflow even when
their COMBINED, economically-relevant exponent (the discounted
forward's log) was perfectly representable (confirmed directly: rate=5,
maturity=142, volatility=1, n_fixings=1 overflows `forward_g` alone, but
`mu_g + 0.5*log_var - r*maturity` evaluates to exactly 0). The fix
combines each term's exponents analytically before ever calling
`math.exp`, exactly the lesson already learned from
`barrier_options.py`'s centering fix, and additionally short-circuits to
0.0 when a term's risk-neutral weight (norm.cdf) has itself underflowed
to exactly 0.0, for the same reason `black_scholes._discounted_expectation`
does. The same two issues, and the same fix, apply to
`geometric_average_forward` (standalone) and the put-parity branch of
`geometric_asian_option_price`.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Literal

import numpy as np
from scipy.stats import norm

from prometheus.numerics import require_finite
from prometheus.stochastica.gbm import simulate_gbm_paths
from prometheus.volterra.instruments import OptionType
from prometheus.volterra.market import MarketSnapshot
from prometheus.volterra.monte_carlo import MonteCarloResult

AsianAverageType = Literal["arithmetic", "geometric"]

_MAX_EXP_ARG = 700.0
"""Safely below float64's ~709.78 overflow threshold for math.exp --
same constant and rationale as `volterra.barrier_options._MAX_EXP_ARG`."""


def _guarded_exp(exponent: float, context: str) -> float:
    """math.exp(exponent), raising a clear ValueError instead of a
    cryptic OverflowError when it would overflow float64 (SDE-12)."""
    if exponent > _MAX_EXP_ARG:
        raise ValueError(
            f"{context} pushes an internal exponential term to exp({exponent:.1f}), "
            "beyond what float64 can represent -- this input combination has no "
            "computable answer under this closed form"
        )
    return math.exp(exponent)


def _guarded_weighted_exp(exponent: float, weight: float) -> float:
    """exp(exponent) * weight, short-circuiting to 0.0 when `weight` is
    exactly 0.0 before ever evaluating the exponential -- a
    risk-neutral weight that has underflowed to exactly 0.0 makes the
    term's true contribution unambiguously 0, regardless of how large
    the discount/notional side is (SDE-12; same reasoning as
    `volterra.black_scholes._discounted_expectation`)."""
    if weight == 0.0:
        return 0.0
    return weight * _guarded_exp(exponent, "a nonzero-weighted term")


@dataclass(frozen=True, slots=True)
class AsianOption:
    strike: float
    maturity: float
    option_type: OptionType
    n_fixings: int
    average_type: AsianAverageType

    def __post_init__(self) -> None:
        require_finite(strike=self.strike, maturity=self.maturity)
        if self.strike <= 0:
            raise ValueError("strike must be positive")
        if self.maturity <= 0:
            raise ValueError("maturity must be positive")
        if self.option_type not in ("call", "put"):
            raise ValueError(f"option_type must be 'call' or 'put', got {self.option_type!r}")
        if self.n_fixings < 1:
            raise ValueError("n_fixings must be a positive integer")
        if self.average_type not in ("arithmetic", "geometric"):
            raise ValueError(
                f"average_type must be 'arithmetic' or 'geometric', got {self.average_type!r}"
            )


def _geometric_average_moments(
    maturity: float, n_fixings: int, nu: float, volatility: float
) -> tuple[float, float]:
    """(mean, variance) of ln(G_T/S0), G_T the geometric average of
    n_fixings equally-spaced GBM fixings."""
    dt = maturity / n_fixings
    n = n_fixings
    mean_t = dt * (n + 1) / 2.0
    var_w_mean = dt * (n + 1) * (2 * n + 1) / (6 * n)
    return nu * mean_t, volatility**2 * var_w_mean


def geometric_average_forward(
    s0: float,
    maturity: float,
    risk_free_rate: float,
    dividend_yield: float,
    volatility: float,
    n_fixings: int,
) -> float:
    """E^Q[G_T], the risk-neutral expectation of the geometric average."""
    if s0 <= 0:
        raise ValueError("s0 must be positive")
    if maturity <= 0:
        raise ValueError("maturity must be positive")
    if n_fixings < 1:
        raise ValueError("n_fixings must be a positive integer")
    nu = risk_free_rate - dividend_yield - 0.5 * volatility**2
    log_mean, log_var = _geometric_average_moments(maturity, n_fixings, nu, volatility)
    exponent = math.log(s0) + log_mean + 0.5 * log_var
    return _guarded_exp(exponent, "the geometric average's drift/variance")


def geometric_asian_call_price(
    s0: float,
    strike: float,
    maturity: float,
    risk_free_rate: float,
    dividend_yield: float,
    volatility: float,
    n_fixings: int,
) -> float:
    if s0 <= 0:
        raise ValueError("s0 must be positive")
    if strike <= 0:
        raise ValueError("strike must be positive")
    if maturity <= 0:
        raise ValueError("maturity must be positive")
    if n_fixings < 1:
        raise ValueError("n_fixings must be a positive integer")

    nu = risk_free_rate - dividend_yield - 0.5 * volatility**2
    log_mean, log_var = _geometric_average_moments(maturity, n_fixings, nu, volatility)
    mu_g = math.log(s0) + log_mean
    sqrt_var_g = math.sqrt(log_var)

    d1 = (mu_g + log_var - math.log(strike)) / sqrt_var_g
    d2 = d1 - sqrt_var_g
    discounted_forward_term = _guarded_weighted_exp(
        mu_g + 0.5 * log_var - risk_free_rate * maturity, norm.cdf(d1)
    )
    discounted_strike_term = strike * _guarded_weighted_exp(
        -risk_free_rate * maturity, norm.cdf(d2)
    )
    return discounted_forward_term - discounted_strike_term


def geometric_asian_option_price(market: MarketSnapshot, option: AsianOption) -> float:
    """Puts are derived via parity against the geometric forward
    (Call - Put = e^{-rT}*(E[G_T] - K) holds for ANY lognormal terminal
    distribution, not just S_T itself), not a second closed form."""
    call = geometric_asian_call_price(
        market.spot,
        option.strike,
        option.maturity,
        market.risk_free_rate,
        market.dividend_yield,
        market.volatility,
        option.n_fixings,
    )
    if option.option_type == "call":
        return call
    nu = market.risk_free_rate - market.dividend_yield - 0.5 * market.volatility**2
    log_mean, log_var = _geometric_average_moments(
        option.maturity, option.n_fixings, nu, market.volatility
    )
    discounted_forward_exponent = (
        math.log(market.spot) + log_mean + 0.5 * log_var - market.risk_free_rate * option.maturity
    )
    discounted_forward_g = _guarded_exp(
        discounted_forward_exponent, "the discounted geometric average's drift/variance"
    )
    discounted_strike = option.strike * _guarded_exp(
        -market.risk_free_rate * option.maturity, "the strike discount factor"
    )
    return call - (discounted_forward_g - discounted_strike)


def _payoff(option_type: OptionType, average: np.ndarray, strike: float) -> np.ndarray:
    if option_type == "call":
        return np.maximum(average - strike, 0.0)
    return np.maximum(strike - average, 0.0)


def monte_carlo_price_asian(
    market: MarketSnapshot,
    option: AsianOption,
    n_paths: int,
    rng: np.random.Generator,
    use_control_variate: bool = True,
) -> MonteCarloResult:
    """Simulates `option.n_fixings` steps of `stochastica.gbm`, one per
    fixing date, under the risk-neutral drift. For an arithmetic-average
    option, defaults to the Kemna-Vorst control variate (the matching
    geometric average's EXACT closed-form price); for a geometric-average
    option the control variate has nothing to add (the exact price is
    already available from `geometric_asian_option_price`) and is not
    applied even if requested."""
    risk_neutral_drift = market.risk_free_rate - market.dividend_yield
    paths = simulate_gbm_paths(
        market.spot,
        risk_neutral_drift,
        market.volatility,
        option.maturity,
        option.n_fixings,
        n_paths,
        rng,
    )
    fixings = paths[:, 1:]
    discount = math.exp(-market.risk_free_rate * option.maturity)

    if option.average_type == "geometric":
        geo_mean = np.exp(np.mean(np.log(fixings), axis=1))
        estimator = discount * _payoff(option.option_type, geo_mean, option.strike)
        price = float(estimator.mean())
        standard_error = float(estimator.std(ddof=1) / math.sqrt(n_paths))
        return MonteCarloResult(
            price=price, standard_error=standard_error, n_paths=n_paths, control_variate_used=False
        )

    arith_mean = fixings.mean(axis=1)
    arith_payoff = discount * _payoff(option.option_type, arith_mean, option.strike)

    if not use_control_variate:
        price = float(arith_payoff.mean())
        standard_error = float(arith_payoff.std(ddof=1) / math.sqrt(n_paths))
        return MonteCarloResult(
            price=price, standard_error=standard_error, n_paths=n_paths, control_variate_used=False
        )

    geo_mean = np.exp(np.mean(np.log(fixings), axis=1))
    geo_payoff = discount * _payoff(option.option_type, geo_mean, option.strike)
    geo_twin = AsianOption(
        option.strike, option.maturity, option.option_type, option.n_fixings, "geometric"
    )
    geo_closed_form = geometric_asian_option_price(market, geo_twin)

    covariance_matrix = np.cov(arith_payoff, geo_payoff)
    var_control = covariance_matrix[1, 1]
    beta = covariance_matrix[0, 1] / var_control if var_control > 0 else 0.0
    estimator = arith_payoff - beta * (geo_payoff - geo_closed_form)

    price = float(estimator.mean())
    standard_error = float(estimator.std(ddof=1) / math.sqrt(n_paths))
    return MonteCarloResult(
        price=price, standard_error=standard_error, n_paths=n_paths, control_variate_used=True
    )
