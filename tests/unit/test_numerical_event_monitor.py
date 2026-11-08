from datetime import date

import numpy as np
import pytest

from prometheus.evidence.numerical_event_monitor import (
    NumericalEvent,
    monitor_call,
    monitor_pricing_deviation,
)
from prometheus.stochastica.gbm import simulate_gbm_paths
from prometheus.volterra.black_scholes import black_scholes_price
from prometheus.volterra.instruments import EuropeanOption
from prometheus.volterra.market import MarketSnapshot
from prometheus.volterra.monte_carlo import monte_carlo_price_vanilla


def test_numerical_event_rejects_an_empty_detail() -> None:
    with pytest.raises(ValueError, match="detail"):
        NumericalEvent(kind="solver_failure", detail="", owner="team")


def test_numerical_event_rejects_an_empty_owner() -> None:
    with pytest.raises(ValueError, match="owner"):
        NumericalEvent(kind="solver_failure", detail="x", owner="")


def test_monitor_call_reports_nothing_for_a_clean_successful_call() -> None:
    assert monitor_call(lambda: 1.0, owner="team") is None


def test_monitor_call_catches_a_raised_exception_as_a_solver_failure() -> None:
    def failing() -> None:
        raise RuntimeError("the solver diverged")

    event = monitor_call(failing, owner="quant-team")
    assert event is not None
    assert event.kind == "solver_failure"
    assert "the solver diverged" in event.detail
    assert event.owner == "quant-team"


def test_monitor_call_detects_a_nan_in_the_result() -> None:
    event = monitor_call(lambda: np.array([1.0, float("nan")]), owner="risk-team")
    assert event is not None
    assert event.kind == "non_finite_result"


def test_monitor_call_detects_an_inf_in_the_result() -> None:
    event = monitor_call(lambda: float("inf"), owner="risk-team")
    assert event is not None
    assert event.kind == "non_finite_result"


def test_monitor_pricing_deviation_rejects_a_non_positive_threshold() -> None:
    with pytest.raises(ValueError, match="max_relative_deviation"):
        monitor_pricing_deviation(1.0, 1.0, max_relative_deviation=0.0, owner="team")


def test_monitor_pricing_deviation_reports_nothing_within_tolerance() -> None:
    event = monitor_pricing_deviation(10.0, 10.05, max_relative_deviation=0.02, owner="team")
    assert event is None


def test_monitor_pricing_deviation_fires_past_tolerance() -> None:
    event = monitor_pricing_deviation(10.0, 20.0, max_relative_deviation=0.02, owner="risk-team")
    assert event is not None
    assert event.kind == "pricing_deviation"
    assert event.owner == "risk-team"


def test_monitor_pricing_deviation_handles_a_zero_reference_price() -> None:
    """A zero reference must not raise ZeroDivisionError -- absolute
    deviation is used as the scale instead."""
    assert monitor_pricing_deviation(0.0001, 0.0, max_relative_deviation=0.5, owner="t") is None
    event = monitor_pricing_deviation(1.0, 0.0, max_relative_deviation=0.5, owner="t")
    assert event is not None


def test_a_real_black_scholes_call_produces_no_event() -> None:
    market = MarketSnapshot(as_of=date(2026, 1, 1), spot=100.0, risk_free_rate=0.03, volatility=0.2)
    option = EuropeanOption(strike=100.0, maturity=1.0, option_type="call")
    event = monitor_call(lambda: black_scholes_price(market, option), owner="risk-team")
    assert event is None


def test_a_real_extreme_drift_gbm_call_produces_a_genuine_solver_failure() -> None:
    """Grounded against this repository's OWN real guard: the same
    extreme positive drift `test_gbm.py` already confirms raises a
    clear `ValueError`, captured here as a real `solver_failure` event
    carrying that real exception's own message."""
    rng = np.random.default_rng(0)

    def extreme_call() -> np.ndarray:
        return simulate_gbm_paths(100.0, 1e300, 0.2, 1.0, n_steps=10, n_paths=10, rng=rng)

    event = monitor_call(extreme_call, owner="quant-team")
    assert event is not None
    assert event.kind == "solver_failure"
    assert "non-finite" in event.detail


def test_a_real_monte_carlo_price_agrees_with_the_real_closed_form_price() -> None:
    """Grounded against two REAL pricers for the SAME market/option:
    `monte_carlo_price_vanilla` with enough paths must agree with
    `black_scholes_price` within a generous tolerance -- no event."""
    market = MarketSnapshot(as_of=date(2026, 1, 1), spot=100.0, risk_free_rate=0.03, volatility=0.2)
    option = EuropeanOption(strike=100.0, maturity=1.0, option_type="call")
    rng = np.random.default_rng(1)
    mc_result = monte_carlo_price_vanilla(market, option, n_paths=50_000, n_steps=50, rng=rng)
    bs_price = black_scholes_price(market, option)

    event = monitor_pricing_deviation(
        mc_result.price, bs_price, max_relative_deviation=0.02, owner="risk-team"
    )
    assert event is None


def test_a_real_monte_carlo_price_against_a_wrong_reference_fires_a_real_deviation_event() -> None:
    """The discriminating half: comparing the SAME real Monte Carlo
    estimate against a deliberately wrong reference price (a different
    option's price) must fire a genuine pricing_deviation event."""
    market = MarketSnapshot(as_of=date(2026, 1, 1), spot=100.0, risk_free_rate=0.03, volatility=0.2)
    option = EuropeanOption(strike=100.0, maturity=1.0, option_type="call")
    rng = np.random.default_rng(1)
    mc_result = monte_carlo_price_vanilla(market, option, n_paths=50_000, n_steps=50, rng=rng)
    bs_price = black_scholes_price(market, option)
    wrong_reference = bs_price * 2

    event = monitor_pricing_deviation(
        mc_result.price, wrong_reference, max_relative_deviation=0.02, owner="risk-team"
    )
    assert event is not None
    assert event.kind == "pricing_deviation"
