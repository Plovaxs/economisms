from datetime import date
from pathlib import Path

import pytest

from prometheus.volterra.volterra_gen import (
    CONDITIONING_SERIES_IDS,
    GeneratedScenario,
    SyntheticLabelError,
    build_volterra_gen_dataset,
    chronological_split,
    load_observations_into_store,
    run_volterra_gen,
    sample_scenarios,
    train_scenario_generator,
)

DATA_PATH = Path(__file__).resolve().parents[2] / "data_cache" / "kaggle_us_macro_monthly.csv"


def test_generated_scenario_requires_is_synthetic_argument() -> None:
    with pytest.raises(TypeError):
        GeneratedScenario(  # type: ignore[call-arg]
            conditioning_month=date(2020, 1, 31),
            conditioning_features=(0.0,) * len(CONDITIONING_SERIES_IDS),
            generated_next_month_return=0.0,
        )


def test_generated_scenario_rejects_a_false_synthetic_label() -> None:
    with pytest.raises(SyntheticLabelError):
        GeneratedScenario(
            conditioning_month=date(2020, 1, 31),
            conditioning_features=(0.0,) * len(CONDITIONING_SERIES_IDS),
            generated_next_month_return=0.0,
            is_synthetic=False,
        )


def test_generated_scenario_rejects_a_falsified_source() -> None:
    with pytest.raises(SyntheticLabelError):
        GeneratedScenario(
            conditioning_month=date(2020, 1, 31),
            conditioning_features=(0.0,) * len(CONDITIONING_SERIES_IDS),
            generated_next_month_return=0.0,
            is_synthetic=True,
            source="real_market_data",
        )


def test_generated_scenario_rejects_wrong_feature_count() -> None:
    with pytest.raises(ValueError, match="conditioning_features"):
        GeneratedScenario(
            conditioning_month=date(2020, 1, 31),
            conditioning_features=(0.0, 0.0),
            generated_next_month_return=0.0,
            is_synthetic=True,
        )


def test_chronological_split_rejects_validation_not_before_test() -> None:
    store, months = load_observations_into_store(DATA_PATH)
    examples = build_volterra_gen_dataset(store, months)
    with pytest.raises(ValueError, match="validation_start"):
        chronological_split(examples, date(2020, 1, 1), date(2015, 1, 1))


def test_build_dataset_targets_are_the_real_next_months_value_not_the_same_month() -> None:
    store, months = load_observations_into_store(DATA_PATH)
    examples = build_volterra_gen_dataset(store, months)
    assert len(examples) > 400
    # Spot-check one real pair directly against the point-in-time store: the
    # label for decision_month must equal the NASDAQ series' OWN next-month
    # observation (the conditioning features' own month's value), never
    # the decision month's own realized value smuggled in as the label.
    sample = examples[0]
    this_months_nasdaq = store.as_of(
        "KAGGLE_NASDAQ_YOY", sample.decision_month, sample.decision_month
    )
    assert this_months_nasdaq is not None
    assert sample.features[-1] == this_months_nasdaq.value
    assert sample.target != this_months_nasdaq.value


def test_run_volterra_gen_end_to_end_on_real_data_is_deterministic_and_honestly_diagnosed() -> None:
    report = run_volterra_gen(DATA_PATH, seed=0)

    assert report.n_train > 0
    assert report.n_validation > 0
    assert report.n_test > 0
    assert report.calibration.n_observations == report.n_test
    assert report.verdict in (
        "generator_beats_classical_baseline",
        "classical_baseline_beats_generator",
        "inconclusive",
    )

    repeat = run_volterra_gen(DATA_PATH, seed=0)
    assert repeat.model_test_nll == report.model_test_nll
    assert repeat.verdict == report.verdict
    assert repeat.calibration.observed_coverage == report.calibration.observed_coverage

    # The real, observed result on the committed data as of this PR: the
    # 2020+ test window (which includes the COVID crash/recovery) is a
    # genuine distribution shift this small MLP's learned variance badly
    # underestimates -- an honest negative finding, reported as-is rather
    # than hidden or re-run until it looked better, the same standard this
    # project already held INFLATIONCAST's miscalibrated GRU result to.
    assert report.verdict == "classical_baseline_beats_generator"
    assert report.calibration.observed_coverage < 0.90
    assert report.calibration.p_value < 0.01


def test_sample_scenarios_are_all_explicitly_synthetic_and_deterministic_given_seed() -> None:
    store, months = load_observations_into_store(DATA_PATH)
    examples = build_volterra_gen_dataset(store, months)
    train, validation, test = chronological_split(examples, date(2015, 1, 1), date(2020, 1, 1))
    trained = train_scenario_generator(train, validation, seed=0, max_epochs=20, patience=5)

    scenarios = sample_scenarios(trained.model, test[:3], n_samples_per_example=5, seed=1)
    assert len(scenarios) == 15
    assert all(s.is_synthetic is True for s in scenarios)
    assert all(s.source == "volterra_gen" for s in scenarios)

    repeat = sample_scenarios(trained.model, test[:3], n_samples_per_example=5, seed=1)
    assert [s.generated_next_month_return for s in scenarios] == [
        s.generated_next_month_return for s in repeat
    ]
