"""Finite-difference Greeks for the Merton jump-diffusion pricer (PRI-07/
FP-12 extension: VOLTERRA Greeks previously existed only for Black-Scholes
and American options -- see `greeks_fd.py`/`american_greeks.py`).

Ordinary central finite differences on `merton_option_price` itself, the
same bump-and-reprice pattern `greeks_fd.py` already uses for Black-
Scholes -- `merton_call_price`'s closed form is smooth in every input
(an infinite but rapidly-converging sum of smooth Black-Scholes terms),
so there is no piecewise-linear pathology here the way there is for the
binomial-tree American Greeks (see `american_greeks.py`'s docstring for
why that case needs a different technique).

Vega is `d(price)/d(sigma)` -- `params.sigma`, the diffusive volatility,
the SAME parameterization Black-Scholes' own vega uses (unlike Heston's
`v0`, a variance; see `heston_greeks.py`). Confirmed, not assumed: as
`jump_intensity -> 0`, Merton's finite-difference delta/gamma/vega/theta/
rho all converge to Black-Scholes' own ANALYTICAL Greeks (computed
independently, not derived from this module) to high precision, since in
that limit the model literally IS Black-Scholes.
"""

from __future__ import annotations

from dataclasses import replace

from prometheus.stochastica.jump_diffusion import MertonJumpParams
from prometheus.volterra.black_scholes import Greeks
from prometheus.volterra.instruments import EuropeanOption
from prometheus.volterra.market import MarketSnapshot
from prometheus.volterra.merton_pricer import merton_option_price


def merton_finite_difference_greeks(
    market: MarketSnapshot,
    option: EuropeanOption,
    params: MertonJumpParams,
    spot_bump: float = 1e-3,
    sigma_bump: float = 1e-5,
    time_bump: float = 1e-5,
    rate_bump: float = 1e-6,
) -> Greeks:
    price_mid = merton_option_price(market, option, params)

    price_up_s = merton_option_price(replace(market, spot=market.spot + spot_bump), option, params)
    price_down_s = merton_option_price(
        replace(market, spot=market.spot - spot_bump), option, params
    )
    delta = (price_up_s - price_down_s) / (2 * spot_bump)
    gamma = (price_up_s - 2 * price_mid + price_down_s) / (spot_bump**2)

    price_up_sigma = merton_option_price(
        market, option, replace(params, sigma=params.sigma + sigma_bump)
    )
    price_down_sigma = merton_option_price(
        market, option, replace(params, sigma=params.sigma - sigma_bump)
    )
    vega = (price_up_sigma - price_down_sigma) / (2 * sigma_bump)

    option_up_t = replace(option, maturity=option.maturity + time_bump)
    option_down_t = replace(option, maturity=option.maturity - time_bump)
    price_up_t = merton_option_price(market, option_up_t, params)
    price_down_t = merton_option_price(market, option_down_t, params)
    theta = -(price_up_t - price_down_t) / (2 * time_bump)

    price_up_r = merton_option_price(
        replace(market, risk_free_rate=market.risk_free_rate + rate_bump), option, params
    )
    price_down_r = merton_option_price(
        replace(market, risk_free_rate=market.risk_free_rate - rate_bump), option, params
    )
    rho = (price_up_r - price_down_r) / (2 * rate_bump)

    return Greeks(delta=delta, gamma=gamma, vega=vega, theta=theta, rho=rho)
