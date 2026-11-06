"""American option pricing via a Cox-Ross-Rubinstein binomial tree
(PRI-01 extension): a genuinely different numerical method from
`black_scholes.py`'s closed form, needed because an American option's
early-exercise right has no closed-form Black-Scholes price.

At each node the tree holds that node's own spot `S0 * u^j * d^(i-j)`
(up-moves j out of i steps so far) and compares the discounted
risk-neutral continuation value against immediate exercise, keeping the
larger -- the standard backward-induction American-option algorithm.
`european_binomial_price` runs the IDENTICAL tree without ever comparing
against immediate exercise, which is what makes the two convergence
cross-checks below meaningful: they are the same code path differing only
in that one comparison, not two independently-written pricers that might
happen to agree by coincidence.

Two classic, independently-known theorems are used as correctness
cross-checks, not just plausibility checks:
  - `european_binomial_price` converges to `black_scholes_price` as
    `n_steps` grows (the tree IS a discretization of the same
    risk-neutral dynamics Black-Scholes prices in closed form).
  - An American call on a non-dividend-paying asset is NEVER worth more
    than the otherwise-identical European call (Merton's classical
    result: early exercise of a call is never optimal without
    dividends) -- the two must match to within tree-discretization
    error, not merely satisfy an inequality.

`crr_parameters` and `binomial_tree_values` are exposed (not kept
private) because `volterra.american_greeks` needs the SAME backward
induction, stopped two steps early, to extract delta/gamma directly from
one tree's own nodes -- see that module's docstring for why spot-bumping
and rebuilding the tree (the naive approach) does not work for gamma.
"""

from __future__ import annotations

import math

from prometheus.volterra.instruments import AmericanOption, EuropeanOption
from prometheus.volterra.market import MarketSnapshot

OptionLike = EuropeanOption | AmericanOption


def crr_parameters(
    market: MarketSnapshot, maturity: float, n_steps: int
) -> tuple[float, float, float, float]:
    if n_steps < 1:
        raise ValueError("n_steps must be a positive integer")
    dt = maturity / n_steps
    u = math.exp(market.volatility * math.sqrt(dt))
    d = 1.0 / u
    growth = math.exp((market.risk_free_rate - market.dividend_yield) * dt)
    p = (growth - d) / (u - d)
    if not 0.0 < p < 1.0:
        raise ValueError(
            f"risk-neutral up-probability {p} is outside (0, 1); n_steps={n_steps} is too "
            "coarse relative to volatility/rate/dt for a well-posed CRR tree"
        )
    return u, d, p, dt


def binomial_tree_values(
    market: MarketSnapshot,
    option: OptionLike,
    n_steps: int,
    *,
    early_exercise: bool,
    stop_at_step: int = 0,
) -> list[float]:
    """Backward-induct from the terminal payoffs down to (and including)
    `stop_at_step`, returning that step's full list of node values (length
    `stop_at_step + 1`) rather than collapsing all the way to a single
    price -- the building block both pricing and Greeks extraction share.
    """
    if not 0 <= stop_at_step < n_steps:
        raise ValueError("stop_at_step must be in [0, n_steps)")
    s0, k = market.spot, option.strike
    u, d, p, dt = crr_parameters(market, option.maturity, n_steps)
    discount = math.exp(-market.risk_free_rate * dt)

    def payoff(spot: float) -> float:
        return max(spot - k, 0.0) if option.option_type == "call" else max(k - spot, 0.0)

    values = [payoff(s0 * (u**j) * (d ** (n_steps - j))) for j in range(n_steps + 1)]

    for i in range(n_steps - 1, stop_at_step - 1, -1):
        next_values = []
        for j in range(i + 1):
            continuation = discount * (p * values[j + 1] + (1.0 - p) * values[j])
            if early_exercise:
                spot_ij = s0 * (u**j) * (d ** (i - j))
                continuation = max(continuation, payoff(spot_ij))
            next_values.append(continuation)
        values = next_values

    return values


def european_binomial_price(market: MarketSnapshot, option: EuropeanOption, n_steps: int) -> float:
    return binomial_tree_values(market, option, n_steps, early_exercise=False)[0]


def american_binomial_price(market: MarketSnapshot, option: AmericanOption, n_steps: int) -> float:
    return binomial_tree_values(market, option, n_steps, early_exercise=True)[0]
