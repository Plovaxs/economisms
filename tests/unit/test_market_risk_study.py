"""PR-199: real-return evaluation of the market-risk models.

Known-answer tests for the statistics, leak tests for every forecaster (changing a FUTURE
return must never change an earlier forecast), a synthetic check that a correctly specified
model is NOT rejected, and one real run of the whole study on the committed S&P 500 data
(about 25 seconds) whose qualitative findings are asserted with generous margins.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np
import pytest
from scipy import stats

from prometheus.orchestration import market_risk_study as study_module
from prometheus.orchestration.market_risk_study import (
    LOOKBACK,
    N_FEATURES,
    backtest_var,
    christoffersen_independence,
    ewma_sigma,
    kupiec_pof,
    main,
    qlike,
    rolling_historical_thresholds,
    run_study,
    trailing_features,
    train_neural_volatility,
)
from prometheus.titan.risk_metrics import var_exception_coverage_test

# ------------------------------------------------------------------------------ statistics


def test_kupiec_matches_the_textbook_likelihood_ratio() -> None:
    n, x, p = 250, 7, 0.01
    observed = x / n
    expected_lr = -2 * (
        (n - x) * math.log(1 - p)
        + x * math.log(p)
        - ((n - x) * math.log(1 - observed) + x * math.log(observed))
    )
    lr, p_value = kupiec_pof(x, n, p)
    assert lr == pytest.approx(expected_lr)
    assert p_value == pytest.approx(stats.chi2.sf(expected_lr, 1))
    assert p_value < 0.05, "7 exceedances in 250 days at 99% is too many"


def test_kupiec_is_zero_when_the_exceedance_rate_equals_the_nominal_rate() -> None:
    lr, p_value = kupiec_pof(10, 1000, 0.01)
    assert lr == pytest.approx(0.0, abs=1e-9) and p_value == pytest.approx(1.0)


def test_kupiec_handles_zero_exceedances_without_a_log_of_zero() -> None:
    lr, _ = kupiec_pof(0, 500, 0.01)
    assert lr == pytest.approx(-2 * 500 * math.log(0.99))


def test_kupiec_rejects_impossible_inputs() -> None:
    for bad in ((5, 4, 0.01), (1, 10, 0.0), (1, 10, 1.0), (0, 0, 0.5)):
        with pytest.raises(ValueError):
            kupiec_pof(*bad)


def test_kupiec_agrees_with_the_repositorys_exact_binomial_coverage_test() -> None:
    """RISK-08's exact two-sided binomial test and Kupiec's asymptotic likelihood ratio test
    the same null; on a realistic sample size they must tell the same story."""
    rng = np.random.default_rng(7)
    losses = rng.standard_normal(3235)
    threshold = float(stats.norm.ppf(0.99))  # a correctly calibrated 99% VaR for N(0, 1) losses
    exact = var_exception_coverage_test(losses, threshold, 0.99)
    _, kupiec_p = kupiec_pof(exact.n_exceptions, exact.n_observations, 0.01)
    # Different definitions of a two-sided p-value (a likelihood ratio versus summing exact
    # binomial tails), so the values differ by a few hundredths; the decisions do not.
    assert kupiec_p > 0.05 and exact.p_value > 0.05
    assert abs(kupiec_p - exact.p_value) < 0.1
    # ...and on a clearly mis-calibrated threshold both reject decisively.
    biased = var_exception_coverage_test(losses, 1.5, 0.99)
    assert biased.p_value < 1e-6
    assert kupiec_pof(biased.n_exceptions, biased.n_observations, 0.01)[1] < 1e-6


def test_the_pinball_loss_is_lowest_at_the_true_conditional_quantile() -> None:
    returns, sigma = _garch_path(0)
    z = stats.norm.ppf(0.01)
    losses = {
        scale: backtest_var(returns, z * sigma * scale, 0.99)["pinball_loss_bp"]
        for scale in (0.6, 1.0, 1.6)
    }
    assert losses[1.0] < losses[0.6] and losses[1.0] < losses[1.6]


def test_christoffersen_separates_clustered_from_scattered_exceedances() -> None:
    scattered = np.zeros(200, dtype=int)
    scattered[[20, 60, 100, 140, 180]] = 1
    clustered = np.zeros(200, dtype=int)
    clustered[100:105] = 1
    _, p_scattered = christoffersen_independence(scattered)
    _, p_clustered = christoffersen_independence(clustered)
    assert p_scattered > 0.5 and p_clustered < 0.05


def test_christoffersen_has_no_information_without_exceedances_or_with_only_exceedances() -> None:
    assert christoffersen_independence(np.zeros(50, dtype=int)) == (0.0, 1.0)
    assert christoffersen_independence(np.ones(50, dtype=int)) == (0.0, 1.0)


def _garch_path(seed: int, n: int = 30_000) -> tuple[np.ndarray, np.ndarray]:
    rng = np.random.default_rng(seed)
    h = 1e-6 / (1 - 0.08 - 0.90)
    returns, sigma = np.empty(n), np.empty(n)
    for t in range(n):
        sigma[t] = math.sqrt(h)
        returns[t] = sigma[t] * rng.standard_normal()
        h = 1e-6 + 0.08 * returns[t] ** 2 + 0.90 * h
    return returns, sigma


@pytest.mark.parametrize("seed", [0, 2])
def test_a_correctly_specified_model_is_not_rejected_by_the_backtests(seed: int) -> None:
    """The known-answer check that the machinery does not manufacture rejections: with the
    TRUE conditional volatility of a simulated GARCH process, both coverage tests pass at
    both levels (seeds fixed; other seeds can fail by chance -- these are 5% tests)."""
    returns, sigma = _garch_path(seed)
    for alpha in (0.99, 0.975):
        result = backtest_var(returns, stats.norm.ppf(1 - alpha) * sigma, alpha)
        assert result["kupiec_p"] > 0.05 and result["christoffersen_independence_p"] > 0.05
        assert result["conditional_coverage_p"] > 0.05


def test_a_constant_volatility_model_is_rejected_on_volatility_clustered_data() -> None:
    returns, _ = _garch_path(0)
    constant = np.full(len(returns), returns.std())
    result = backtest_var(returns, stats.norm.ppf(0.01) * constant, 0.99)
    assert result["christoffersen_independence_p"] < 0.01


def test_qlike_is_minimised_at_the_true_volatility_on_average() -> None:
    returns, sigma = _garch_path(0)
    assert qlike(returns, sigma).mean() < qlike(returns, sigma * 1.5).mean()
    assert qlike(returns, sigma).mean() < qlike(returns, sigma * 0.6).mean()


# ------------------------------------------------------------------------------ no look-ahead


def test_rolling_historical_thresholds_use_only_returns_before_the_day() -> None:
    rng = np.random.default_rng(1)
    returns = rng.standard_normal(400) * 0.01
    base = rolling_historical_thresholds(returns, 250, 0.99)
    assert np.isnan(base[:250]).all() and not np.isnan(base[250:]).any()
    altered = returns.copy()
    altered[300:] = 5.0  # a huge FUTURE shock
    after = rolling_historical_thresholds(altered, 250, 0.99)
    assert np.array_equal(base[:301], after[:301], equal_nan=True), (
        "the shock at 300 first matters at 301"
    )
    expected = -np.quantile(-returns[0:250], 0.99)
    assert base[250] == pytest.approx(expected)


def test_ewma_sigma_follows_its_recursion_and_uses_only_the_past() -> None:
    returns = np.array([0.01, -0.02, 0.03, 0.0])
    sigma = ewma_sigma(returns, 0.94, 1e-4)
    assert sigma[0] == pytest.approx(0.01)
    assert sigma[1] ** 2 == pytest.approx(0.94 * 1e-4 + 0.06 * 0.01**2)
    altered = returns.copy()
    altered[2:] = 9.0
    assert np.array_equal(sigma[:3], ewma_sigma(altered, 0.94, 1e-4)[:3])


def test_trailing_features_are_hand_checkable_and_use_only_the_past() -> None:
    rng = np.random.default_rng(2)
    returns = rng.standard_normal(200) * 0.01
    features = trailing_features(returns)
    assert features.shape == (200, N_FEATURES) and np.isnan(features[:LOOKBACK]).all()
    t = 120
    assert features[t, 0] == returns[t - 1] and features[t, 1] == abs(returns[t - 1])
    assert features[t, 2] == pytest.approx(np.abs(returns[t - 5 : t]).mean())
    assert features[t, 3] == pytest.approx(np.abs(returns[t - 22 : t]).mean())
    assert features[t, 4] == pytest.approx(np.abs(returns[t - 66 : t]).mean())
    assert features[t, 5] == min(returns[t - 1], 0.0)
    altered = returns.copy()
    altered[t:] = 3.0
    assert np.array_equal(features[: t + 1], trailing_features(altered)[: t + 1], equal_nan=True)


def test_the_neural_volatility_model_learns_a_clustered_process() -> None:
    returns, sigma = _garch_path(3, n=6000)
    features = trailing_features(returns)
    train = np.arange(LOOKBACK, 4000)
    validation = np.arange(4000, 5000)
    model = train_neural_volatility(
        features[train],
        returns[train],
        features[validation],
        returns[validation],
        seed=0,
        max_epochs=300,
        patience=30,
    )
    test = np.arange(5000, 6000)
    predicted = model.sigma(features[test])
    assert np.corrcoef(predicted, sigma[test])[0, 1] > 0.6
    constant_loss = qlike(returns[test], np.full(1000, returns[train].std())).mean()
    assert qlike(returns[test], predicted).mean() < constant_loss


# ------------------------------------------------------------------------------ the real study


@pytest.fixture(scope="module")
def study() -> dict:  # type: ignore[type-arg]
    return run_study(seeds=(0, 1, 2, 3, 4), block_resamples=1000)


def test_the_study_scores_models_on_the_documented_chronological_split(study) -> None:  # noqa: ANN001
    data = study["data"]
    assert (data["n_train"], data["n_validation"], data["n_test"]) == (18_077, 2_010, 3_235)
    assert data["n_returns"] == data["n_train"] + data["n_validation"] + data["n_test"]
    assert data["test_first_date"] == "2008-01-02" and data["test_last_date"] == "2020-11-04"
    assert data["test_worst_day_pct"] == pytest.approx(-12.77, abs=0.05)
    assert data["train_excess_kurtosis"] > 15


def test_no_var_model_passes_conditional_coverage_over_the_two_crises(study) -> None:  # noqa: ANN001
    """The honest headline: 2008 and 2020 break every model, at both levels."""
    for name, result in study["backtests"].items():
        for alpha in ("alpha_0.99", "alpha_0.975"):
            assert result[alpha]["conditional_coverage_p"] < 0.05, (name, alpha)


def test_normal_quantile_models_badly_underestimate_the_tail_at_99_percent(study) -> None:  # noqa: ANN001
    for name, result in study["backtests"].items():
        if "normal" in name:
            assert result["alpha_0.99"]["exceedance_rate"] > 0.02, name


def test_filtered_historical_simulation_with_full_history_is_among_the_closest_to_nominal(
    study,  # noqa: ANN001
) -> None:
    hits = {n: r["alpha_0.99"]["n_exceedances"] for n, r in study["backtests"].items()}
    assert hits["garch_fhs@all"] < hits["historical_250"]
    assert "garch_fhs@all" in sorted(hits, key=lambda name: hits[name])[:3]


def test_the_consistent_quantile_loss_agrees_that_filtered_garch_is_among_the_best_var_models(
    study,  # noqa: ANN001
) -> None:
    """RISK-09's pinball loss is the strictly consistent score for a quantile forecast, so it
    ranks VaR models without relying on exceedance counts alone. Margins are deliberately
    loose (within 5% of the best), because the ranking of the top few is a close call."""
    for alpha in ("alpha_0.99", "alpha_0.975"):
        scores = {n: r[alpha]["pinball_loss_bp"] for n, r in study["backtests"].items()}
        assert scores["garch_fhs@all"] <= 1.05 * min(scores.values()), alpha
        assert scores["garch_fhs@all"] < scores["historical_250"]
        assert scores["garch_fhs@all"] < scores["constant_normal@all"]


def test_garch_beats_the_neural_volatility_model_and_both_beat_a_constant(study) -> None:  # noqa: ANN001
    q = study["volatility"]
    assert q["garch_normal@all"]["qlike_mean"] < q["neural_ensemble@all"]["qlike_mean"]
    assert q["neural_ensemble@all"]["qlike_mean"] < q["constant_normal@all"]["qlike_mean"] - 0.5
    assert (
        study["comparisons"]["neural_ensemble_vs_garch_all"]["qlike_difference_first_minus_second"]
        > 0
    )


def test_more_history_helps_the_neural_model_a_lot_and_garch_a_little(study) -> None:  # noqa: ANN001
    q = study["volatility"]
    assert q["neural_ensemble@all"]["qlike_mean"] < q["neural_ensemble@10y"]["qlike_mean"] - 0.05
    assert q["garch_normal@all"]["qlike_mean"] < q["garch_normal@10y"]["qlike_mean"]
    comparison = study["comparisons"]["neural_ensemble_all_vs_10y"]
    assert comparison["qlike_difference_first_minus_second"] < -0.05


def test_the_report_is_json_serialisable_and_states_its_caveats(study) -> None:  # noqa: ANN001
    json.dumps(study)
    assert len(study["caveats"]) == 4 and "0.98" in study["caveats"][2]


def test_main_writes_the_report_and_rejects_a_bad_seed_count(
    study,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,  # noqa: ANN001
) -> None:
    monkeypatch.setattr(study_module, "run_study", lambda **_: study)
    out = tmp_path / "risk.json"
    assert main(["--seeds", "1", "--output", str(out)]) == 0
    assert json.loads(out.read_text())["data"]["n_test"] == 3_235
    with pytest.raises(SystemExit):
        main(["--seeds", "0"])
