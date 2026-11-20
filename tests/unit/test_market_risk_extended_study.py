"""PR-202: second market, longer test, asymmetric volatility, pooled training.

Unit tests of the study's parts on tiny synthetic markets (no training to convergence), plus
one real run of the whole study on the committed snapshots whose qualitative findings are
asserted with generous margins.
"""

from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from prometheus.orchestration import market_risk_extended_study as study_module
from prometheus.orchestration.market_risk_extended_study import (
    EXTENSION_START,
    MARKET_PATHS,
    extension_scores,
    history_gain,
    main,
    pooled_neural_sigmas,
    run_extended_study,
    verdict,
)
from prometheus.orchestration.market_risk_study import (
    HISTORY_STARTS,
    MarketData,
    Scoreboard,
    prepare_market,
)


def _write_market(path: Path, first: date, last: date, seed: int) -> Path:
    """A random-walk `date,close` file on weekdays."""
    rng = np.random.default_rng(seed)
    rows = ["date,close"]
    price = 100.0
    day = first
    while day <= last:
        if day.weekday() < 5:
            price *= float(np.exp(rng.normal(0.0002, 0.01)))
            rows.append(f"{day.isoformat()},{price:.6f}")
        day += timedelta(days=1)
    path.write_text("\n".join(rows) + "\n")
    return path


@pytest.fixture(scope="module")
def synthetic(tmp_path_factory: pytest.TempPathFactory) -> dict[str, MarketData]:
    root = tmp_path_factory.mktemp("markets")
    return {
        "a": prepare_market(
            _write_market(root / "a.csv", date(1985, 1, 1), date(2021, 6, 30), 1), "a"
        ),
        "b": prepare_market(
            _write_market(root / "b.csv", date(1992, 6, 1), date(2022, 3, 31), 2), "b"
        ),
    }


# ------------------------------------------------------------------ the decision rule


@pytest.mark.parametrize(
    ("low", "high", "predicted_negative", "expected"),
    [
        (-0.5, -0.1, True, "SUPPORTED"),
        (0.1, 0.5, True, "CONTRADICTED"),
        (-0.2, 0.3, True, "INCONCLUSIVE"),
        (0.1, 0.5, False, "SUPPORTED"),
        (-0.5, -0.1, False, "CONTRADICTED"),
        (-0.2, 0.3, False, "INCONCLUSIVE"),
        (0.0, 0.4, True, "INCONCLUSIVE"),
        (-0.4, 0.0, True, "INCONCLUSIVE"),
    ],
)
def test_the_preregistered_decision_rule(
    low: float, high: float, predicted_negative: bool, expected: str
) -> None:
    assert verdict(low, high, predicted_negative=predicted_negative) == expected


# ------------------------------------------------------------------ the parts


def test_prepare_market_cuts_chronologically_with_no_overlap(
    synthetic: dict[str, MarketData],
) -> None:
    data = synthetic["a"]
    masks = (data.train_mask, data.validation_mask, data.test_mask)
    assert sum(int(m.sum()) for m in masks) == len(data.returns), "every day is in one split"
    assert not (masks[0] & masks[1]).any() and not (masks[1] & masks[2]).any()
    first_test = next(d for d, m in zip(data.return_dates, data.test_mask, strict=True) if m)
    last_train = max(d for d, m in zip(data.return_dates, data.train_mask, strict=True) if m)
    assert last_train < date(2000, 1, 1) <= first_test or last_train < first_test
    assert first_test >= date(2008, 1, 1) and last_train < date(2000, 1, 1)
    assert np.isnan(data.features[:66]).all() and not np.isnan(data.features[66:]).any()


def test_pooled_training_uses_every_market_and_only_pre_2000_rows(
    synthetic: dict[str, MarketData], monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: dict[str, Any] = {}

    class Recorder:
        def sigma(self, x: np.ndarray) -> np.ndarray:
            return np.full(len(x), 0.01)

    def fake_train(
        train_x: np.ndarray, train_r: np.ndarray, val_x: np.ndarray, val_r: np.ndarray, **_: Any
    ) -> Recorder:
        seen["shapes"] = (len(train_x), len(train_r), len(val_x), len(val_r))
        return Recorder()

    monkeypatch.setattr(study_module, "train_neural_volatility", fake_train)
    out = pooled_neural_sigmas(synthetic, seeds=(0, 1), max_epochs=1, patience=1)
    expected_train = sum(
        int((d.train_mask & ~np.isnan(d.features[:, 0])).sum()) for d in synthetic.values()
    )
    expected_validation = sum(
        int((d.validation_mask & ~np.isnan(d.features[:, 0])).sum()) for d in synthetic.values()
    )
    assert seen["shapes"] == (
        expected_train,
        expected_train,
        expected_validation,
        expected_validation,
    )
    for name, data in synthetic.items():
        assert len(out[name]) == 2, "one forecast per seed"
        assert all(len(s) == int(data.test_mask.sum()) for s in out[name])


def test_pooled_training_really_trains_and_forecasts_positive_volatility(
    synthetic: dict[str, MarketData],
) -> None:
    out = pooled_neural_sigmas(synthetic, seeds=(0,), max_epochs=5, patience=3)
    for sigmas in out.values():
        assert np.all(np.isfinite(sigmas[0])) and np.all(sigmas[0] > 0)


def test_the_extension_report_counts_only_days_after_the_join(
    synthetic: dict[str, MarketData],
) -> None:
    data = synthetic["a"]
    board = Scoreboard(data)
    n_test = int(data.test_mask.sum())
    sigma = np.full(n_test, 0.01)
    threshold = {0.99: np.full(n_test, -0.02), 0.975: np.full(n_test, -0.015)}
    board.record("flat", sigma, threshold)
    report = extension_scores(data, board)
    test_dates = [d for d, m in zip(data.return_dates, data.test_mask, strict=True) if m]
    in_extension = np.array([d >= EXTENSION_START for d in test_dates])
    returns = data.test_returns[in_extension]
    assert report["n_days"] == int(in_extension.sum()) > 0
    assert report["first_date"] >= EXTENSION_START.isoformat()
    row = report["models"]["flat"]
    assert row["exceedances_0.99"] == float(np.sum(returns < -0.02))
    assert row["exceedances_0.975"] == float(np.sum(returns < -0.015))
    assert row["qlike_mean"] == pytest.approx(float(np.mean(np.log(0.0001) + returns**2 / 0.0001)))


def test_history_gain_is_positive_when_more_history_lowers_the_loss(
    synthetic: dict[str, MarketData],
) -> None:
    board = Scoreboard(synthetic["a"])
    board.volatility["m@10y"] = {"qlike_mean": -5.0}
    board.volatility["m@all"] = {"qlike_mean": -5.5}
    assert history_gain(board, "m") == pytest.approx(0.5)


def test_every_history_window_is_one_the_study_documents() -> None:
    assert set(HISTORY_STARTS) == {"10y", "30y", "all"}
    assert study_module.POOLED_WINDOW in HISTORY_STARTS
    assert EXTENSION_START == date(2020, 11, 5)


# ------------------------------------------------------------------ the splice reproduces PR-199


def test_the_spliced_series_reproduces_pr199_on_pr199s_own_days() -> None:
    """Extending the data must not change a single earlier number: same returns, same
    training window, hence the same fit and -- the filter being causal -- the same
    volatility forecast on every day PR-199 already scored."""
    from prometheus.titan.garch_family import fit_garch_family

    old = prepare_market(MARKET_PATHS["sp500_extended"].with_name("kaggle_sp500_daily_close.csv"))
    new = prepare_market(MARKET_PATHS["sp500_extended"], "sp500_extended")
    n_old = len(old.returns)
    assert len(new.returns) > n_old
    assert np.array_equal(new.returns[:n_old], old.returns)
    assert new.return_dates[:n_old] == old.return_dates
    assert np.array_equal(new.features[:n_old], old.features, equal_nan=True)
    assert np.array_equal(new.returns[new.train_mask], old.returns[old.train_mask])
    fit_old = fit_garch_family(old.returns[old.train_mask], asymmetric=True)
    fit_new = fit_garch_family(new.returns[new.train_mask], asymmetric=True)
    assert fit_old == fit_new
    sigma_old = np.sqrt(fit_old.conditional_variances(old.returns))[old.test_mask]
    sigma_new = np.sqrt(fit_new.conditional_variances(new.returns))[new.test_mask]
    assert np.array_equal(sigma_new[: sigma_old.size], sigma_old)


def test_the_committed_market_snapshots_have_the_documented_shape() -> None:
    sp = prepare_market(MARKET_PATHS["sp500_extended"])
    nasdaq = prepare_market(MARKET_PATHS["nasdaq"])
    assert len(sp.returns) == 23_948 and sp.return_dates[-1] == date(2023, 5, 3)
    assert len(nasdaq.returns) == 10_874 and nasdaq.return_dates[0] == date(1980, 3, 19)
    assert int(sp.test_mask.sum()) == int(nasdaq.test_mask.sum()) == 3_861
    assert [d for d, m in zip(sp.return_dates, sp.test_mask, strict=True) if m] == [
        d for d, m in zip(nasdaq.return_dates, nasdaq.test_mask, strict=True) if m
    ], "both markets are scored on exactly the same days"


# ------------------------------------------------------------------ one real run of the study


@pytest.fixture(scope="module")
def study() -> dict[str, Any]:
    return run_extended_study()


def test_the_pre_registration_is_in_the_module_docstring() -> None:
    doc = study_module.__doc__ or ""
    for question in ("Q-A", "Q-B", "Q-C", "Q-D", "Q-E"):
        assert question in doc
    assert "written down BEFORE" in doc and "Decision rule" in doc


def test_both_markets_are_scored_on_identical_test_days(study: dict[str, Any]) -> None:
    for market in study["markets"].values():
        data = market["data"]
        assert data["n_test"] == 3_861
        assert data["test_first_date"] == "2008-01-02" and data["test_last_date"] == "2023-05-03"
        assert market["extension"]["n_days"] == 626
        assert market["extension"]["first_date"] == "2020-11-05"


def test_q_a_leverage_asymmetry_lowers_qlike_on_both_markets(study: dict[str, Any]) -> None:
    for name, market in study["markets"].items():
        comparison = market["comparisons"]["Q-A"]
        assert comparison["preregistered_verdict"] == "SUPPORTED", name
        assert comparison["ci_high"] < 0
        assert market["garch_family_parameters"]["gjr@all"]["gamma"] > 0.04, (
            "bad news must raise next-day variance by more than good news"
        )


def test_q_a_also_holds_on_the_days_that_did_not_exist_when_pr199_was_written(
    study: dict[str, Any],
) -> None:
    sp = study["markets"]["sp500_extended"]["comparisons"]["Q-A_extension"]
    assert sp["n_days"] == 626 and sp["preregistered_verdict"] == "SUPPORTED"
    nasdaq = study["markets"]["nasdaq"]["comparisons"]["Q-A_extension"]
    assert nasdaq["qlike_difference_first_minus_second"] < 0, "same sign; too few days to be sure"


def test_q_b_the_looser_persistence_cap_did_not_help_out_of_sample(study: dict[str, Any]) -> None:
    """The pre-registered prediction (a higher cap lowers the loss) is CONTRADICTED on both
    markets: the likelihood prefers near-integrated volatility, the forecast does not."""
    for market in study["markets"].values():
        assert market["comparisons"]["Q-B"]["qlike_difference_first_minus_second"] > 0
    assert study["markets"]["sp500_extended"]["garch_family_parameters"]["garch_free@all"][
        "persistence"
    ] == pytest.approx(0.999, abs=1e-6), "on 70 years of S&P returns the free fit sits ON the cap"


def test_q_c_no_var_model_passes_conditional_coverage_over_the_longer_window(
    study: dict[str, Any],
) -> None:
    for market, outcome in study["hypotheses"]["Q-C"].items():
        assert outcome["verdict"] == "CONTRADICTED", market
        assert outcome["models_passing_at_99"] == {} and outcome["models_passing_at_97.5"] == {}
        closest = outcome["closest_at_99"]
        assert closest["conditional_coverage_p"] < 0.05
        assert closest["n_exceedances"] > 1.2 * closest["expected_exceedances"]
        assert "fhs" in closest["model"], "filtered historical simulation is the closest family"


def test_q_d_the_neural_model_still_loses_to_garch_and_gains_more_from_history_on_the_sp500(
    study: dict[str, Any],
) -> None:
    for name, market in study["markets"].items():
        assert market["comparisons"]["Q-D(i)"]["qlike_difference_first_minus_second"] > 0, name
    sp = study["hypotheses"]["Q-D"]["sp500_extended"]
    assert sp["neural_gains_more"] is True
    assert sp["neural_gain_from_history"] > 0.05 > sp["garch_gain_from_history"]


def test_q_e_pooling_both_markets_lowers_the_neural_loss_on_each(study: dict[str, Any]) -> None:
    for name, market in study["markets"].items():
        assert market["comparisons"]["Q-E"]["qlike_difference_first_minus_second"] < 0, name


def test_exploratory_comparisons_are_labelled_and_carry_no_verdict(study: dict[str, Any]) -> None:
    for market in study["markets"].values():
        for label in ("X-1_gjr_vs_pr199_garch", "X-2_pooled_neural_vs_pr199_garch"):
            row = market["comparisons"][label]
            assert row["status"].startswith("EXPLORATORY")
            assert "preregistered_verdict" not in row and "prediction" not in row
        assert (
            market["comparisons"]["X-1_gjr_vs_pr199_garch"]["qlike_difference_first_minus_second"]
            < 0
        ), "the asymmetric model beats the GARCH of PR-199"


def test_the_gjr_model_has_the_lowest_whole_window_qlike_among_the_all_history_models(
    study: dict[str, Any],
) -> None:
    for name, market in study["markets"].items():
        qlike = {k: v["qlike_mean"] for k, v in market["volatility"].items() if k.endswith("@all")}
        best = sorted(qlike, key=lambda k: qlike[k])[:3]
        assert any(k.startswith("gjr") for k in best[:2]), (name, best)


def test_every_extension_score_is_finite(study: dict[str, Any]) -> None:
    for market in study["markets"].values():
        for row in market["extension"]["models"].values():
            assert all(np.isfinite(v) for v in row.values())


def test_the_report_is_json_serialisable_and_states_its_caveats(study: dict[str, Any]) -> None:
    json.dumps(study)
    assert len(study["caveats"]) == 6
    assert set(study["hypotheses"]) == {"Q-A", "Q-B", "Q-C", "Q-D", "Q-E"}


def test_main_writes_the_report_and_rejects_a_bad_seed_count(
    study: dict[str, Any], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(study_module, "run_extended_study", lambda **_: study)
    out = tmp_path / "extended.json"
    assert main(["--seeds", "1", "--output", str(out)]) == 0
    assert json.loads(out.read_text())["config"]["pooled_window"] == "all"
    with pytest.raises(SystemExit):
        main(["--seeds", "0"])
