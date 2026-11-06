import numpy as np
import pytest

from prometheus.stochastica.convergence import (
    ConvergencePoint,
    WeakConvergenceStudy,
    estimate_weak_convergence_order,
    heston_weak_convergence_study,
)
from prometheus.stochastica.heston import HestonParams
from prometheus.volterra.heston_pricer import heston_call_price


def test_estimate_weak_convergence_order_rejects_invalid_inputs() -> None:
    with pytest.raises(ValueError):
        estimate_weak_convergence_order([0.1], [0.5])
    with pytest.raises(ValueError):
        estimate_weak_convergence_order([0.1, 0.05], [0.5])
    with pytest.raises(ValueError):
        estimate_weak_convergence_order([0.1, 0.05], [0.5, 0.0])


def test_estimate_weak_convergence_order_recovers_exact_order_one() -> None:
    dts = [0.5, 0.25, 0.125, 0.0625]
    biases = [3.0 * dt for dt in dts]  # exactly C * dt^1
    order = estimate_weak_convergence_order(dts, biases)
    assert order == pytest.approx(1.0, abs=1e-9)


def test_estimate_weak_convergence_order_recovers_exact_order_two() -> None:
    dts = [0.5, 0.25, 0.125, 0.0625]
    biases = [-2.0 * dt**2 for dt in dts]  # exactly C * dt^2, negative sign too
    order = estimate_weak_convergence_order(dts, biases)
    assert order == pytest.approx(2.0, abs=1e-9)


def test_bias_decreases_monotonically_true_and_false_cases() -> None:
    decreasing = WeakConvergenceStudy(
        reference_price=10.0,
        points=[
            ConvergencePoint(8, 0.125, 10.3, 0.01, 0.3),
            ConvergencePoint(32, 0.03125, 10.1, 0.01, 0.1),
            ConvergencePoint(128, 0.0078125, 10.02, 0.01, 0.02),
        ],
        fitted_order=0.9,
    )
    assert decreasing.bias_decreases_monotonically() is True

    not_decreasing = WeakConvergenceStudy(
        reference_price=10.0,
        points=[
            ConvergencePoint(8, 0.125, 10.1, 0.01, 0.1),
            ConvergencePoint(32, 0.03125, 10.3, 0.01, 0.3),
        ],
        fitted_order=-0.9,
    )
    assert not_decreasing.bias_decreases_monotonically() is False


def test_heston_weak_convergence_study_rejects_invalid_inputs() -> None:
    params = HestonParams(mu=0.03, kappa=1.5, theta=0.04, xi=0.4, rho=-0.6, v0=0.045)
    rng = np.random.default_rng(0)
    with pytest.raises(ValueError):
        heston_weak_convergence_study(100.0, 100.0, 1.0, 0.03, 0.0, params, [8], 100, 1, rng)
    with pytest.raises(ValueError):
        heston_weak_convergence_study(100.0, 100.0, 1.0, 0.03, 0.0, params, [32, 8], 100, 1, rng)
    with pytest.raises(ValueError):
        heston_weak_convergence_study(100.0, 100.0, 1.0, 0.03, 0.0, params, [8, 8], 100, 1, rng)
    with pytest.raises(ValueError):
        heston_weak_convergence_study(100.0, 100.0, 1.0, 0.03, 0.0, params, [8, 32], 0, 1, rng)
    with pytest.raises(ValueError):
        heston_weak_convergence_study(100.0, 100.0, 1.0, 0.03, 0.0, params, [8, 32], 100, 0, rng)


def test_heston_weak_convergence_study_shows_shrinking_bias_near_order_one() -> None:
    """A deterministic (fixed-seed), memory-bounded (batched) convergence
    study of the log-Euler/full-truncation Heston scheme: the bias
    against the closed-form reference price must shrink monotonically as
    dt decreases, and the fitted weak-convergence order must land in a
    range consistent with the theoretical order-1 prediction (generous
    enough to tolerate Monte Carlo noise, tight enough to rule out "no
    real convergence" or an implausibly high order)."""
    s0, strike, maturity, r, q = 100.0, 100.0, 1.0, 0.03, 0.0
    params = HestonParams(mu=r, kappa=1.5, theta=0.04, xi=0.4, rho=-0.6, v0=0.045)
    rng = np.random.default_rng(123)

    study = heston_weak_convergence_study(
        s0, strike, maturity, r, q, params,
        step_counts=[8, 32, 128], n_paths_per_batch=50_000, n_batches=10, rng=rng,
    )

    assert study.reference_price == pytest.approx(
        heston_call_price(s0, strike, maturity, r, q, params)
    )
    assert study.bias_decreases_monotonically() is True
    assert 0.3 < study.fitted_order < 1.5
    # Every bias must still be well outside pure noise at the coarse end,
    # confirming the signal (not just the fit) is real.
    coarsest = study.points[0]
    assert abs(coarsest.bias) > 3 * coarsest.mc_standard_error
