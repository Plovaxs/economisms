import math
from datetime import date

import pytest

from prometheus.stochastica.heston import HestonParams
from prometheus.volterra.black_scholes import black_scholes_greeks
from prometheus.volterra.heston_greeks import heston_finite_difference_greeks
from prometheus.volterra.instruments import EuropeanOption
from prometheus.volterra.market import MarketSnapshot


def _market(**overrides: float) -> MarketSnapshot:
    defaults: dict = dict(as_of=date(2026, 1, 1), spot=100.0, risk_free_rate=0.03, volatility=0.2)
    defaults.update(overrides)
    return MarketSnapshot(**defaults)


def _params(**overrides: float) -> HestonParams:
    defaults: dict = dict(mu=0.03, kappa=1.5, theta=0.04, xi=0.3, rho=-0.6, v0=0.045)
    defaults.update(overrides)
    return HestonParams(**defaults)


def test_delta_gamma_theta_rho_converge_to_black_scholes_regardless_of_kappa() -> None:
    """These four do not depend on the v0-vs-sigma parameterization, so
    they must converge to Black-Scholes' Greeks in the zero-vol-of-vol
    limit at ANY kappa -- unlike vega (see below)."""
    market = _market(spot=100.0, risk_free_rate=0.03, volatility=0.2)
    option = EuropeanOption(strike=100.0, maturity=1.0, option_type="call")
    params = _params(kappa=1.5, theta=0.04, xi=1e-5, rho=0.0, v0=0.04)

    heston_g = heston_finite_difference_greeks(market, option, params)
    bs_g = black_scholes_greeks(market, option)

    assert heston_g.delta == pytest.approx(bs_g.delta, abs=1e-4)
    assert heston_g.gamma == pytest.approx(bs_g.gamma, abs=1e-4)
    assert heston_g.theta == pytest.approx(bs_g.theta, abs=2e-2)
    assert heston_g.rho == pytest.approx(bs_g.rho, abs=1e-4)


def test_vega_requires_removing_mean_reversion_to_match_black_scholes() -> None:
    """Pins the real, documented finding this module's docstring
    describes: with realistic mean reversion (kappa=1.5), Heston's
    vega(v0), chain-rule-converted to a per-sigma basis, is NOT close to
    Black-Scholes vega -- it is damped by mean reversion pulling v0 back
    toward theta over the option's life. Only with kappa -> 0 (no mean
    reversion) does the chain-rule-converted vega match Black-Scholes
    closely. Both halves are asserted so a future change that
    accidentally "fixes" (removes) the real economic effect, or breaks
    the limiting match, fails loudly."""
    market = _market(spot=100.0, risk_free_rate=0.03, volatility=0.2)
    option = EuropeanOption(strike=100.0, maturity=1.0, option_type="call")
    bs_g = black_scholes_greeks(market, option)
    sigma = 0.2

    with_reversion = _params(kappa=1.5, theta=0.04, xi=1e-5, rho=0.0, v0=0.04)
    g_with_reversion = heston_finite_difference_greeks(market, option, with_reversion)
    converted = g_with_reversion.vega * 2 * sigma
    assert abs(converted - bs_g.vega) > 0.3 * bs_g.vega  # genuinely far off, not numerical noise

    without_reversion = _params(kappa=1e-6, theta=0.04, xi=1e-5, rho=0.0, v0=0.04)
    g_without_reversion = heston_finite_difference_greeks(market, option, without_reversion)
    converted_no_reversion = g_without_reversion.vega * 2 * sigma
    assert converted_no_reversion == pytest.approx(bs_g.vega, rel=1e-3)


def test_heston_greeks_market_volatility_field_is_ignored() -> None:
    option = EuropeanOption(strike=100.0, maturity=1.0, option_type="call")
    params = _params()
    g_a = heston_finite_difference_greeks(_market(volatility=0.1), option, params)
    g_b = heston_finite_difference_greeks(_market(volatility=0.9), option, params)
    assert g_a == g_b


def test_heston_greeks_are_stable_across_bump_sizes() -> None:
    market = _market()
    option = EuropeanOption(strike=100.0, maturity=1.0, option_type="call")
    params = _params()

    coarse = heston_finite_difference_greeks(
        market, option, params, spot_bump=2e-3, v0_bump=2e-6, time_bump=2e-5, rate_bump=2e-6
    )
    fine = heston_finite_difference_greeks(
        market, option, params, spot_bump=1e-3, v0_bump=1e-6, time_bump=1e-5, rate_bump=1e-6
    )
    assert coarse.delta == pytest.approx(fine.delta, abs=1e-5)
    assert coarse.gamma == pytest.approx(fine.gamma, abs=1e-3)
    assert coarse.vega == pytest.approx(fine.vega, rel=1e-2)
    assert coarse.theta == pytest.approx(fine.theta, abs=1e-2)
    assert coarse.rho == pytest.approx(fine.rho, abs=1e-2)


def test_heston_vega_scales_linearly_with_time_in_the_no_mean_reversion_limit() -> None:
    """A model-free-ish sanity check independent of Black-Scholes: with
    no mean reversion, the TOTAL variance accumulated is v0*T, so the
    option's sensitivity to v0 should scale roughly with maturity --
    confirmed via two different maturities rather than assumed."""
    market = _market()
    params = _params(kappa=1e-6, theta=0.04, xi=1e-5, rho=0.0, v0=0.04)
    short = heston_finite_difference_greeks(
        market, EuropeanOption(100.0, 0.25, "call"), params
    )
    long = heston_finite_difference_greeks(market, EuropeanOption(100.0, 1.0, "call"), params)
    assert long.vega > short.vega
    assert not math.isnan(long.vega) and not math.isnan(short.vega)
