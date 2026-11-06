import numpy as np
import pytest

from prometheus.macrocore.baselines import (
    DistributionForecast,
    fit_autoregression,
    fit_vector_autoregression,
    gaussian_crps,
    persistence_forecast,
)


def test_distribution_forecast_rejects_invalid_fields() -> None:
    with pytest.raises(ValueError):
        DistributionForecast(horizon=0, mean=0.0, std=1.0)
    with pytest.raises(ValueError):
        DistributionForecast(horizon=1, mean=0.0, std=-1.0)


def test_distribution_forecast_interval_matches_hand_computed_z_score() -> None:
    forecast = DistributionForecast(horizon=1, mean=10.0, std=2.0)
    lower, upper = forecast.interval(0.8)
    # 80% central interval -> z = 1.2815515655446004 (10th/90th percentile)
    z = 1.2815515655446004
    assert lower == pytest.approx(10.0 - z * 2.0, abs=1e-6)
    assert upper == pytest.approx(10.0 + z * 2.0, abs=1e-6)
    with pytest.raises(ValueError):
        forecast.interval(0.0)
    with pytest.raises(ValueError):
        forecast.interval(1.0)


def test_gaussian_crps_matches_known_values() -> None:
    # Cross-checked against Monte Carlo (5M draws) in pre-implementation
    # verification; pinned here as exact regression values.
    assert gaussian_crps(0.0, 1.0, 0.5) == pytest.approx(0.33140, abs=1e-4)
    assert gaussian_crps(3.0, 2.0, -1.0) == pytest.approx(2.90558, abs=1e-3)


def test_gaussian_crps_rejects_negative_std() -> None:
    with pytest.raises(ValueError):
        gaussian_crps(0.0, -1.0, 0.0)


def test_gaussian_crps_reduces_to_absolute_error_at_zero_std() -> None:
    assert gaussian_crps(5.0, 0.0, 8.0) == pytest.approx(3.0)
    assert gaussian_crps(5.0, 0.0, 5.0) == pytest.approx(0.0)


def test_persistence_forecast_uses_last_value_as_point_forecast() -> None:
    history = np.array([1.0, 2.0, 3.0, 4.0, 5.0])
    forecasts = persistence_forecast(history, [1, 3, 6])
    assert [f.mean for f in forecasts] == [5.0, 5.0, 5.0]


def test_persistence_forecast_std_scales_with_sqrt_horizon() -> None:
    rng = np.random.default_rng(0)
    history = np.cumsum(rng.standard_normal(500))  # a random walk
    forecasts = persistence_forecast(history, [1, 4, 9])
    std_1, std_4, std_9 = (f.std for f in forecasts)
    assert std_4 == pytest.approx(std_1 * 2.0, rel=1e-9)
    assert std_9 == pytest.approx(std_1 * 3.0, rel=1e-9)


def test_persistence_forecast_rejects_invalid_inputs() -> None:
    with pytest.raises(ValueError):
        persistence_forecast(np.array([1.0]), [1])
    with pytest.raises(ValueError):
        persistence_forecast(np.array([1.0, 2.0, 3.0]), [0])


def test_fit_autoregression_rejects_invalid_inputs() -> None:
    with pytest.raises(ValueError):
        fit_autoregression(np.arange(10.0), order=0)
    with pytest.raises(ValueError):
        fit_autoregression(np.arange(3.0), order=2)


def test_fit_autoregression_recovers_known_ar1_coefficient() -> None:
    rng = np.random.default_rng(1)
    phi_true = 0.6
    sigma_true = 0.5
    n = 20000
    y = np.zeros(n)
    for t in range(1, n):
        y[t] = phi_true * y[t - 1] + sigma_true * rng.standard_normal()
    fitted = fit_autoregression(y, order=1)
    assert fitted.phi[0] == pytest.approx(phi_true, abs=0.02)
    assert fitted.residual_variance == pytest.approx(sigma_true**2, rel=0.1)


def test_ar_forecast_variance_converges_to_stationary_variance_at_long_horizon() -> None:
    """For a stationary AR(1), Var(y_t) = sigma^2/(1-phi^2) exactly; the
    h-step forecast variance must converge to this as h grows, since the
    forecast's informational value about the far future vanishes -- a
    cheap, exact analytical check independent of the psi-weight
    machinery's own Monte Carlo verification."""
    phi = 0.7
    sigma2 = 1.0
    from prometheus.macrocore.baselines import FittedAutoregression

    fitted = FittedAutoregression(
        order=1,
        intercept=0.0,
        phi=np.array([phi]),
        residual_variance=sigma2,
        last_values=np.array([0.0]),
    )
    forecasts = fitted.forecast([1, 50, 200])
    stationary_variance = sigma2 / (1 - phi**2)
    assert forecasts[0].std**2 == pytest.approx(sigma2, abs=1e-9)
    assert forecasts[-1].std**2 == pytest.approx(stationary_variance, rel=1e-6)


def test_ar_forecast_matches_from_scratch_second_computation_of_psi_weights() -> None:
    """A completely independent re-derivation of the psi-weight variance
    formula (direct recursive expansion, not calling production code),
    for an AR(2) process."""
    phi = np.array([0.4, -0.3])
    sigma2 = 2.0
    fitted = _fitted_ar(phi, sigma2, intercept=1.5, last_values=np.array([3.0, -1.0]))
    horizons = [1, 2, 3, 4, 8]
    forecasts = {f.horizon: f for f in fitted.forecast(horizons)}

    # Independent psi-weight computation.
    max_h = max(horizons)
    psi = [1.0]
    for j in range(1, max_h):
        total = 0.0
        for i in range(1, min(j, len(phi)) + 1):
            total += phi[i - 1] * psi[j - i]
        psi.append(total)
    variances = np.cumsum(np.array(psi) ** 2) * sigma2

    # Independent point-forecast recursion.
    history = [-1.0, 3.0]  # oldest-first
    for _ in range(max_h):
        value = 1.5 + phi[0] * history[-1] + phi[1] * history[-2]
        history.append(value)
    point_forecasts = history[2:]

    for h in horizons:
        assert forecasts[h].mean == pytest.approx(point_forecasts[h - 1], abs=1e-9)
        assert forecasts[h].std**2 == pytest.approx(variances[h - 1], abs=1e-9)


def _fitted_ar(phi, sigma2, intercept, last_values):
    from prometheus.macrocore.baselines import FittedAutoregression

    return FittedAutoregression(
        order=len(phi),
        intercept=intercept,
        phi=phi,
        residual_variance=sigma2,
        last_values=last_values,
    )


def test_fit_vector_autoregression_rejects_invalid_inputs() -> None:
    history = np.random.default_rng(0).standard_normal((5, 2))
    with pytest.raises(ValueError):
        fit_vector_autoregression(history, order=0, series_ids=["A", "B"])
    with pytest.raises(ValueError):
        fit_vector_autoregression(history, order=1, series_ids=["A"])
    with pytest.raises(ValueError):
        short_history = np.random.default_rng(0).standard_normal((3, 2))
        fit_vector_autoregression(short_history, order=2, series_ids=["A", "B"])


def test_var_forecast_matches_from_scratch_second_computation() -> None:
    from prometheus.macrocore.baselines import FittedVectorAutoregression

    phi1 = np.array([[0.5, 0.1], [0.05, 0.4]])
    phi2 = np.array([[-0.2, 0.0], [0.0, -0.1]])
    sigma = np.array([[1.0, 0.3], [0.3, 0.8]])
    last_values = np.array([[0.2, 0.3], [1.5, -0.5]])  # oldest-first
    intercept = np.array([0.1, -0.2])

    fitted = FittedVectorAutoregression(
        order=2,
        intercept=intercept,
        phi_matrices=[phi1, phi2],
        residual_covariance=sigma,
        last_values=last_values,
        series_ids=["A", "B"],
    )
    horizons = [1, 2, 3, 5, 8]
    result = fitted.forecast(horizons)

    # Independent psi-weight + point-forecast recursion.
    k = 2
    max_h = max(horizons)
    psi = [np.eye(k)]
    for j in range(1, max_h):
        total = np.zeros((k, k))
        for i in range(1, min(j, 2) + 1):
            total = total + [phi1, phi2][i - 1] @ psi[j - i]
        psi.append(total)
    covariances = []
    running = np.zeros((k, k))
    for j in range(max_h):
        running = running + psi[j] @ sigma @ psi[j].T
        covariances.append(running)

    history = [last_values[0], last_values[1]]
    for _ in range(max_h):
        value = intercept + phi1 @ history[-1] + phi2 @ history[-2]
        history.append(value)
    point_forecasts = history[2:]

    for idx, series_id in enumerate(["A", "B"]):
        by_horizon = {f.horizon: f for f in result[series_id]}
        for h in horizons:
            assert by_horizon[h].mean == pytest.approx(point_forecasts[h - 1][idx], abs=1e-9)
            assert by_horizon[h].std**2 == pytest.approx(covariances[h - 1][idx, idx], abs=1e-9)


def test_fit_vector_autoregression_recovers_known_coefficients() -> None:
    rng = np.random.default_rng(2)
    phi1 = np.array([[0.5, 0.0], [0.0, 0.4]])
    sigma = np.array([[1.0, 0.0], [0.0, 1.0]])
    chol = np.linalg.cholesky(sigma)
    n = 20000
    y = np.zeros((n, 2))
    for t in range(1, n):
        y[t] = phi1 @ y[t - 1] + chol @ rng.standard_normal(2)
    fitted = fit_vector_autoregression(y, order=1, series_ids=["A", "B"])
    assert fitted.phi_matrices[0] == pytest.approx(phi1, abs=0.03)


def test_fit_vector_autoregression_rejects_non_2d_history() -> None:
    with pytest.raises(ValueError):
        fit_vector_autoregression(np.arange(10.0), order=1, series_ids=["A"])


def test_fit_autoregression_rejects_degenerate_minimal_sample() -> None:
    """At the smallest history size the input-shape check alone allows
    (order + 2 observations, order=1), there are zero residual degrees
    of freedom left to estimate a variance from -- a distinct failure
    mode from "too short to even form the design matrix," caught by a
    separate check further down `fit_autoregression`."""
    with pytest.raises(ValueError):
        fit_autoregression(np.array([1.0, 2.0, 3.0]), order=1)


def test_fit_vector_autoregression_rejects_degenerate_minimal_sample() -> None:
    history = np.random.default_rng(0).standard_normal((4, 2))  # order + k + 1 = 1+2+1 = 4
    with pytest.raises(ValueError):
        fit_vector_autoregression(history, order=1, series_ids=["A", "B"])


def test_fitted_autoregression_forecast_rejects_invalid_horizons() -> None:
    from prometheus.macrocore.baselines import FittedAutoregression

    fitted = FittedAutoregression(
        order=1,
        intercept=0.0,
        phi=np.array([0.5]),
        residual_variance=1.0,
        last_values=np.array([0.0]),
    )
    with pytest.raises(ValueError):
        fitted.forecast([0])


def test_fitted_vector_autoregression_forecast_rejects_invalid_horizons() -> None:
    from prometheus.macrocore.baselines import FittedVectorAutoregression

    fitted = FittedVectorAutoregression(
        order=1,
        intercept=np.array([0.0, 0.0]),
        phi_matrices=[np.eye(2) * 0.5],
        residual_covariance=np.eye(2),
        last_values=np.array([[0.0, 0.0]]),
        series_ids=["A", "B"],
    )
    with pytest.raises(ValueError):
        fitted.forecast([-1])
