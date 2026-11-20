"""PR-203: the long-history inflation nowcast and the base-effect arithmetic.

Known-answer tests of the arithmetic (a constant-growth economy is nowcast exactly; a base
effect is invisible to persistence and visible to a rule that forecasts the monthly growth),
leak tests (a month's features use only what is known at the end of that month), a known-answer
ridge, and one real run whose qualitative findings are asserted with generous margins.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from prometheus.orchestration import inflationcast_long_study as study_module
from prometheus.orchestration.inflationcast_long_study import (
    CPI_PATH,
    MACRO_PATH,
    NowcastData,
    base_effect_forecast,
    build_nowcast_data,
    feature_matrix,
    fit_ridge,
    main,
    run_study,
    train_mom_network,
    verdict,
    yoy_from_mom,
)


@pytest.fixture(scope="module")
def real() -> NowcastData:
    return build_nowcast_data()


def _write_cpi(
    path: Path, levels: list[float], first_measured: tuple[int, int] = (1990, 1)
) -> Path:
    """A `kaggle_cpi_index_monthly`-shaped file: row r holds the level of month r - 1."""
    rows = ["date,CPI_INDEX_SA"]
    year, month = first_measured
    for level in levels:
        month += 1
        if month == 13:
            year, month = year + 1, 1
        rows.append(f"{year}{month:02d},{level}")
    path.write_text("\n".join(rows) + "\n")
    return path


def _write_macro(path: Path, first: tuple[int, int], n: int) -> Path:
    header = "date,GDP_YOY,CLAIMS_YOY,FEDFUNDS,UNRATE,CPI_YOY_SA,BANK_CREDIT_YOY,SPX_YOY,SPX_VOL"
    rows = [header]
    year, month = first
    for i in range(n):
        rows.append(f"{year}{month:02d},{i},{i},{i},{i},{i},{i},{i},{i}")
        month += 1
        if month == 13:
            year, month = year + 1, 1
    path.write_text("\n".join(rows) + "\n")
    return path


# ------------------------------------------------------------------ the arithmetic


def test_the_identity_recovers_the_actual_yoy_from_the_actual_monthly_growth(
    real: NowcastData,
) -> None:
    assert yoy_from_mom(real, real.mom) == pytest.approx(real.yoy, abs=1e-9)


def test_a_constant_growth_economy_is_nowcast_exactly_by_every_rule(tmp_path: Path) -> None:
    levels = [100.0 * 1.003**i for i in range(60)]
    data = build_nowcast_data(
        _write_cpi(tmp_path / "c.csv", levels), _write_macro(tmp_path / "m.csv", (1990, 2), 60)
    )
    for rule in ("base_last", "base_mean3", "base_mean12"):
        forecast = yoy_from_mom(data, base_effect_forecast(data, rule))
        assert forecast == pytest.approx(data.yoy, abs=1e-9), rule
    assert data.previous_yoy == pytest.approx(data.yoy, abs=1e-9), "persistence too"


def test_a_base_effect_is_invisible_to_persistence_and_visible_to_the_base_rule(
    tmp_path: Path,
) -> None:
    """Steady 0.2% growth except one 2% jump. When the jump drops out of the 12-month window,
    inflation falls by about two points -- which persistence cannot see and any rule that
    forecasts the monthly growth gets right, because the month leaving the window is known."""
    growth = np.full(48, 0.002)
    growth[20] = 0.02
    levels = list(100.0 * np.cumprod(1.0 + growth))
    data = build_nowcast_data(
        _write_cpi(tmp_path / "c.csv", levels), _write_macro(tmp_path / "m.csv", (1990, 2), 48)
    )
    # the target month whose window loses the jump: 12 months after it
    i = next(
        k
        for k, m in enumerate(data.months)
        if abs(data.mom[k] - 0.2) < 1e-9 and data.mom_history[k, 0] > 1.9
    )
    persistence_error = abs(data.previous_yoy[i] - data.yoy[i])
    base_error = abs(yoy_from_mom(data, base_effect_forecast(data, "base_last"))[i] - data.yoy[i])
    assert data.previous_yoy[i] - data.yoy[i] == pytest.approx(1.8, abs=0.05)
    assert persistence_error > 1.7 and base_error < 1e-9


def test_unknown_rules_and_feature_sets_are_refused(real: NowcastData) -> None:
    with pytest.raises(ValueError, match="unknown base-effect rule"):
        base_effect_forecast(real, "nope")
    with pytest.raises(ValueError, match="unknown feature set"):
        feature_matrix(real, "nope")


# ------------------------------------------------------------------ no look-ahead


def test_features_for_a_month_use_only_what_is_known_at_its_end(tmp_path: Path) -> None:
    rng = np.random.default_rng(0)
    levels = list(100.0 * np.cumprod(1.0 + rng.normal(0.003, 0.002, 70)))
    macro = _write_macro(tmp_path / "m.csv", (1990, 2), 70)
    base = build_nowcast_data(_write_cpi(tmp_path / "a.csv", levels), macro)

    t = 40  # a target-month row
    shocked_levels = list(levels)
    # the level of the TARGET month itself (published after the decision) and everything after
    shocked_levels[t + 13 :] = [x * 1.5 for x in shocked_levels[t + 13 :]]
    shocked = build_nowcast_data(_write_cpi(tmp_path / "b.csv", shocked_levels), macro)

    for name in ("mom_history", "previous_yoy", "base_level", "year_ago_level"):
        assert np.array_equal(getattr(base, name)[: t + 1], getattr(shocked, name)[: t + 1]), name
    assert base.yoy[t] != shocked.yoy[t], "only the TARGET differs"


def test_macro_features_come_from_the_grid_row_of_the_decision_month(real: NowcastData) -> None:
    i = real.months.index(date(2008, 9, 30))
    from prometheus.data_ingestion.kaggle_macro_extended import load_extended_macro_observations

    rows = {
        o.observation_at: o.value
        for o in load_extended_macro_observations(MACRO_PATH, columns=("UNRATE",))
    }
    assert real.macro["UNRATE"][i] == rows[date(2008, 9, 30)]


def test_the_three_month_change_looks_backwards_only(real: NowcastData) -> None:
    features = feature_matrix(real, "core")
    unrate = real.macro["UNRATE"]
    i = real.months.index(date(2008, 9, 30))
    assert features[i, 12 + 1] == pytest.approx(unrate[i] - unrate[i - 3])


# ------------------------------------------------------------------ the models


def test_ridge_recovers_a_known_linear_rule_and_shrinks_with_the_penalty() -> None:
    rng = np.random.default_rng(1)
    x = rng.normal(size=(2_000, 3))
    y = 2.0 * x[:, 0] - 1.0 * x[:, 1] + 0.05 * rng.normal(size=2_000) + 0.5
    free = fit_ridge(x, y, 1e-6)
    standardised = free.coefficients / free.scale
    assert standardised == pytest.approx([2.0, -1.0, 0.0], abs=0.05)
    assert free.intercept == pytest.approx(y.mean())
    shrunk = fit_ridge(x, y, 1e6)
    assert np.abs(shrunk.coefficients).max() < 0.2 * np.abs(free.coefficients).max()
    assert free.predict(x[:5]).shape == (5,)
    with pytest.raises(ValueError, match="non-negative"):
        fit_ridge(x, y, -1.0)


def test_the_network_learns_a_linear_map_better_than_the_mean() -> None:
    rng = np.random.default_rng(2)
    x = rng.normal(size=(600, 4))
    y = 0.8 * x[:, 0] - 0.4 * x[:, 3]
    model = train_mom_network(
        x[:400], y[:400], x[400:500], y[400:500], seed=0, max_epochs=400, patience=30
    )
    held_out = slice(500, None)
    network_mse = float(np.mean((model.predict(x[held_out]) - y[held_out]) ** 2))
    assert network_mse < 0.3 * float(np.var(y[held_out]))


@pytest.mark.parametrize(
    ("low", "high", "predicted_negative", "expected"),
    [
        (-0.3, -0.1, True, "SUPPORTED"),
        (0.1, 0.3, True, "CONTRADICTED"),
        (-0.1, 0.2, True, "INCONCLUSIVE"),
        (0.1, 0.3, False, "SUPPORTED"),
        (-0.3, -0.1, False, "CONTRADICTED"),
    ],
)
def test_the_preregistered_decision_rule(
    low: float, high: float, predicted_negative: bool, expected: str
) -> None:
    assert verdict(low, high, predicted_negative=predicted_negative) == expected


# ------------------------------------------------------------------ the splits


def test_the_chronological_splits_do_not_overlap_and_the_test_window_is_the_documented_one(
    real: NowcastData,
) -> None:
    train = real.mask(None, study_module.TRAIN_END)
    validation = real.mask(study_module.TRAIN_END, study_module.VALIDATION_END) & ~train
    test = ~(train | validation) & ~np.isnan(feature_matrix(real, "all")).any(axis=1)
    assert not (train & validation).any() and not (validation & test).any()
    assert int(train.sum()) == 503 and int(validation.sum()) == 120 and int(test.sum()) == 277
    test_months = [m for m, keep in zip(real.months, test, strict=True) if keep]
    assert test_months[0] == date(2000, 1, 31) and test_months[-1] == date(2023, 1, 31)
    last_train = max(m for m, keep in zip(real.months, train, strict=True) if keep)
    assert last_train == date(1989, 12, 31)


# ------------------------------------------------------------------ one real run


@pytest.fixture(scope="module")
def study() -> dict[str, Any]:
    return run_study()


def test_the_pre_registration_is_in_the_module_docstring() -> None:
    doc = study_module.__doc__ or ""
    for question in ("Q1", "Q2", "Q3", "Q4", "Q5"):
        assert question in doc
    assert "BEFORE any number" in doc


def test_q1_the_base_effect_rule_beats_persistence_by_about_a_third(study: dict[str, Any]) -> None:
    comparison = study["comparisons"]["Q1_base_effect_vs_persistence"]
    assert comparison["preregistered_verdict"] == "SUPPORTED"
    assert comparison["ci_high"] < -0.03
    scores = study["scores"]
    assert scores["base_mean12"]["mae"] < 0.8 * scores["persistence_yoy"]["mae"]
    for rule in ("base_last", "base_mean3", "base_mean12"):
        assert scores[rule]["mae"] < scores["persistence_yoy"]["mae"], rule


def test_the_base_effect_matters_most_when_inflation_surges(study: dict[str, Any]) -> None:
    scores = study["scores"]
    assert (
        scores["base_last"]["mae_2020_onward"] < 0.75 * scores["persistence_yoy"]["mae_2020_onward"]
    )


def test_q2_a_learned_monthly_model_adds_a_little_on_top_of_the_best_rule(
    study: dict[str, Any],
) -> None:
    comparison = study["comparisons"]["Q2_ridge_own_vs_base_effect"]
    assert comparison["mae_difference_first_minus_second"] < 0
    assert comparison["ci_high"] < 0.01, "at best a small gain, never a loss"


def test_q3_macro_predictors_did_not_help(study: dict[str, Any]) -> None:
    for label in ("Q3_ridge_core_vs_own", "Q3_mlp_core_vs_own"):
        comparison = study["comparisons"][label]
        assert comparison["mae_difference_first_minus_second"] > -0.02, label
        assert comparison["preregistered_verdict"] != "SUPPORTED", label


def test_q4_more_history_did_not_help(study: dict[str, Any]) -> None:
    for label in ("Q4_ridge_1949_vs_1980", "Q4_mlp_1962_vs_1980"):
        comparison = study["comparisons"][label]
        assert comparison["mae_difference_first_minus_second"] > -0.02, label
        assert comparison["preregistered_verdict"] != "SUPPORTED", label


def test_validation_cannot_tell_the_ridge_variants_apart(study: dict[str, Any]) -> None:
    """All variants sit within a few thousandths of each other on the validation decade, so no
    single 'best' variant is headlined: one chosen on the test months would be selection."""
    values = [row["validation_mae"] for row in study["selection"].values()]
    assert max(values) - min(values) < 0.01


def test_every_learned_variant_beats_persistence_on_the_whole_test_window(
    study: dict[str, Any],
) -> None:
    persistence = study["scores"]["persistence_yoy"]["mae"]
    for name, row in study["scores"].items():
        if name.startswith(("ridge", "mlp")):
            assert row["mae"] < 0.8 * persistence, name


def test_descriptive_comparisons_carry_no_verdict(study: dict[str, Any]) -> None:
    for row in study["descriptive_comparisons"].values():
        assert "preregistered_verdict" not in row


def test_the_report_is_json_serialisable_and_states_its_caveats(study: dict[str, Any]) -> None:
    json.dumps(study)
    assert len(study["caveats"]) == 5
    assert study["data"]["n_test"] == 277 and study["data"]["n_test_2020_onward"] == 37


def test_main_writes_the_report_and_rejects_a_bad_seed_count(
    study: dict[str, Any], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(study_module, "run_study", lambda **_: study)
    out = tmp_path / "inflation.json"
    assert main(["--seeds", "1", "--output", str(out)]) == 0
    assert json.loads(out.read_text())["data"]["n_test"] == 277
    with pytest.raises(SystemExit):
        main(["--seeds", "0"])
    assert CPI_PATH.exists()
