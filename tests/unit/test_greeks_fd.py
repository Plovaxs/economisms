from datetime import date

import pytest

from prometheus.volterra.black_scholes import black_scholes_greeks
from prometheus.volterra.greeks_fd import finite_difference_greeks
from prometheus.volterra.instruments import EuropeanOption
from prometheus.volterra.market import MarketSnapshot


@pytest.mark.parametrize("option_type", ["call", "put"])
@pytest.mark.parametrize("moneyness", [80.0, 100.0, 120.0])
def test_finite_difference_matches_analytical_greeks(option_type: str, moneyness: float) -> None:
    """VAL-05: an independently computed (central finite-difference) Greek
    must match the analytical one within a tight tolerance -- across ITM,
    ATM and OTM strikes for both calls and puts, including near a kink
    (deep ITM/OTM) where discretization error could plausibly hide a bug."""
    market = MarketSnapshot(
        as_of=date(2026, 1, 1), spot=100.0, risk_free_rate=0.05, volatility=0.2, dividend_yield=0.01
    )
    option = EuropeanOption(strike=moneyness, maturity=1.0, option_type=option_type)  # type: ignore[arg-type]

    analytical = black_scholes_greeks(market, option)
    fd = finite_difference_greeks(market, option)

    assert fd.delta == pytest.approx(analytical.delta, abs=1e-6)
    assert fd.gamma == pytest.approx(analytical.gamma, abs=1e-4)
    assert fd.vega == pytest.approx(analytical.vega, abs=1e-4)
    assert fd.theta == pytest.approx(analytical.theta, abs=1e-4)
    assert fd.rho == pytest.approx(analytical.rho, abs=1e-4)
