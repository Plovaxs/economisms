"""The market-forecast study: no lookahead, the written verdict rule, a small end-to-end run."""

from __future__ import annotations

from datetime import date, timedelta

import numpy as np
import pytest

from prometheus.orchestration import market_forecast_study as mfs


def _series(n: int = 9500, seed: int = 0) -> tuple[list[date], np.ndarray]:
    rng = np.random.default_rng(seed)
    dates = [date(1990, 1, 1) + timedelta(days=i) for i in range(n + 1)]
    closes = 100.0 * np.exp(np.cumsum(np.concatenate([[0.0], rng.normal(0.0003, 0.01, n)])))
    return dates, closes


def test_verdict_follows_the_written_rule() -> None:
    assert mfs.verdict(0.1, 0.5) == "SUPPORTED"
    assert mfs.verdict(-0.5, -0.1) == "CONTRADICTED"
    assert mfs.verdict(-0.1, 0.2) == "INCONCLUSIVE"


def test_features_and_the_benchmark_never_use_the_day_they_forecast() -> None:
    rng = np.random.default_rng(1)
    returns = rng.normal(0.0, 0.01, 600)
    changed = returns.copy()
    changed[400] += 5.0  # change day 400 only
    original = mfs.build_features(returns)
    after = mfs.build_features(changed)
    assert np.array_equal(original[:401], after[:401], equal_nan=True)  # days up to 400 unaffected
    assert not np.array_equal(original[401], after[401])
    benchmark = mfs.expanding_mean(returns)
    assert np.isnan(benchmark[0]) and benchmark[400] == pytest.approx(returns[:400].mean())
    assert mfs.expanding_mean(changed)[400] == benchmark[400]


def test_transaction_costs_are_charged_on_turnover_only() -> None:
    simple = np.array([0.01, 0.01, 0.01])
    flat = mfs._strategy_returns(np.ones(3), simple)
    assert np.allclose(flat, simple)  # constant weight: no turnover
    switching = mfs._strategy_returns(np.array([1.0, 0.0, 1.0]), simple)
    assert switching[1] == pytest.approx(-mfs.COST_PER_UNIT_TURNOVER)
    assert switching[2] == pytest.approx(0.01 - mfs.COST_PER_UNIT_TURNOVER)


def test_end_to_end_run_on_a_random_walk_finds_no_forecastability() -> None:
    dates, closes = _series()
    report = mfs.run_study(dates, closes, n_mlp_seeds=1, max_epochs=40, n_resamples=200)
    assert set(report["forecast_accuracy"]) == set(mfs.MODEL_NAMES)
    assert report["data"]["n_test"] > 0 and report["data"]["n_train"] > 0
    # i.i.d. returns carry nothing to forecast: no model should be wholly better than the mean
    assert report["hypotheses"]["M-A_any_forecast_beats_historical_mean"] != "SUPPORTED"
    assert report["hypotheses"]["M-D_any_forecast_timing_beats_buy_and_hold"] != "SUPPORTED"
    managed = report["volatility_managed"]["cap_1"]
    assert 0.0 < managed["mean_weight"] <= 1.0
    for row in report["forecast_accuracy"].values():
        assert row["squared_error_gain"]["low"] <= row["squared_error_gain"]["high"]


def test_the_run_is_deterministic() -> None:
    dates, closes = _series(9000)
    first = mfs.run_study(dates, closes, n_mlp_seeds=1, max_epochs=20, n_resamples=100)
    second = mfs.run_study(dates, closes, n_mlp_seeds=1, max_epochs=20, n_resamples=100)
    assert first == second
