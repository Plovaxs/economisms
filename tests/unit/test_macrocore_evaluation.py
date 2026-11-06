from datetime import date, timedelta

import numpy as np
import pytest

from prometheus.econosim.pit import FutureDataError, MacroObservation, PointInTimeStore
from prometheus.macrocore.baselines import DistributionForecast
from prometheus.macrocore.evaluation import (
    ForecastScore,
    backtest_autoregressive,
    backtest_persistence,
    backtest_vector_autoregressive,
    coverage_confidence_interval,
    summarize_scores,
)
from prometheus.macrocore.synthetic_data import generate_synthetic_macro_var_series


def _panel(n_periods=120, publication_lag_days=20, seed=7):
    rng = np.random.default_rng(seed)
    phi1 = np.array([[0.5, 0.1], [0.05, 0.4]])
    sigma = np.array([[1.0, 0.2], [0.2, 0.7]])
    return generate_synthetic_macro_var_series(
        series_ids=["SYN_GDP", "SYN_UNRATE"],
        phi_matrices=[phi1],
        sigma=sigma,
        n_periods=n_periods,
        start_date=date(2015, 1, 1),
        publication_lag_days=publication_lag_days,
        rng=rng,
    )


def test_forecast_score_derived_metrics() -> None:
    forecast = DistributionForecast(horizon=1, mean=10.0, std=2.0)
    score = ForecastScore(origin_index=0, horizon=1, forecast=forecast, actual=12.0)
    assert score.absolute_error == pytest.approx(2.0)
    assert score.squared_error == pytest.approx(4.0)
    assert score.crps > 0.0
    assert score.covered(0.95) is True
    assert score.covered(0.01) is False


def test_backtest_persistence_produces_scores_for_every_origin_and_horizon() -> None:
    panel = _panel(n_periods=60)
    horizons = [1, 3, 6]
    scores = backtest_persistence(
        panel.store, "SYN_GDP", panel.observation_dates, panel.known_at_dates,
        min_train_periods=10, horizons=horizons,
    )
    assert len(scores) > 0
    assert {s.horizon for s in scores} == set(horizons)
    for s in scores:
        assert s.forecast.mean == pytest.approx(
            panel.levels[s.origin_index, panel.series_ids.index("SYN_GDP")]
        )


def test_autoregressive_beats_persistence_on_strongly_mean_reverting_data() -> None:
    """A strongly mean-reverting AR(1) series (small phi) is much more
    predictable by an AR model than by a naive persistence forecast --
    not a universal truth for every series, but true by construction
    here, so this is a meaningful, not tautological, sanity check."""
    rng = np.random.default_rng(3)
    phi = np.array([[0.1, 0.0], [0.0, 0.1]])  # fast mean reversion to zero
    sigma = np.array([[1.0, 0.0], [0.0, 1.0]])
    panel = generate_synthetic_macro_var_series(
        series_ids=["A", "B"], phi_matrices=[phi], sigma=sigma, n_periods=150,
        start_date=date(2010, 1, 1), publication_lag_days=10, rng=rng,
    )
    horizons = [3]
    ar_scores = backtest_autoregressive(
        panel.store, "A", panel.observation_dates, panel.known_at_dates,
        order=1, min_train_periods=20, horizons=horizons,
    )
    persistence_scores = backtest_persistence(
        panel.store, "A", panel.observation_dates, panel.known_at_dates,
        min_train_periods=20, horizons=horizons,
    )
    ar_rmse = summarize_scores(ar_scores)[3]["rmse"]
    persistence_rmse = summarize_scores(persistence_scores)[3]["rmse"]
    assert ar_rmse < persistence_rmse


def test_backtest_vector_autoregressive_returns_scores_per_series() -> None:
    panel = _panel(n_periods=80)
    horizons = [1, 2]
    results = backtest_vector_autoregressive(
        panel.store, panel.series_ids, panel.observation_dates, panel.known_at_dates,
        order=1, min_train_periods=15, horizons=horizons,
    )
    assert set(results.keys()) == set(panel.series_ids)
    for series_id in panel.series_ids:
        assert len(results[series_id]) > 0
        assert {s.horizon for s in results[series_id]} == set(horizons)


def test_summarize_scores_matches_hand_computed_mae_rmse() -> None:
    forecasts = [DistributionForecast(horizon=1, mean=m, std=1.0) for m in [0.0, 0.0, 0.0]]
    actuals = [1.0, -2.0, 3.0]
    scores = [
        ForecastScore(origin_index=i, horizon=1, forecast=f, actual=a)
        for i, (f, a) in enumerate(zip(forecasts, actuals, strict=True))
    ]
    summary = summarize_scores(scores)
    assert summary[1]["mae"] == pytest.approx((1.0 + 2.0 + 3.0) / 3.0)
    assert summary[1]["rmse"] == pytest.approx(np.sqrt((1.0 + 4.0 + 9.0) / 3.0))
    assert summary[1]["n_origins"] == 3.0


def test_coverage_rate_of_a_calibrated_model_falls_within_its_confidence_interval() -> None:
    """Simulates MANY independent Gaussian forecast/actual pairs drawn
    from the model's own assumed distribution (so the model is, by
    construction, perfectly calibrated) and checks the realized 80%
    coverage rate lands inside the binomial confidence interval --
    confirming `covered()`/`coverage_confidence_interval` agree with each
    other under the null of correct calibration, not just independently
    plausible-looking numbers."""
    rng = np.random.default_rng(11)
    n = 20000
    mean, std = 5.0, 2.0
    forecast = DistributionForecast(horizon=1, mean=mean, std=std)
    actuals = mean + std * rng.standard_normal(n)
    scores = [
        ForecastScore(origin_index=i, horizon=1, forecast=forecast, actual=float(a))
        for i, a in enumerate(actuals)
    ]
    summary = summarize_scores(scores, coverage_level=0.8)
    lower, upper = coverage_confidence_interval(n, 0.8)
    assert lower <= summary[1]["coverage_rate"] <= upper


def test_coverage_confidence_interval_rejects_invalid_inputs() -> None:
    with pytest.raises(ValueError):
        coverage_confidence_interval(0, 0.8)
    with pytest.raises(ValueError):
        coverage_confidence_interval(100, 1.0)


def test_backtests_fail_closed_if_a_period_is_requested_before_its_known_at_date() -> None:
    """A direct demonstration that the point-in-time gate is actually
    load-bearing inside the backtest harness: manually constructing a
    store where a value is missing until far too late must surface as
    FutureDataError through the backtest, not a silently wrong score."""
    store = PointInTimeStore()
    observation_dates = [date(2020, 1, 1), date(2020, 2, 1), date(2020, 3, 1), date(2020, 4, 1)]
    known_at_dates = [d + timedelta(days=10) for d in observation_dates]
    # Deliberately omit period index 2 entirely (never published).
    for i, d in enumerate(observation_dates):
        if i == 2:
            continue
        store.record(MacroObservation("X", d, known_at_dates[i], value=float(i)))

    with pytest.raises(FutureDataError):
        backtest_persistence(
            store, "X", observation_dates, known_at_dates, min_train_periods=2, horizons=[1]
        )
