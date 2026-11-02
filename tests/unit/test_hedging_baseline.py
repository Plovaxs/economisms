from datetime import date

import numpy as np
import pytest

from prometheus.hedging.baseline import (
    apply_no_trade_band,
    black_scholes_delta_hedge_ratios,
    black_scholes_delta_vectorized,
)
from prometheus.volterra.black_scholes import black_scholes_greeks
from prometheus.volterra.instruments import EuropeanOption
from prometheus.volterra.market import MarketSnapshot


@pytest.mark.parametrize("option_type", ["call", "put"])
@pytest.mark.parametrize("spot", [80.0, 100.0, 120.0])
def test_vectorized_delta_matches_scalar_black_scholes_delta(
    option_type: str, spot: float
) -> None:
    market = MarketSnapshot(
        as_of=date(2026, 1, 1), spot=spot, risk_free_rate=0.05, volatility=0.2, dividend_yield=0.01
    )
    option = EuropeanOption(strike=100.0, maturity=0.75, option_type=option_type)  # type: ignore[arg-type]
    scalar_delta = black_scholes_greeks(market, option).delta

    vector_delta = black_scholes_delta_vectorized(
        np.array([spot]), 100.0, 0.05, 0.2, np.array([0.75]), option_type, dividend_yield=0.01  # type: ignore[arg-type]
    )[0]
    assert vector_delta == pytest.approx(scalar_delta, abs=1e-10)


def test_delta_hedge_ratios_shape_and_call_bounds() -> None:
    paths = np.full((5, 11), 100.0)
    ratios = black_scholes_delta_hedge_ratios(
        paths,
        dt=0.1,
        strike=100.0,
        maturity=1.0,
        risk_free_rate=0.05,
        volatility=0.2,
        option_type="call",
    )
    assert ratios.shape == (5, 10)
    assert np.all(ratios >= 0.0) and np.all(ratios <= 1.0)


def test_delta_hedge_ratios_are_causal() -> None:
    """Changing a *later* price must not change an *earlier* hedge ratio."""
    rng = np.random.default_rng(0)
    paths = 100.0 + rng.standard_normal((4, 11)) * 2.0
    ratios_original = black_scholes_delta_hedge_ratios(
        paths, 0.1, 100.0, 1.0, 0.05, 0.2, "call"
    )
    mutated = paths.copy()
    mutated[:, -1] += 1000.0  # blow up only the terminal price
    ratios_mutated = black_scholes_delta_hedge_ratios(mutated, 0.1, 100.0, 1.0, 0.05, 0.2, "call")
    assert np.allclose(ratios_original[:, :-1], ratios_mutated[:, :-1])


def test_no_trade_band_zero_width_tracks_target_exactly() -> None:
    target = np.array([[0.2, 0.5, 0.3, 0.9]])
    actual = apply_no_trade_band(target, band_width=0.0)
    assert np.allclose(actual, target)


def test_no_trade_band_reduces_turnover() -> None:
    rng = np.random.default_rng(1)
    target = np.cumsum(rng.standard_normal((50, 30)) * 0.05, axis=1)
    no_band = apply_no_trade_band(target, band_width=0.0)
    with_band = apply_no_trade_band(target, band_width=0.1)

    def turnover(actual: np.ndarray) -> np.ndarray:
        diffs = np.diff(actual, axis=1, prepend=0.0)
        return np.abs(diffs).sum(axis=1)

    assert turnover(with_band).mean() < turnover(no_band).mean()


def test_no_trade_band_rejects_negative_width() -> None:
    with pytest.raises(ValueError):
        apply_no_trade_band(np.zeros((2, 2)), band_width=-0.1)
