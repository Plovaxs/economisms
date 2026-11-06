"""Greeks for American options (VAL-05 extension).

Delta and gamma are extracted from a SINGLE binomial tree's own early
nodes (`binomial_tree_values(..., stop_at_step=2)`) -- the standard
Cox-Ross-Rubinstein technique (Hull, *Options, Futures and Other
Derivatives*) -- not by bumping spot and rebuilding the tree. Naive
central differences on spot are a well known pitfall here, confirmed
empirically (not just asserted) before choosing this approach: a CRR
tree's price is a piecewise-linear, not smooth, function of spot (kinks
appear wherever spot crosses a lattice node), so a central-difference
gamma computed from independently-rebuilt trees oscillates and does NOT
converge as either `n_steps` or the spot bump changes -- see this
module's own test demonstrating that non-convergence directly.

With three adjacent nodes at step 2 -- spot S0*d^2, S0 (since u*d = 1 for
CRR), S0*u^2, with values V_dd, V_mid, V_uu -- delta and gamma follow
from the same finite-difference formulas, but applied to ONE shared
tree's own internally-consistent nodes instead of several independently
re-rooted ones:

    delta = (V_uu - V_dd) / (S0*u^2 - S0*d^2)
    gamma = [ (V_uu-V_mid)/(S0*u^2-S0) - (V_mid-V_dd)/(S0-S0*d^2) ]
            / ( 0.5 * (S0*u^2 - S0*d^2) )

This reads the option's sensitivity at time 2*dt rather than exactly
t=0, converging to the true t=0 Greeks as `n_steps` grows and dt shrinks
-- confirmed by convergence to Black-Scholes' analytical Greeks for an
American call with no dividends (PRI-38's equal-price theorem extends to
equal Greeks too, since the two prices are identical functions of spot
in that case).

Vega, theta and rho do not share gamma's pathology -- bumping volatility,
time or rate rebuilds the ENTIRE tree rather than reading two adjacent
spot nodes of the same one -- so they are computed by ordinary central
finite differences, the same bump-and-reprice pattern `greeks_fd.py`
already uses for the closed-form Black-Scholes Greeks.
"""

from __future__ import annotations

from dataclasses import replace

from prometheus.volterra.american_options import (
    american_binomial_price,
    binomial_tree_values,
    crr_parameters,
)
from prometheus.volterra.black_scholes import Greeks
from prometheus.volterra.instruments import AmericanOption
from prometheus.volterra.market import MarketSnapshot


def tree_delta_gamma(
    market: MarketSnapshot, option: AmericanOption, n_steps: int
) -> tuple[float, float]:
    if n_steps < 2:
        raise ValueError("n_steps must be >= 2 to extract delta/gamma from the tree's own nodes")
    values = binomial_tree_values(market, option, n_steps, early_exercise=True, stop_at_step=2)
    v_dd, v_mid, v_uu = values[0], values[1], values[2]

    u, d, _p, _dt = crr_parameters(market, option.maturity, n_steps)
    s0 = market.spot
    s_uu, s_mid, s_dd = s0 * u**2, s0, s0 * d**2

    delta = (v_uu - v_dd) / (s_uu - s_dd)
    gamma = ((v_uu - v_mid) / (s_uu - s_mid) - (v_mid - v_dd) / (s_mid - s_dd)) / (
        0.5 * (s_uu - s_dd)
    )
    return delta, gamma


def american_binomial_greeks(
    market: MarketSnapshot,
    option: AmericanOption,
    n_steps: int,
    vol_bump: float = 1e-3,
    time_bump: float = 1e-3,
    rate_bump: float = 1e-4,
) -> Greeks:
    delta, gamma = tree_delta_gamma(market, option, n_steps)

    price_up_vol = american_binomial_price(
        replace(market, volatility=market.volatility + vol_bump), option, n_steps
    )
    price_down_vol = american_binomial_price(
        replace(market, volatility=market.volatility - vol_bump), option, n_steps
    )
    vega = (price_up_vol - price_down_vol) / (2 * vol_bump)

    option_up_t = replace(option, maturity=option.maturity + time_bump)
    option_down_t = replace(option, maturity=option.maturity - time_bump)
    price_up_t = american_binomial_price(market, option_up_t, n_steps)
    price_down_t = american_binomial_price(market, option_down_t, n_steps)
    # theta is the calendar-time derivative, i.e. -d(price)/d(time-to-maturity)
    theta = -(price_up_t - price_down_t) / (2 * time_bump)

    price_up_r = american_binomial_price(
        replace(market, risk_free_rate=market.risk_free_rate + rate_bump), option, n_steps
    )
    price_down_r = american_binomial_price(
        replace(market, risk_free_rate=market.risk_free_rate - rate_bump), option, n_steps
    )
    rho = (price_up_r - price_down_r) / (2 * rate_bump)

    return Greeks(delta=delta, gamma=gamma, vega=vega, theta=theta, rho=rho)
