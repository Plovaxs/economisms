"""PDE-06: deep BSDE solver, validated in 1D against the closed-form
Black-Scholes price/Delta and in 2D/3D (where no closed form or grid
solver reaches, see test_pde_benchmark.py) against independent plain
Monte Carlo."""

from __future__ import annotations

from datetime import date

import numpy as np
import pytest

from prometheus.pde_solvers.deep_bsde import (
    DeepBSDEResult,
    _basket_monte_carlo_price,
    train_deep_bsde,
)
from prometheus.pde_solvers.problem import BasketOptionPDESpec
from prometheus.volterra.black_scholes import black_scholes_greeks, black_scholes_price
from prometheus.volterra.instruments import EuropeanOption
from prometheus.volterra.market import MarketSnapshot

_SPEC_1D = BasketOptionPDESpec(
    risk_free_rate=0.05,
    volatilities=(0.2,),
    correlation=((1.0,),),
    maturity=1.0,
    strike=100.0,
    option_type="call",
)
_MARKET = MarketSnapshot(as_of=date(2024, 1, 1), spot=100.0, risk_free_rate=0.05, volatility=0.2)
_OPTION = EuropeanOption(100.0, 1.0, "call")


@pytest.fixture(scope="module")
def trained_1d() -> DeepBSDEResult:
    """Trained once (~15-30s) and reused by every test that only reads
    its price/Delta -- see the identical rationale in test_pde_pinn.py."""
    return train_deep_bsde(
        _SPEC_1D,
        np.array([100.0]),
        seed=0,
        n_time=20,
        n_paths=512,
        n_epochs=400,
        learning_rate=0.03,
    )


def test_1d_price_matches_closed_form_within_disclosed_tolerance(
    trained_1d: DeepBSDEResult,
) -> None:
    closed_form = black_scholes_price(_MARKET, _OPTION)
    assert trained_1d.price == pytest.approx(closed_form, abs=2.0)


def test_1d_delta_estimate_matches_closed_form(trained_1d: DeepBSDEResult) -> None:
    greeks = black_scholes_greeks(_MARKET, _OPTION)
    assert trained_1d.delta_estimate is not None
    assert trained_1d.delta_estimate == pytest.approx(greeks.delta, abs=0.1)


def test_more_epochs_materially_closes_the_price_gap_to_closed_form() -> None:
    """PR-176: a direct sweep (4 seeds, see `benchmark.compute_cost_
    comparison`'s own docstring for the full numbers) found 400 epochs
    -- this file's own `trained_1d` fixture, and the value
    `pde_solvers.benchmark.compute_cost_comparison` used until this PR
    -- genuinely undertrains this model (price error ~1.43-1.48,
    consistent across seeds, not noise): quadrupling to 1600 epochs
    drops it to ~0.005-0.06, within ~2x of the classical grid's own
    error rather than ~580x. Locked in at seed 0 (deterministic,
    already the seed `compute_cost_comparison` itself uses) as a
    permanent regression check that this is a real training-budget
    effect, not a one-off measurement."""
    closed_form = black_scholes_price(_MARKET, _OPTION)
    undertrained = train_deep_bsde(
        _SPEC_1D, np.array([100.0]), seed=0, n_time=20, n_paths=512, n_epochs=400,
        learning_rate=0.03,
    )
    well_trained = train_deep_bsde(
        _SPEC_1D, np.array([100.0]), seed=0, n_time=20, n_paths=512, n_epochs=1600,
        learning_rate=0.03,
    )
    undertrained_error = abs(undertrained.price - closed_form)
    well_trained_error = abs(well_trained.price - closed_form)
    assert well_trained_error < undertrained_error / 10


def test_basket_delta_estimate_is_not_reported() -> None:
    """PDE-08's Greeks benchmark only reports what it has validated --
    a basket's Z_0 does not have the same scalar sigma*S*Delta identity
    without further derivation this module does not claim to have
    done, so `delta_estimate` must be None, not a guessed number."""
    corr = ((1.0, 0.3), (0.3, 1.0))
    spec = BasketOptionPDESpec(
        risk_free_rate=0.05,
        volatilities=(0.2, 0.25),
        correlation=corr,
        maturity=1.0,
        strike=100.0,
        option_type="call",
    )
    result = train_deep_bsde(
        spec, np.array([100.0, 100.0]), seed=0, n_time=10, n_paths=128, n_epochs=50
    )
    assert result.delta_estimate is None


def test_basket_price_matches_independent_monte_carlo_ground_truth() -> None:
    """d=2: no closed form, no grid solver reaches this -- the
    independent reference is a plain (un-learned) Monte Carlo average
    of the discounted basket payoff over many more paths than the
    network itself ever trains on."""
    corr = ((1.0, 0.3), (0.3, 1.0))
    spec = BasketOptionPDESpec(
        risk_free_rate=0.05,
        volatilities=(0.2, 0.25),
        correlation=corr,
        maturity=1.0,
        strike=100.0,
        option_type="call",
    )
    s0 = np.array([100.0, 100.0])
    mc_price = _basket_monte_carlo_price(spec, s0, n_time=100, n_paths=200_000, seed=123)
    result = train_deep_bsde(
        spec, s0, seed=0, n_time=20, n_paths=512, n_epochs=500, learning_rate=0.03
    )
    assert result.price == pytest.approx(mc_price, abs=1.5)


def test_three_asset_basket_price_matches_independent_monte_carlo_ground_truth() -> None:
    corr = ((1.0, 0.3, 0.1), (0.3, 1.0, 0.2), (0.1, 0.2, 1.0))
    spec = BasketOptionPDESpec(
        risk_free_rate=0.05,
        volatilities=(0.2, 0.25, 0.18),
        correlation=corr,
        maturity=1.0,
        strike=100.0,
        option_type="call",
    )
    s0 = np.array([100.0, 100.0, 100.0])
    mc_price = _basket_monte_carlo_price(spec, s0, n_time=100, n_paths=200_000, seed=123)
    result = train_deep_bsde(
        spec, s0, seed=0, n_time=20, n_paths=512, n_epochs=500, learning_rate=0.03
    )
    assert result.price == pytest.approx(mc_price, abs=1.5)


def test_rejects_mismatched_s0_shape() -> None:
    with pytest.raises(ValueError, match="s0 must have shape"):
        train_deep_bsde(
            _SPEC_1D, np.array([100.0, 100.0]), seed=0, n_time=5, n_paths=16, n_epochs=2
        )


def test_rejects_non_positive_n_time_n_paths_n_epochs() -> None:
    with pytest.raises(ValueError, match="n_time"):
        train_deep_bsde(_SPEC_1D, np.array([100.0]), seed=0, n_time=0, n_paths=16, n_epochs=2)
    with pytest.raises(ValueError, match="n_paths"):
        train_deep_bsde(_SPEC_1D, np.array([100.0]), seed=0, n_time=5, n_paths=0, n_epochs=2)
    with pytest.raises(ValueError, match="n_epochs"):
        train_deep_bsde(_SPEC_1D, np.array([100.0]), seed=0, n_time=5, n_paths=16, n_epochs=0)


def test_extreme_rate_and_maturity_raises_instead_of_silent_overflow() -> None:
    """Mirrors stochastica.gbm's own confirmed extreme-input finding
    (r=5, maturity=142 overflows exp) -- this module simulates the
    same kind of correlated-GBM paths and must not silently return an
    inf/nan path either."""
    spec = BasketOptionPDESpec(
        risk_free_rate=5.0,
        volatilities=(0.2,),
        correlation=((1.0,),),
        maturity=142.0,
        strike=100.0,
        option_type="call",
    )
    with pytest.raises(ValueError, match="no computable answer"):
        train_deep_bsde(spec, np.array([100.0]), seed=0, n_time=200, n_paths=500, n_epochs=1)
