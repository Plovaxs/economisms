"""Finite-difference Greeks for single-barrier options (PRI-07/FP-12
extension: VOLTERRA Greeks previously existed only for Black-Scholes and
American options).

Ordinary central finite differences on `barrier_option_price`, with a
deliberately LARGER default `spot_bump` than `greeks_fd.py`'s Black-
Scholes default (1e-3). Originally this was attributed to
`barrier_option_price` being a numerical quadrature with a noise floor
that gamma's division by `spot_bump**2` amplifies -- confirmed, at the
time, by a 7.8% gamma error at `spot_bump=1e-3` versus 4-significant-
figure agreement at `spot_bump=0.05`.

SDE-12 stress testing later found the REAL root cause to be different and
deeper: `barrier_option_price`'s integration never told `scipy.integrate.
quad` about the payoff's kink at `x = ln(strike/s0)`, so its adaptive
subdivision could silently converge to a value with far more error than
its own reported error estimate suggested. Once that pricer-level bug was
fixed (passing `points=[kink]` to `quad`), gamma became accurate at BOTH
bump sizes -- confirmed directly, re-verified in this module's own test
suite. The larger default bump is kept anyway, now simply as a
conservative choice (a small, acceptable extra cost in central-difference
truncation error, negligible for a smooth function at a 0.05-on-100
relative bump) rather than a load-bearing fix for the original bug, which
no longer exists.
"""

from __future__ import annotations

from dataclasses import replace

from prometheus.volterra.barrier_options import BarrierOption, barrier_option_price
from prometheus.volterra.black_scholes import Greeks
from prometheus.volterra.market import MarketSnapshot


def barrier_finite_difference_greeks(
    market: MarketSnapshot,
    option: BarrierOption,
    spot_bump: float = 0.05,
    vol_bump: float = 1e-5,
    time_bump: float = 1e-5,
    rate_bump: float = 1e-6,
) -> Greeks:
    price_mid = barrier_option_price(market, option)

    price_up_s = barrier_option_price(replace(market, spot=market.spot + spot_bump), option)
    price_down_s = barrier_option_price(replace(market, spot=market.spot - spot_bump), option)
    delta = (price_up_s - price_down_s) / (2 * spot_bump)
    gamma = (price_up_s - 2 * price_mid + price_down_s) / (spot_bump**2)

    price_up_vol = barrier_option_price(
        replace(market, volatility=market.volatility + vol_bump), option
    )
    price_down_vol = barrier_option_price(
        replace(market, volatility=market.volatility - vol_bump), option
    )
    vega = (price_up_vol - price_down_vol) / (2 * vol_bump)

    option_up_t = replace(option, maturity=option.maturity + time_bump)
    option_down_t = replace(option, maturity=option.maturity - time_bump)
    price_up_t = barrier_option_price(market, option_up_t)
    price_down_t = barrier_option_price(market, option_down_t)
    theta = -(price_up_t - price_down_t) / (2 * time_bump)

    price_up_r = barrier_option_price(
        replace(market, risk_free_rate=market.risk_free_rate + rate_bump), option
    )
    price_down_r = barrier_option_price(
        replace(market, risk_free_rate=market.risk_free_rate - rate_bump), option
    )
    rho = (price_up_r - price_down_r) / (2 * rate_bump)

    return Greeks(delta=delta, gamma=gamma, vega=vega, theta=theta, rho=rho)
