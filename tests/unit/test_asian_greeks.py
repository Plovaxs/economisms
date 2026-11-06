from datetime import date

import pytest

from prometheus.volterra.asian_greeks import geometric_asian_finite_difference_greeks
from prometheus.volterra.asian_options import AsianOption
from prometheus.volterra.black_scholes import black_scholes_greeks
from prometheus.volterra.instruments import EuropeanOption
from prometheus.volterra.market import MarketSnapshot


def _market(**overrides: float) -> MarketSnapshot:
    defaults: dict = dict(as_of=date(2026, 1, 1), spot=100.0, risk_free_rate=0.03, volatility=0.2)
    defaults.update(overrides)
    return MarketSnapshot(**defaults)


def test_rejects_arithmetic_average_option() -> None:
    market = _market()
    option = AsianOption(100.0, 1.0, "call", n_fixings=12, average_type="arithmetic")
    with pytest.raises(ValueError, match="geometric"):
        geometric_asian_finite_difference_greeks(market, option)


def test_single_fixing_at_maturity_greeks_exactly_match_black_scholes() -> None:
    """n_fixings=1 makes the geometric average IDENTICAL to the terminal
    spot for any volatility -- an exact identity, not a limit -- so every
    Greek must match Black-Scholes' independently-computed analytical
    Greeks closely, not just approximately in some edge case."""
    market = _market(spot=100.0, risk_free_rate=0.03, volatility=0.2)
    option = AsianOption(100.0, 1.0, "call", n_fixings=1, average_type="geometric")
    bs_g = black_scholes_greeks(market, EuropeanOption(100.0, 1.0, "call"))

    asian_g = geometric_asian_finite_difference_greeks(market, option)
    assert asian_g.delta == pytest.approx(bs_g.delta, abs=1e-4)
    assert asian_g.gamma == pytest.approx(bs_g.gamma, abs=1e-4)
    assert asian_g.vega == pytest.approx(bs_g.vega, abs=1e-3)
    assert asian_g.theta == pytest.approx(bs_g.theta, abs=1e-3)
    assert asian_g.rho == pytest.approx(bs_g.rho, abs=1e-3)


def test_single_fixing_put_with_dividends_also_matches() -> None:
    market = _market(spot=90.0, risk_free_rate=0.02, dividend_yield=0.015, volatility=0.25)
    option = AsianOption(100.0, 0.5, "put", n_fixings=1, average_type="geometric")
    bs_g = black_scholes_greeks(market, EuropeanOption(100.0, 0.5, "put"))

    asian_g = geometric_asian_finite_difference_greeks(market, option)
    assert asian_g.delta == pytest.approx(bs_g.delta, abs=1e-4)
    assert asian_g.vega == pytest.approx(bs_g.vega, abs=1e-3)


def test_delta_decreases_in_magnitude_as_fixings_increase() -> None:
    """A model-free sanity check: averaging over more fixing dates
    dampens the option's sensitivity to the spot at any single moment
    (the average is less reactive than the terminal spot alone), so
    |delta| should shrink as n_fixings grows for an otherwise identical
    contract -- not asserted from a formula, checked directly."""
    market = _market(spot=100.0, risk_free_rate=0.03, volatility=0.3)
    few = geometric_asian_finite_difference_greeks(
        market, AsianOption(100.0, 1.0, "call", n_fixings=2, average_type="geometric")
    )
    many = geometric_asian_finite_difference_greeks(
        market, AsianOption(100.0, 1.0, "call", n_fixings=50, average_type="geometric")
    )
    assert many.delta < few.delta


def test_asian_greeks_are_stable_across_bump_sizes() -> None:
    market = _market()
    option = AsianOption(100.0, 1.0, "call", n_fixings=12, average_type="geometric")

    coarse = geometric_asian_finite_difference_greeks(
        market, option, spot_bump=2e-3, vol_bump=2e-5, time_bump=2e-5, rate_bump=2e-6
    )
    fine = geometric_asian_finite_difference_greeks(
        market, option, spot_bump=1e-3, vol_bump=1e-5, time_bump=1e-5, rate_bump=1e-6
    )
    assert coarse.delta == pytest.approx(fine.delta, abs=1e-5)
    assert coarse.gamma == pytest.approx(fine.gamma, abs=1e-3)
    assert coarse.vega == pytest.approx(fine.vega, abs=1e-2)
    assert coarse.theta == pytest.approx(fine.theta, abs=1e-2)
    assert coarse.rho == pytest.approx(fine.rho, abs=1e-2)
