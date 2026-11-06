from datetime import date

import pytest

from prometheus.volterra.barrier_greeks import barrier_finite_difference_greeks
from prometheus.volterra.barrier_options import BarrierOption
from prometheus.volterra.black_scholes import black_scholes_greeks
from prometheus.volterra.instruments import EuropeanOption
from prometheus.volterra.market import MarketSnapshot


def _market(**overrides: float) -> MarketSnapshot:
    defaults: dict = dict(as_of=date(2026, 1, 1), spot=100.0, risk_free_rate=0.03, volatility=0.2)
    defaults.update(overrides)
    return MarketSnapshot(**defaults)


def test_down_and_out_call_greeks_converge_to_black_scholes_as_barrier_vanishes() -> None:
    market = _market(spot=100.0, risk_free_rate=0.03, volatility=0.2)
    option = BarrierOption(100.0, 1.0, "call", barrier=1e-7, direction="down", knock="out")
    bs_g = black_scholes_greeks(market, EuropeanOption(100.0, 1.0, "call"))

    barrier_g = barrier_finite_difference_greeks(market, option)
    assert barrier_g.delta == pytest.approx(bs_g.delta, abs=1e-4)
    assert barrier_g.gamma == pytest.approx(bs_g.gamma, abs=1e-4)
    assert barrier_g.vega == pytest.approx(bs_g.vega, abs=1e-3)
    assert barrier_g.theta == pytest.approx(bs_g.theta, abs=1e-3)
    assert barrier_g.rho == pytest.approx(bs_g.rho, abs=1e-3)


def test_up_and_out_put_greeks_converge_to_black_scholes_as_barrier_recedes() -> None:
    market = _market(spot=100.0, risk_free_rate=0.02, volatility=0.3)
    option = BarrierOption(100.0, 0.75, "put", barrier=1e7, direction="up", knock="out")
    bs_g = black_scholes_greeks(market, EuropeanOption(100.0, 0.75, "put"))

    barrier_g = barrier_finite_difference_greeks(market, option)
    assert barrier_g.delta == pytest.approx(bs_g.delta, abs=1e-4)
    assert barrier_g.gamma == pytest.approx(bs_g.gamma, abs=1e-4)


def test_gamma_is_accurate_at_both_the_default_and_a_smaller_bump() -> None:
    """Historical note, corrected by SDE-12 stress testing (see
    `barrier_options.py`'s own docstring): a Black-Scholes-sized bump of
    1e-3 USED TO give a materially wrong gamma here, blamed at the time on
    quadrature noise amplified by dividing by spot_bump^2, which is why
    this module's default bump was set larger (0.05). The REAL root cause
    turned out to be different and deeper: `scipy.integrate.quad` was
    never told about the payoff's kink at `x = ln(strike/s0)`, so its
    adaptive subdivision could silently converge to a value with far more
    error than its own reported error estimate suggested -- confirmed
    directly against an independent fine-grid Simpson's-rule ground
    truth. Passing `points=[kink]` to `quad` fixed the quadrature's
    accuracy at its root, which incidentally also fixed gamma at the
    smaller bump: both bump sizes are now accurate, confirmed here so a
    future change does not reintroduce either failure mode."""
    market = _market(spot=100.0, risk_free_rate=0.03, volatility=0.2)
    option = BarrierOption(100.0, 1.0, "call", barrier=1e-7, direction="down", knock="out")
    bs_gamma = black_scholes_greeks(market, EuropeanOption(100.0, 1.0, "call")).gamma

    small_bump = barrier_finite_difference_greeks(market, option, spot_bump=1e-3)
    assert small_bump.gamma == pytest.approx(bs_gamma, abs=1e-4)

    default_bump = barrier_finite_difference_greeks(market, option)
    assert default_bump.gamma == pytest.approx(bs_gamma, abs=1e-4)


def test_barrier_greeks_are_stable_across_bump_sizes() -> None:
    market = _market()
    option = BarrierOption(100.0, 1.0, "call", barrier=85.0, direction="down", knock="out")

    coarse = barrier_finite_difference_greeks(
        market, option, spot_bump=0.1, vol_bump=2e-5, time_bump=2e-5, rate_bump=2e-6
    )
    fine = barrier_finite_difference_greeks(
        market, option, spot_bump=0.05, vol_bump=1e-5, time_bump=1e-5, rate_bump=1e-6
    )
    assert coarse.delta == pytest.approx(fine.delta, abs=1e-3)
    assert coarse.gamma == pytest.approx(fine.gamma, abs=1e-3)
    assert coarse.vega == pytest.approx(fine.vega, abs=1e-2)
    assert coarse.theta == pytest.approx(fine.theta, abs=1e-2)
    assert coarse.rho == pytest.approx(fine.rho, abs=1e-2)
