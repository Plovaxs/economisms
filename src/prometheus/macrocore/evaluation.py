"""Rolling-origin backtesting for the classical forecasting baselines
(ECONOSIM-X/PROMETHEUS-X addendum FP-04, section 07's "rolling-origin
backtests ... fit ... only on available training windows", and E01's
"MAE, RMSE, CRPS/coverage" minimum evidence).

Every read here -- both the training window AND the eventual scoring
value -- goes through `econosim.pit.require_eligible`, never through a
raw ground-truth array, at two DIFFERENT `as_of` dates: the origin's own
as-of (for fitting) and the scored period's own publication date (for
scoring). This makes leakage physically impossible rather than merely
avoided by careful indexing: a bug that accidentally included a
not-yet-published period would raise `FutureDataError` immediately rather
than silently inflating the backtest's apparent accuracy.

"ARIMA" in the addendum's own experiment-matrix language (E01: "Persistence
/ ARIMA / VAR / TCN") is represented here by AR(p) -- see
`macrocore.baselines`'s module docstring for why a full differenced,
moving-average Box-Jenkins ARIMA(p, d, q) was not attempted. Regime-
conditioned error breakdowns (E01's "error by regime") are NOT implemented
here -- there is no regime-labeling mechanism anywhere in this repository
yet.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import numpy as np
from scipy.stats import norm

from prometheus.econosim.pit import PointInTimeStore, require_eligible
from prometheus.macrocore.baselines import (
    DistributionForecast,
    fit_autoregression,
    fit_vector_autoregression,
    gaussian_crps,
    persistence_forecast,
)


@dataclass(frozen=True, slots=True)
class ForecastScore:
    origin_index: int
    horizon: int
    forecast: DistributionForecast
    actual: float

    @property
    def absolute_error(self) -> float:
        return abs(self.actual - self.forecast.mean)

    @property
    def squared_error(self) -> float:
        return (self.actual - self.forecast.mean) ** 2

    @property
    def crps(self) -> float:
        return gaussian_crps(self.forecast.mean, self.forecast.std, self.actual)

    def covered(self, level: float = 0.8) -> bool:
        lower, upper = self.forecast.interval(level)
        return bool(lower <= self.actual <= upper)


def _read_training_window(
    store: PointInTimeStore,
    series_id: str,
    observation_dates: list[date],
    upto_index: int,
    as_of: date,
) -> np.ndarray:
    return np.array(
        [
            require_eligible(store, series_id, observation_dates[j], as_of).value
            for j in range(upto_index + 1)
        ]
    )


def backtest_persistence(
    store: PointInTimeStore,
    series_id: str,
    observation_dates: list[date],
    known_at_dates: list[date],
    min_train_periods: int,
    horizons: list[int],
) -> list[ForecastScore]:
    scores: list[ForecastScore] = []
    max_h = max(horizons)
    n = len(observation_dates)
    for origin in range(min_train_periods - 1, n - max_h):
        as_of = known_at_dates[origin]
        history = _read_training_window(store, series_id, observation_dates, origin, as_of)
        forecasts = persistence_forecast(history, horizons)
        for forecast in forecasts:
            target_index = origin + forecast.horizon
            actual = require_eligible(
                store, series_id, observation_dates[target_index], known_at_dates[target_index]
            ).value
            scores.append(ForecastScore(origin, forecast.horizon, forecast, actual))
    return scores


def backtest_autoregressive(
    store: PointInTimeStore,
    series_id: str,
    observation_dates: list[date],
    known_at_dates: list[date],
    order: int,
    min_train_periods: int,
    horizons: list[int],
) -> list[ForecastScore]:
    scores: list[ForecastScore] = []
    max_h = max(horizons)
    n = len(observation_dates)
    for origin in range(min_train_periods - 1, n - max_h):
        as_of = known_at_dates[origin]
        history = _read_training_window(store, series_id, observation_dates, origin, as_of)
        fitted = fit_autoregression(history, order)
        forecasts = fitted.forecast(horizons)
        for forecast in forecasts:
            target_index = origin + forecast.horizon
            actual = require_eligible(
                store, series_id, observation_dates[target_index], known_at_dates[target_index]
            ).value
            scores.append(ForecastScore(origin, forecast.horizon, forecast, actual))
    return scores


def backtest_vector_autoregressive(
    store: PointInTimeStore,
    series_ids: list[str],
    observation_dates: list[date],
    known_at_dates: list[date],
    order: int,
    min_train_periods: int,
    horizons: list[int],
) -> dict[str, list[ForecastScore]]:
    results: dict[str, list[ForecastScore]] = {sid: [] for sid in series_ids}
    max_h = max(horizons)
    n = len(observation_dates)
    for origin in range(min_train_periods - 1, n - max_h):
        as_of = known_at_dates[origin]
        history = np.column_stack(
            [
                _read_training_window(store, sid, observation_dates, origin, as_of)
                for sid in series_ids
            ]
        )
        fitted = fit_vector_autoregression(history, order, series_ids)
        forecasts_by_series = fitted.forecast(horizons)
        for series_id in series_ids:
            for forecast in forecasts_by_series[series_id]:
                target_index = origin + forecast.horizon
                actual = require_eligible(
                    store, series_id, observation_dates[target_index], known_at_dates[target_index]
                ).value
                results[series_id].append(ForecastScore(origin, forecast.horizon, forecast, actual))
    return results


def summarize_scores(
    scores: list[ForecastScore], coverage_level: float = 0.8
) -> dict[int, dict[str, float]]:
    """Groups by horizon: {mae, rmse, mean_crps, coverage_rate}."""
    by_horizon: dict[int, list[ForecastScore]] = {}
    for score in scores:
        by_horizon.setdefault(score.horizon, []).append(score)

    summary: dict[int, dict[str, float]] = {}
    for horizon, group in by_horizon.items():
        absolute_errors = [s.absolute_error for s in group]
        squared_errors = [s.squared_error for s in group]
        crps_values = [s.crps for s in group]
        coverage = [s.covered(coverage_level) for s in group]
        summary[horizon] = {
            "mae": float(np.mean(absolute_errors)),
            "rmse": float(np.sqrt(np.mean(squared_errors))),
            "mean_crps": float(np.mean(crps_values)),
            "coverage_rate": float(np.mean(coverage)),
            "n_origins": float(len(group)),
        }
    return summary


def coverage_confidence_interval(n_trials: int, nominal_level: float) -> tuple[float, float]:
    """A normal-approximation 95% CI for the realized coverage rate of a
    correctly-calibrated model with `n_trials` independent backtest
    scores at the given nominal interval level -- used to judge whether
    an observed `coverage_rate` is statistically consistent with
    calibration, not just eyeballed against the nominal level."""
    if n_trials < 1:
        raise ValueError("n_trials must be a positive integer")
    if not 0.0 < nominal_level < 1.0:
        raise ValueError("nominal_level must be in (0, 1)")
    standard_error = float(np.sqrt(nominal_level * (1 - nominal_level) / n_trials))
    z = float(norm.ppf(0.975))
    return nominal_level - z * standard_error, nominal_level + z * standard_error
