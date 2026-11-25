import numpy as np
import pytest

from prometheus.stochastica.convergence import (
    ConvergencePoint,
    WeakConvergenceStudy,
    estimate_weak_convergence_order,
    heston_strong_convergence_study,
    heston_weak_convergence_study,
)
from prometheus.stochastica.heston import HestonParams, heston_step, simulate_heston_paths
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


def test_heston_step_floors_a_negative_variance_in_every_term() -> None:
    """With v < 0 the scheme uses max(v, 0) in the drift and the diffusion, so no noise enters the
    step: log S moves by mu dt, and v by kappa theta dt added to the unfloored v (then floored)."""
    params = HestonParams(mu=0.05, kappa=2.0, theta=0.04, xi=0.5, rho=-0.5, v0=0.04)
    log_s, v = heston_step(
        np.array([1.0]), np.array([-0.001]), params, 0.1, np.array([0.7]), np.array([-0.9])
    )
    assert log_s[0] == pytest.approx(1.0 + 0.05 * 0.1)
    assert v[0] == pytest.approx(-0.001 + 2.0 * 0.04 * 0.1)


def test_heston_step_is_the_scheme_simulate_heston_paths_runs() -> None:
    """The shared step reproduces the path simulator exactly when fed the increments it draws."""
    params = HestonParams(mu=0.03, kappa=1.5, theta=0.04, xi=0.4, rho=-0.6, v0=0.045)
    n_steps, n_paths, maturity = 20, 50, 1.0
    prices, variances = simulate_heston_paths(
        100.0, params, maturity, n_steps, n_paths, np.random.default_rng(5)
    )
    rng = np.random.default_rng(5)
    z1 = rng.standard_normal((n_paths, n_steps))
    z2 = rng.standard_normal((n_paths, n_steps))
    dt = maturity / n_steps
    dw_s = z1 * np.sqrt(dt)
    dw_v = (params.rho * z1 + np.sqrt(1 - params.rho**2) * z2) * np.sqrt(dt)
    log_s, v = np.full(n_paths, np.log(100.0)), np.full(n_paths, params.v0)
    for t in range(n_steps):
        log_s, v = heston_step(log_s, v, params, dt, dw_s[:, t], dw_v[:, t])
    np.testing.assert_array_equal(np.exp(log_s), prices[:, -1])
    np.testing.assert_array_equal(v, variances[:, -1])


def test_heston_strong_convergence_study_rejects_invalid_inputs() -> None:
    params = HestonParams(mu=0.03, kappa=1.5, theta=0.04, xi=0.4, rho=-0.6, v0=0.045)
    rng = np.random.default_rng(0)

    def study(steps: list[int], ref: int = 256, paths: int = 10, batches: int = 1, t: float = 1.0):
        return heston_strong_convergence_study(params, t, steps, ref, paths, batches, rng)

    for bad in (
        lambda: study([8]),  # one point cannot fit an order
        lambda: study([16, 8]),  # not increasing
        lambda: study([8, 8]),  # duplicate
        lambda: study([8, 24]),  # 24 does not divide 256
        lambda: study([8, 16], ref=64),  # reference not 8x the finest grid
        lambda: study([8, 16], paths=0),
        lambda: study([8, 16], batches=0),
        lambda: study([8, 16], t=0.0),
        lambda: study([0, 8]),
    ):
        with pytest.raises(ValueError):
            bad()


def test_strong_error_shrinks_with_dt_and_the_order_depends_on_the_feller_ratio() -> None:
    """Measured, fixed seed (seeds 1-3 spread each order by < 0.02): the pathwise error
    of the full-truncation scheme decays at about 1/2 when the Feller condition holds and clearly
    slower when it is violated. If the coarse grids were driven by independent noise instead of the
    summed fine increments, the error would not shrink at all and these would fail."""
    feller = HestonParams(mu=0.05, kappa=2.0, theta=0.04, xi=0.3, rho=-0.7, v0=0.04)
    violated = HestonParams(mu=0.05, kappa=0.5, theta=0.04, xi=1.0, rho=-0.7, v0=0.04)
    assert feller.feller_ratio() >= 1.0 > violated.feller_ratio()

    steps = [4, 8, 16, 32, 64]
    good = heston_strong_convergence_study(
        feller, 1.0, steps, 512, 4000, 4, np.random.default_rng(1)
    )
    bad = heston_strong_convergence_study(
        violated, 1.0, steps, 512, 4000, 4, np.random.default_rng(1)
    )
    errors = [p.log_price_error for p in good.points]
    assert all(a > b for a, b in zip(errors, errors[1:], strict=False))
    assert 0.40 < good.log_price_order < 0.65
    assert 0.45 < good.variance_order < 0.75
    assert 0.20 < bad.log_price_order < 0.40
    assert bad.log_price_order < good.log_price_order - 0.1
    assert bad.variance_order < good.variance_order - 0.2
    assert good.feller_ratio == pytest.approx(feller.feller_ratio())
    # the error at the coarsest grid is far above its own standard error: the signal is not noise
    assert good.points[0].log_price_error > 20 * good.points[0].log_price_standard_error
