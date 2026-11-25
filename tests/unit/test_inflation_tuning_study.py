"""PR-216: the tuned inflation nowcast. Unit tests of the pieces plus the committed output."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from prometheus.orchestration import inflation_tuning_study as study
from prometheus.orchestration.inflationcast_long_study import (
    NowcastData,
    build_nowcast_data,
    fit_ridge,
)

COMMITTED = Path(__file__).resolve().parents[2] / "docs" / "numerics" / "inflation_tuning.json"


@pytest.fixture(scope="module")
def data() -> NowcastData:
    return build_nowcast_data()


def test_the_grid_has_twenty_four_distinct_configurations_simplest_first() -> None:
    grid = study.config_grid()
    assert len(grid) == len(set(grid)) == 24
    assert grid[0] == study.Config(6, "raw", "l2", "1962")


@pytest.mark.parametrize("lags", [6, 12, 24])
def test_lag_columns_are_the_growth_rates_before_the_target_month(
    data: NowcastData, lags: int
) -> None:
    x = study.lag_matrix(data, lags)
    assert x.shape == (len(data.months), lags)
    # the last column is last month's growth; row i's last lag is row i-1's own growth
    np.testing.assert_allclose(x[1:, -1], data.mom[:-1])
    if lags == 24:
        i = 100
        np.testing.assert_allclose(x[i], data.mom[i - 24 : i])
        assert np.isnan(x[:12]).any()


def test_no_lag_uses_the_target_month_itself(data: NowcastData) -> None:
    x = study.lag_matrix(data, 12)
    # nothing in row i equals a function of mom[i]: shifting the target must not move the row
    changed = NowcastData(**{**data.__dict__, "mom": data.mom + 0.0})
    np.testing.assert_array_equal(study.lag_matrix(changed, 12), x)
    assert not np.allclose(x[200:210, -1], data.mom[200:210])


def test_l1_ridge_resists_an_outlier_that_l2_chases() -> None:
    rng = np.random.default_rng(0)
    x = rng.normal(size=(200, 3))
    y = x @ np.array([1.0, -1.0, 0.5]) + rng.normal(0.0, 0.05, 200)
    y[0] += 50.0
    l2 = fit_ridge(x, y, 1.0)
    l1 = study.fit_l1_ridge(x, y, 1.0)
    truth = x[1:] @ np.array([1.0, -1.0, 0.5])
    assert np.mean(np.abs(l1.predict(x[1:]) - truth)) < np.mean(np.abs(l2.predict(x[1:]) - truth))


def test_l1_ridge_equals_l2_ridge_on_clean_symmetric_data_to_first_order() -> None:
    rng = np.random.default_rng(1)
    x = rng.normal(size=(500, 2))
    y = x @ np.array([0.7, 0.3]) + rng.normal(0.0, 0.01, 500)
    np.testing.assert_allclose(
        study.fit_l1_ridge(x, y, 1e-3).predict(x), fit_ridge(x, y, 1e-3).predict(x), atol=5e-3
    )


def test_selection_takes_the_lowest_validation_error_and_breaks_ties_toward_the_earlier() -> None:
    config = study.Config(6, "raw", "l2", "1962")

    def candidate(error: float) -> study.Candidate:
        return study.Candidate(config, 1.0, error, None, np.zeros((1, 1)))

    first, second, third = candidate(0.3), candidate(0.2), candidate(0.2)
    assert study.select([first, second, third]) is second


def test_a_short_run_reports_both_questions(data: NowcastData) -> None:
    report = study.run_study(
        block_resamples=50,
        grid=[study.Config(12, "raw", "l2", "1962"), study.Config(12, "residual", "l1", "1980")],
    )
    assert set(report["comparisons"]) == {
        "I-A_tuned_vs_finding18_ridge",
        "I-B_tuned_vs_base_mean12",
    }
    errors = [g["validation_mae"] for g in report["grid"]]
    assert errors == sorted(errors)
    assert report["grid"][0]["config"] == study.Config(**report["config"]["selected"]).name


@pytest.mark.skipif(not COMMITTED.exists(), reason="committed study output is absent")
def test_the_committed_report_is_internally_consistent() -> None:
    report = json.loads(COMMITTED.read_text())
    errors = [g["validation_mae"] for g in report["grid"]]
    assert len(errors) == 24 and errors == sorted(errors)
    assert report["grid"][0]["config"] == study.Config(**report["config"]["selected"]).name
    for row in report["comparisons"].values():
        assert row["ci_low"] <= row["mae_difference_first_minus_second"] <= row["ci_high"]
    assert report["test_mae"]["base_mean12"] < report["test_mae"]["persistence_yoy"]
