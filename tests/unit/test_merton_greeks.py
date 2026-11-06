from datetime import date

import pytest

from prometheus.stochastica.jump_diffusion import MertonJumpParams
from prometheus.volterra.black_scholes import black_scholes_greeks
from prometheus.volterra.instruments import EuropeanOption
from prometheus.volterra.market import MarketSnapshot
from prometheus.volterra.merton_greeks import merton_finite_difference_greeks


def _market(**overrides: float) -> MarketSnapshot:
    defaults: dict = dict(as_of=date(2026, 1, 1), spot=100.0, risk_free_rate=0.03, volatility=0.2)
    defaults.update(overrides)
    return MarketSnapshot(**defaults)


def _params(**overrides: float) -> MertonJumpParams:
    defaults: dict = dict(mu=0.03, sigma=0.2, jump_intensity=0.75, jump_mean=-0.1, jump_std=0.25)
    defaults.update(overrides)
    return MertonJumpParams(**defaults)


def test_merton_greeks_converge_to_black_scholes_in_zero_jump_limit() -> None:
    """In the zero-jump-intensity limit, Merton IS Black-Scholes, so ALL
    FIVE Greeks (not just the price) must converge to Black-Scholes'
    independently-computed analytical Greeks -- vega needs no chain-rule
    adjustment here, unlike Heston's v0, because sigma is literally the
    same parameter in both models."""
    market = _market(spot=100.0, risk_free_rate=0.03, volatility=0.2)
    option = EuropeanOption(strike=100.0, maturity=1.0, option_type="call")
    params = _params(sigma=0.2, jump_intensity=1e-9, jump_mean=0.0, jump_std=1e-6)

    merton_g = merton_finite_difference_greeks(market, option, params)
    bs_g = black_scholes_greeks(market, option)

    assert merton_g.delta == pytest.approx(bs_g.delta, abs=1e-4)
    assert merton_g.gamma == pytest.approx(bs_g.gamma, abs=1e-4)
    assert merton_g.vega == pytest.approx(bs_g.vega, abs=1e-3)
    assert merton_g.theta == pytest.approx(bs_g.theta, abs=1e-3)
    assert merton_g.rho == pytest.approx(bs_g.rho, abs=1e-3)


def test_merton_greeks_put_also_converges_to_black_scholes_with_dividends() -> None:
    market = _market(spot=90.0, risk_free_rate=0.02, dividend_yield=0.015, volatility=0.25)
    option = EuropeanOption(strike=100.0, maturity=0.5, option_type="put")
    params = _params(sigma=0.25, jump_intensity=1e-9, jump_mean=0.0, jump_std=1e-6)

    merton_g = merton_finite_difference_greeks(market, option, params)
    bs_g = black_scholes_greeks(market, option)

    assert merton_g.delta == pytest.approx(bs_g.delta, abs=1e-4)
    assert merton_g.gamma == pytest.approx(bs_g.gamma, abs=1e-4)
    assert merton_g.vega == pytest.approx(bs_g.vega, abs=1e-3)


def test_merton_greeks_market_volatility_field_is_ignored() -> None:
    option = EuropeanOption(strike=100.0, maturity=1.0, option_type="call")
    params = _params()
    g_a = merton_finite_difference_greeks(_market(volatility=0.1), option, params)
    g_b = merton_finite_difference_greeks(_market(volatility=0.9), option, params)
    assert g_a == g_b


def test_merton_greeks_are_stable_across_bump_sizes() -> None:
    """A generic, limit-independent self-consistency check: halving every
    bump size should change each Greek only slightly (central-difference
    truncation error shrinking), not produce a wildly different value."""
    market = _market()
    option = EuropeanOption(strike=100.0, maturity=1.0, option_type="call")
    params = _params()

    coarse = merton_finite_difference_greeks(
        market, option, params, spot_bump=2e-3, sigma_bump=2e-5, time_bump=2e-5, rate_bump=2e-6
    )
    fine = merton_finite_difference_greeks(
        market, option, params, spot_bump=1e-3, sigma_bump=1e-5, time_bump=1e-5, rate_bump=1e-6
    )
    assert coarse.delta == pytest.approx(fine.delta, abs=1e-5)
    assert coarse.gamma == pytest.approx(fine.gamma, abs=1e-3)
    assert coarse.vega == pytest.approx(fine.vega, abs=1e-2)
    assert coarse.theta == pytest.approx(fine.theta, abs=1e-2)
    assert coarse.rho == pytest.approx(fine.rho, abs=1e-2)
