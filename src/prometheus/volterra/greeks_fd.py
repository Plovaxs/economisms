"""Finite-difference Greeks: an independent cross-check of the analytical
Black-Scholes Greeks (VAL-05: Greeks computed one way should match Greeks
computed another way within a tolerance budget). This differentiates
black_scholes_price itself via central differences, so it validates the
Greeks formulas specifically against the same price function the rest of
the system relies on -- it is not a from-scratch independent pricer.
"""

from __future__ import annotations

from dataclasses import replace

from prometheus.volterra.black_scholes import Greeks, black_scholes_price
from prometheus.volterra.instruments import EuropeanOption
from prometheus.volterra.market import MarketSnapshot


def finite_difference_greeks(
    market: MarketSnapshot,
    option: EuropeanOption,
    spot_bump: float = 1e-3,
    vol_bump: float = 1e-5,
    time_bump: float = 1e-5,
    rate_bump: float = 1e-6,
) -> Greeks:
    price_mid = black_scholes_price(market, option)

    price_up_s = black_scholes_price(replace(market, spot=market.spot + spot_bump), option)
    price_down_s = black_scholes_price(replace(market, spot=market.spot - spot_bump), option)
    delta = (price_up_s - price_down_s) / (2 * spot_bump)
    gamma = (price_up_s - 2 * price_mid + price_down_s) / (spot_bump**2)

    price_up_vol = black_scholes_price(
        replace(market, volatility=market.volatility + vol_bump), option
    )
    price_down_vol = black_scholes_price(
        replace(market, volatility=market.volatility - vol_bump), option
    )
    vega = (price_up_vol - price_down_vol) / (2 * vol_bump)

    price_up_t = black_scholes_price(market, replace(option, maturity=option.maturity + time_bump))
    price_down_t = black_scholes_price(
        market, replace(option, maturity=option.maturity - time_bump)
    )
    # theta is the calendar-time derivative, i.e. -d(price)/d(time-to-maturity)
    theta = -(price_up_t - price_down_t) / (2 * time_bump)

    price_up_r = black_scholes_price(
        replace(market, risk_free_rate=market.risk_free_rate + rate_bump), option
    )
    price_down_r = black_scholes_price(
        replace(market, risk_free_rate=market.risk_free_rate - rate_bump), option
    )
    rho = (price_up_r - price_down_r) / (2 * rate_bump)

    return Greeks(delta=delta, gamma=gamma, vega=vega, theta=theta, rho=rho)
