"""Finite-difference Greeks for the Heston characteristic-function pricer
(PRI-07/FP-12 extension: VOLTERRA Greeks previously existed only for
Black-Scholes and American options).

Delta, gamma, theta and rho are ordinary central finite differences on
`heston_option_price` (smooth in spot/maturity/rate, same bump-and-
reprice pattern as `greeks_fd.py`'s Black-Scholes Greeks).

Vega is DIFFERENT in kind, not just in formula, from Black-Scholes vega,
and this difference is real, not a simplification this module glosses
over:

  - Heston has no single "volatility" input. Its vega here is
    `d(price)/d(v0)` -- sensitivity to the CURRENT variance level, the
    closest Heston analog of Black-Scholes' sigma. `v0` is a VARIANCE,
    not a volatility, so this is price change per 1.00 unit of v0, not
    per 1.00 unit of an implied vol.

  - Even accounting for that units difference via the chain rule
    (sigma = sqrt(v0), so d(price)/d(sigma) = d(price)/d(v0) * 2*sigma),
    Heston's vega(v0) does NOT generally equal Black-Scholes vega(sigma)
    at v0 = sigma^2, UNLESS kappa (the mean-reversion speed) is also
    driven to zero. This was confirmed empirically, not assumed, before
    writing this module: at kappa=1.5 (a realistic mean-reversion speed)
    and T=1 year, vega(v0)*2*sigma came out roughly HALF of the matching
    Black-Scholes vega; only after separately testing with kappa -> 0
    (removing mean reversion) did the two match to high precision. The
    reason is economically real, not a bug: with kappa > 0, the variance
    process reverts from v0 toward theta over the option's life, so a
    bump to v0 ALONE has a smaller effect on the path-averaged variance
    (and hence the option price) than an equivalent bump to a constant
    Black-Scholes sigma held fixed for the whole horizon would. Heston's
    vega(v0) is therefore a genuinely different (and, with mean
    reversion, strictly smaller-magnitude after the chain-rule
    adjustment) sensitivity than Black-Scholes vega, not merely the same
    quantity in different units.

Delta/gamma/theta/rho, by contrast, do not depend on which volatility
parameterization is used (S0, maturity and r are common to every
parameterization), so they DO converge directly to Black-Scholes'
analytical Greeks in the xi -> 0 (vol-of-vol -> 0) limit, independent of
kappa -- confirmed in testing.
"""

from __future__ import annotations

from dataclasses import replace

from prometheus.stochastica.heston import HestonParams
from prometheus.volterra.black_scholes import Greeks
from prometheus.volterra.heston_pricer import heston_option_price
from prometheus.volterra.instruments import EuropeanOption
from prometheus.volterra.market import MarketSnapshot


def heston_finite_difference_greeks(
    market: MarketSnapshot,
    option: EuropeanOption,
    params: HestonParams,
    spot_bump: float = 1e-3,
    v0_bump: float = 1e-6,
    time_bump: float = 1e-5,
    rate_bump: float = 1e-6,
) -> Greeks:
    price_mid = heston_option_price(market, option, params)

    price_up_s = heston_option_price(replace(market, spot=market.spot + spot_bump), option, params)
    price_down_s = heston_option_price(
        replace(market, spot=market.spot - spot_bump), option, params
    )
    delta = (price_up_s - price_down_s) / (2 * spot_bump)
    gamma = (price_up_s - 2 * price_mid + price_down_s) / (spot_bump**2)

    price_up_v0 = heston_option_price(market, option, replace(params, v0=params.v0 + v0_bump))
    price_down_v0 = heston_option_price(market, option, replace(params, v0=params.v0 - v0_bump))
    vega_wrt_v0 = (price_up_v0 - price_down_v0) / (2 * v0_bump)

    option_up_t = replace(option, maturity=option.maturity + time_bump)
    option_down_t = replace(option, maturity=option.maturity - time_bump)
    price_up_t = heston_option_price(market, option_up_t, params)
    price_down_t = heston_option_price(market, option_down_t, params)
    theta = -(price_up_t - price_down_t) / (2 * time_bump)

    price_up_r = heston_option_price(
        replace(market, risk_free_rate=market.risk_free_rate + rate_bump), option, params
    )
    price_down_r = heston_option_price(
        replace(market, risk_free_rate=market.risk_free_rate - rate_bump), option, params
    )
    rho = (price_up_r - price_down_r) / (2 * rate_bump)

    return Greeks(delta=delta, gamma=gamma, vega=vega_wrt_v0, theta=theta, rho=rho)
