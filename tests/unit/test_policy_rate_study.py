"""PR-200: real-data policy-rule study.

Known-answer tests (a hand-computed Taylor rule, a simulated rule whose coefficients least
squares must recover), a leak test, and one real run of the whole study on the committed
Federal Reserve snapshot (a few seconds) whose qualitative findings are asserted with
generous margins.
"""

from __future__ import annotations

import json
import math
from datetime import date
from pathlib import Path

import numpy as np
import pytest

from prometheus.data_ingestion.kaggle_build import add_months
from prometheus.data_ingestion.kaggle_fed_policy import FedPolicyMonth
from prometheus.orchestration import policy_rate_study as study_module
from prometheus.orchestration.policy_rate_study import (
    FEATURE_NAMES,
    bootstrap_long_run_response,
    build_rows,
    fit_ols,
    long_run_response,
    main,
    ols_predict,
    run_study,
    simulator_taylor_prediction,
    train_neural_rule,
)


def _months(
    n: int, rate: list[float], unemployment: list[float], inflation: list[float]
) -> list[FedPolicyMonth]:
    row = date(1960, 1, 31)
    out = []
    for i in range(n):
        out.append(FedPolicyMonth(row, rate[i], unemployment[i], inflation[i], None))
        row = add_months(row, 1)
    return out


def test_build_rows_explains_each_month_from_the_two_previous_months_only() -> None:
    rate = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0]
    unemployment = [5.0, 5.5, 6.0, 6.5, 7.0, 7.5]
    inflation = [2.0, 2.5, 3.0, 3.5, 4.0, 4.5]
    rows = build_rows(_months(6, rate, unemployment, inflation))
    assert len(rows.months) == 4 and rows.months[0] == date(1960, 3, 31)
    assert rows.features.shape == (4, len(FEATURE_NAMES))
    # month index 2 (rate 3.0) is explained by months 1 and 0:
    assert list(rows.features[0]) == [2.0, 2.5, 5.5, 0.5, 0.5, 1.0]
    assert rows.target[0] == 3.0
    # Changing a LATER month never changes an earlier row's features.
    altered = _months(6, [*rate[:5], 99.0], unemployment, inflation)
    assert np.array_equal(build_rows(altered).features[:3], rows.features[:3])


def test_build_rows_rejects_gaps_and_series_that_are_too_short() -> None:
    months = _months(6, [1.0] * 6, [5.0] * 6, [2.0] * 6)
    del months[3]
    with pytest.raises(ValueError, match="not consecutive"):
        build_rows(months)
    with pytest.raises(ValueError, match="at least three"):
        build_rows(_months(2, [1.0, 1.0], [5.0, 5.0], [2.0, 2.0]))


def test_months_missing_a_variable_are_dropped_before_the_rows_are_built() -> None:
    months = [
        FedPolicyMonth(date(1960, 1, 31), 1.0, 5.0, None, None),
        *_months(5, [1.0] * 5, [5.0] * 5, [2.0] * 5)[1:],
    ]
    assert len(build_rows(months).months) == 2


def test_the_simulators_taylor_baseline_is_evaluated_in_percent_by_hand() -> None:
    features = np.array(
        [
            [3.0, 4.0, 6.0, 0.0, 0.0, 0.0],  # u = u*: no gap -> 3% + 1.5 x (4% - 2%) = 6%
            [3.0, 4.0, 5.0, 0.0, 0.0, 0.0],  # u one point below u*: gap +2% -> +0.5 x 2% = 7%
            [
                3.0,
                20.0,
                6.0,
                0.0,
                0.0,
                0.0,
            ],  # a huge inflation reading is clamped at the 10% maximum
        ]
    )
    assert simulator_taylor_prediction(features, 6.0) == pytest.approx([6.0, 7.0, 10.0])


def _partial_adjustment_data(seed: int, n: int = 600) -> tuple[np.ndarray, np.ndarray]:
    rng = np.random.default_rng(seed)
    rate = np.empty(n)
    inflation = 2.0 + np.cumsum(rng.normal(0, 0.1, n)) * 0.2 + rng.normal(0, 0.5, n)
    unemployment = 6.0 + rng.normal(0, 1.0, n)
    rate[0] = 4.0
    for t in range(1, n):
        rate[t] = (
            0.2
            + 0.9 * rate[t - 1]
            + 0.3 * inflation[t - 1]
            - 0.1 * unemployment[t - 1]
            + rng.normal(0, 0.05)
        )
    features = np.column_stack([rate[:-1], inflation[:-1], unemployment[:-1]])
    return features, rate[1:]


def test_least_squares_recovers_a_known_partial_adjustment_rule() -> None:
    features, target = _partial_adjustment_data(0)
    coefficients = fit_ols(features, target, 3)
    assert coefficients == pytest.approx([0.2, 0.9, 0.3, -0.1], abs=0.06)
    phi_pi, phi_u = long_run_response(coefficients)
    assert phi_pi == pytest.approx(3.0, abs=0.7) and phi_u == pytest.approx(-1.0, abs=0.4)
    assert ols_predict(coefficients, features).shape == target.shape


def test_the_long_run_response_is_undefined_for_a_unit_root_fit() -> None:
    phi_pi, phi_u = long_run_response(np.array([0.0, 1.0, 0.5, 0.5]))
    assert math.isnan(phi_pi) and math.isnan(phi_u)


def test_the_bootstrap_interval_covers_the_true_long_run_response_when_it_is_identified() -> None:
    features, target = _partial_adjustment_data(1)
    low, high, undefined = bootstrap_long_run_response(
        features, target, 12, np.random.default_rng(0), 300
    )
    assert low < 3.0 < high and undefined == 0.0


def test_the_bootstrap_reports_resamples_where_the_response_is_undefined() -> None:
    """With an explosive rate (rho = 1.03) almost every resample has rho >= 1, so there is no
    long-run response to report; a percentile over NaNs would hide that, this reports it."""
    rng = np.random.default_rng(2)
    rate = np.empty(300)
    rate[0] = 1.0
    for t in range(1, 300):
        rate[t] = 1.03 * rate[t - 1] + rng.normal(0, 0.01)
    features = np.column_stack([rate[:-1], rng.normal(2, 1, 299), rng.normal(6, 1, 299)])
    _, _, undefined = bootstrap_long_run_response(
        features, rate[1:], 12, np.random.default_rng(0), 100
    )
    assert undefined > 0.5


def test_the_neural_rule_learns_momentum_in_rate_changes() -> None:
    rng = np.random.default_rng(3)
    n = 900
    change = np.zeros(n)
    for t in range(1, n):
        change[t] = 0.8 * change[t - 1] + rng.normal(0, 0.05)
    rate = 5.0 + np.cumsum(change)
    x = np.column_stack(
        [
            rate[1:-1],
            np.full(n - 2, 2.0),
            np.full(n - 2, 6.0),
            np.zeros(n - 2),
            np.zeros(n - 2),
            np.diff(rate)[:-1],
        ]
    )
    y = rate[2:]
    model = train_neural_rule(
        x[:500], y[:500], x[500:700], y[500:700], seed=0, max_epochs=300, patience=30
    )
    held_out = slice(700, None)
    neural_mse = float(np.mean((model.predict(x[held_out]) - y[held_out]) ** 2))
    persistence_mse = float(np.mean((x[held_out, 0] - y[held_out]) ** 2))
    assert neural_mse < 0.8 * persistence_mse


@pytest.fixture(scope="module")
def study() -> dict:  # type: ignore[type-arg]
    return run_study(seeds=(0, 1, 2, 3, 4), block_resamples=1000)


def test_the_study_uses_the_documented_chronological_split(study) -> None:  # noqa: ANN001
    data = study["data"]
    assert (data["n_train"], data["n_validation"], data["n_test"], data["n_test_pre_zlb"]) == (
        382,
        120,
        206,
        106,
    )
    assert data["first_month"] == "1958-03-31" and data["last_month"] == "2017-02-28"


def test_persistence_is_a_strong_baseline_for_a_smoothed_policy_rate(study) -> None:  # noqa: ANN001
    persistence = study["results"]["persistence"]
    assert (
        0.1 < persistence["test_all"]["rmse"] < 0.3
        and 0.15 < persistence["test_pre_zlb"]["rmse"] < 0.35
    )


def test_the_simulators_default_taylor_rule_does_not_describe_the_real_fed(study) -> None:  # noqa: ANN001
    """The simulator's baseline has no interest-rate smoothing, so on real data it is far
    worse than 'the rate stays where it was' -- a statement about the SIMULATOR's baseline, not
    about Taylor's insight."""
    for window in ("10y", "20y", "all"):
        assert study["results"][f"simulator_taylor@{window}"]["test_pre_zlb"]["rmse"] > 1.0
    comparison = study["comparisons"]["simulator_taylor@all_vs_persistence_pre_zlb"]
    assert comparison["verdict"] == "higher_error_than_persistence"


def test_the_taylor_principle_cannot_be_established_from_1958_1989(study) -> None:  # noqa: ANN001
    full = study["long_run"]["all"]
    assert full["persistence_rho"] > 0.95, "the fitted rule is dominated by interest-rate smoothing"
    low, high = full["long_run_inflation_response_ci"]
    assert low < 1.0 < high, "the interval is too wide to say whether the response exceeds 1"
    assert study["long_run"]["simulator_default_response"] == 1.5


def test_a_neural_rule_with_momentum_beats_persistence_but_not_a_linear_rule_with_the_same_inputs(
    study,  # noqa: ANN001
) -> None:
    results = study["results"]
    assert (
        results["neural_ensemble@all"]["test_pre_zlb"]["rmse"]
        < results["persistence"]["test_pre_zlb"]["rmse"]
    )
    assert (
        results["neural_ensemble@all"]["test_all"]["rmse"]
        < 1.05 * results["persistence"]["test_all"]["rmse"]
    ), "over the whole test period (zero lower bound included) it is a close call"
    versus_persistence = study["comparisons"]["neural_ensemble@all_vs_persistence_pre_zlb"]
    assert versus_persistence["mean_squared_error_difference"] < 0
    versus_linear = study["comparisons"]["neural_ensemble_vs_ols_six_pre_zlb"]
    assert versus_linear["ci_low"] < 0 < versus_linear["ci_high"], (
        "no evidence the gain is non-linear"
    )


def test_more_history_lowers_the_error_of_the_fitted_rules(study) -> None:  # noqa: ANN001
    assert (
        study["comparisons"]["ols_partial_all_vs_10y_pre_zlb"]["mean_squared_error_difference"]
        < -0.1
    )
    assert (
        study["comparisons"]["neural_ensemble_all_vs_10y_pre_zlb"]["mean_squared_error_difference"]
        < 0
    )


def test_the_report_is_json_serialisable_and_states_its_caveats(study) -> None:  # noqa: ANN001
    json.dumps(study)
    assert len(study["caveats"]) == 4


def test_main_writes_the_report_and_rejects_a_bad_seed_count(study, tmp_path: Path) -> None:  # noqa: ANN001
    out = tmp_path / "policy.json"
    assert main(["--seeds", "1", "--output", str(out)], runner=lambda **_: study) == 0
    assert json.loads(out.read_text())["data"]["n_test"] == 206
    with pytest.raises(SystemExit):
        main(["--seeds", "0"])
    assert study_module.DATA_PATH.exists()
