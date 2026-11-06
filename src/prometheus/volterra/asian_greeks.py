"""Finite-difference Greeks for geometric-average Asian options (PRI-07/
FP-12 extension: VOLTERRA Greeks previously existed only for Black-
Scholes and American options).

Deliberately restricted to `average_type="geometric"`: that variant has
an exact closed form (`geometric_asian_option_price`), smooth in every
input, safe for ordinary central finite differences -- the same
confidence `greeks_fd.py` has in Black-Scholes. The arithmetic-average
variant is priced only by Monte Carlo (`monte_carlo_price_asian`), whose
sampling noise would swamp a naive bump-and-reprice difference (the
SAME failure mode `barrier_greeks.py`'s gamma ran into with quadrature
noise, but worse: Monte Carlo standard error does not even shrink
automatically between a price and its bump unless paths are explicitly
shared via common random numbers, which `monte_carlo_price_asian` does
not do). Rather than report a Greek with unknown and likely unreliable
precision, this module raises on an arithmetic option -- consistent with
this project's existing "fail closed rather than report false precision"
convention (e.g. `PDE-11`'s acceptance text in the blueprint).

Verified, before being trusted: with `n_fixings=1` (a single fixing
exactly at maturity), a geometric-average Asian option is not merely
close to a vanilla European option -- it IS one exactly, for any
volatility, since the "average" of one observation is that observation
itself. Finite-difference Greeks at `n_fixings=1` therefore match Black-
Scholes' independently-computed analytical Greeks to high precision,
confirmed in testing -- a stronger, non-degenerate-limit check than the
Heston/Merton/barrier modules get, because this identity holds exactly
rather than only as volatility or a parameter goes to zero.
"""

from __future__ import annotations

from dataclasses import replace

from prometheus.volterra.asian_options import AsianOption, geometric_asian_option_price
from prometheus.volterra.black_scholes import Greeks
from prometheus.volterra.market import MarketSnapshot


def geometric_asian_finite_difference_greeks(
    market: MarketSnapshot,
    option: AsianOption,
    spot_bump: float = 1e-3,
    vol_bump: float = 1e-5,
    time_bump: float = 1e-5,
    rate_bump: float = 1e-6,
) -> Greeks:
    if option.average_type != "geometric":
        raise ValueError(
            "finite-difference Greeks are only implemented for average_type='geometric' "
            "-- the arithmetic variant is priced by Monte Carlo, whose sampling noise is "
            "not safe to bump-and-reprice without common random numbers (not implemented)"
        )

    price_mid = geometric_asian_option_price(market, option)

    price_up_s = geometric_asian_option_price(replace(market, spot=market.spot + spot_bump), option)
    price_down_s = geometric_asian_option_price(
        replace(market, spot=market.spot - spot_bump), option
    )
    delta = (price_up_s - price_down_s) / (2 * spot_bump)
    gamma = (price_up_s - 2 * price_mid + price_down_s) / (spot_bump**2)

    price_up_vol = geometric_asian_option_price(
        replace(market, volatility=market.volatility + vol_bump), option
    )
    price_down_vol = geometric_asian_option_price(
        replace(market, volatility=market.volatility - vol_bump), option
    )
    vega = (price_up_vol - price_down_vol) / (2 * vol_bump)

    option_up_t = replace(option, maturity=option.maturity + time_bump)
    option_down_t = replace(option, maturity=option.maturity - time_bump)
    price_up_t = geometric_asian_option_price(market, option_up_t)
    price_down_t = geometric_asian_option_price(market, option_down_t)
    theta = -(price_up_t - price_down_t) / (2 * time_bump)

    price_up_r = geometric_asian_option_price(
        replace(market, risk_free_rate=market.risk_free_rate + rate_bump), option
    )
    price_down_r = geometric_asian_option_price(
        replace(market, risk_free_rate=market.risk_free_rate - rate_bump), option
    )
    rho = (price_up_r - price_down_r) / (2 * rate_bump)

    return Greeks(delta=delta, gamma=gamma, vega=vega, theta=theta, rho=rho)
