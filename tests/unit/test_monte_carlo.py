from datetime import date

import numpy as np
import pytest

from prometheus.volterra.black_scholes import black_scholes_price
from prometheus.volterra.instruments import EuropeanOption
from prometheus.volterra.market import MarketSnapshot
from prometheus.volterra.monte_carlo import monte_carlo_price_vanilla


def _standard_market() -> MarketSnapshot:
    return MarketSnapshot(as_of=date(2026, 1, 1), spot=100.0, risk_free_rate=0.05, volatility=0.2)


def test_mc_price_converges_to_black_scholes_within_a_few_standard_errors() -> None:
    market = _standard_market()
    option = EuropeanOption(strike=100.0, maturity=1.0, option_type="call")
    bs_price = black_scholes_price(market, option)

    rng = np.random.default_rng(1)
    result = monte_carlo_price_vanilla(market, option, n_paths=50_000, n_steps=50, rng=rng)

    assert abs(result.price - bs_price) < 5 * result.standard_error


def test_mc_result_always_reports_a_standard_error_and_path_count() -> None:
    """PRI-13: no price without an uncertainty estimate."""
    market = _standard_market()
    option = EuropeanOption(strike=100.0, maturity=1.0, option_type="put")
    rng = np.random.default_rng(2)
    result = monte_carlo_price_vanilla(market, option, n_paths=1_000, n_steps=20, rng=rng)
    assert result.standard_error > 0.0
    assert result.n_paths == 1_000


def test_control_variate_meaningfully_reduces_standard_error() -> None:
    market = _standard_market()
    option = EuropeanOption(strike=100.0, maturity=1.0, option_type="call")

    rng_cv = np.random.default_rng(1)
    with_cv = monte_carlo_price_vanilla(
        market, option, n_paths=50_000, n_steps=50, rng=rng_cv, use_control_variate=True
    )
    rng_plain = np.random.default_rng(1)
    without_cv = monte_carlo_price_vanilla(
        market, option, n_paths=50_000, n_steps=50, rng=rng_plain, use_control_variate=False
    )

    assert with_cv.standard_error < without_cv.standard_error / 1.5


def test_standard_error_shrinks_roughly_as_inverse_sqrt_n() -> None:
    market = _standard_market()
    option = EuropeanOption(strike=100.0, maturity=1.0, option_type="call")

    rng_small = np.random.default_rng(5)
    small = monte_carlo_price_vanilla(
        market, option, n_paths=2_000, n_steps=20, rng=rng_small, use_control_variate=False
    )
    rng_large = np.random.default_rng(5)
    large = monte_carlo_price_vanilla(
        market, option, n_paths=200_000, n_steps=20, rng=rng_large, use_control_variate=False
    )

    # SE scales as 1/sqrt(N); a 100x path-count increase should roughly
    # halve-to-a-tenth it depending on realized sample variance, so this
    # checks the right order of magnitude (expected ratio ~10x) loosely.
    ratio = small.standard_error / large.standard_error
    assert 5.0 < ratio < 20.0


def test_rejects_market_with_wrong_measure_label_upstream() -> None:
    """VOLTERRA's MarketSnapshot constructor itself enforces this (SDE-09);
    re-asserted here at the Monte Carlo entry point's doorstep."""
    with pytest.raises(ValueError):
        MarketSnapshot(
            as_of=date(2026, 1, 1), spot=100.0, risk_free_rate=0.05, volatility=0.2, measure="P"
        )
