import copy
from pathlib import Path

import numpy as np
import pytest

from prometheus.data_ingestion.kaggle_macro import load_kaggle_us_macro_observations
from prometheus.neural_sde.dataset import (
    build_point_in_time_store,
    build_transition_dataset,
    chronological_split,
    fit_scaler,
)
from prometheus.neural_sde.design import DEFAULT_DESIGN_SPEC
from prometheus.neural_sde.ood import (
    COVID_OOD_WINDOW_END,
    COVID_OOD_WINDOW_START,
    evaluate_ood_without_retuning,
    split_pre_and_during_covid,
)
from prometheus.neural_sde.training import train_neural_sde

_CSV_PATH = Path(__file__).resolve().parents[2] / "data_cache" / "kaggle_us_macro_monthly.csv"


def _real_observations():
    return load_kaggle_us_macro_observations(_CSV_PATH)


def test_real_gdp_yoy_hits_its_sample_wide_minimum_inside_the_covid_window() -> None:
    """Verifies the claim this module's docstring makes directly against
    the committed real CSV, rather than trusting the docstring's prose."""
    observations = _real_observations()
    gdp = [o for o in observations if o.series_id == "KAGGLE_GDP_YOY"]
    most_negative = min(gdp, key=lambda o: o.value)
    assert COVID_OOD_WINDOW_START <= most_negative.observation_at <= COVID_OOD_WINDOW_END
    assert most_negative.value == pytest.approx(-7.689368896330128, abs=1e-6)


def test_real_claims_yoy_hits_its_sample_wide_maximum_inside_the_covid_window() -> None:
    observations = _real_observations()
    claims = [o for o in observations if o.series_id == "KAGGLE_CLAIMS_YOY"]
    most_positive = max(claims, key=lambda o: o.value)
    assert COVID_OOD_WINDOW_START <= most_positive.observation_at <= COVID_OOD_WINDOW_END
    assert most_positive.value == pytest.approx(1146.4183381088824, abs=1e-6)


def test_real_nasdaq_yoy_does_not_hit_an_extreme_inside_the_covid_window() -> None:
    """The disclosed asymmetry this module's docstring names explicitly:
    NASDAQ's all-time low/high in this sample are NOT inside the COVID
    window."""
    observations = _real_observations()
    nasdaq = [o for o in observations if o.series_id == "KAGGLE_NASDAQ_YOY"]
    most_negative = min(nasdaq, key=lambda o: o.value)
    most_positive = max(nasdaq, key=lambda o: o.value)
    assert not (COVID_OOD_WINDOW_START <= most_negative.observation_at <= COVID_OOD_WINDOW_END)
    assert not (COVID_OOD_WINDOW_START <= most_positive.observation_at <= COVID_OOD_WINDOW_END)
    covid_values = [
        o.value
        for o in nasdaq
        if COVID_OOD_WINDOW_START <= o.observation_at <= COVID_OOD_WINDOW_END
    ]
    assert all(v > -5 for v in covid_values)  # mildly negative/positive, not a crash in YoY terms


def test_split_pre_and_during_covid_partitions_by_decision_time() -> None:
    observations = _real_observations()
    store = build_point_in_time_store(observations)
    months = sorted({o.observation_at for o in observations})
    examples = build_transition_dataset(store, DEFAULT_DESIGN_SPEC, months)

    pre_covid, covid_window = split_pre_and_during_covid(examples)
    assert len(pre_covid) > 0
    assert len(covid_window) > 0
    assert all(e.decision_time < COVID_OOD_WINDOW_START for e in pre_covid)
    assert all(
        COVID_OOD_WINDOW_START <= e.decision_time <= COVID_OOD_WINDOW_END for e in covid_window
    )


def test_evaluate_ood_without_retuning_does_not_mutate_the_trained_model() -> None:
    observations = _real_observations()
    store = build_point_in_time_store(observations)
    months = sorted({o.observation_at for o in observations})
    examples = build_transition_dataset(store, DEFAULT_DESIGN_SPEC, months)
    pre_covid, covid_window = split_pre_and_during_covid(examples)
    train_examples, validation_examples = chronological_split(pre_covid, train_fraction=0.8)

    state_scaler = fit_scaler(np.array([e.state for e in train_examples]))
    regime_scaler = fit_scaler(np.array([e.regime for e in train_examples]))
    trained = train_neural_sde(
        train_examples,
        validation_examples,
        state_scaler,
        regime_scaler,
        seed=0,
        max_epochs=10,
        patience=5,
    )
    state_dict_before = copy.deepcopy(trained.model.state_dict())

    report = evaluate_ood_without_retuning(
        trained, validation_examples, covid_window, train_examples
    )

    state_dict_after = trained.model.state_dict()
    for key in state_dict_before:
        assert (state_dict_before[key] == state_dict_after[key]).all()

    assert report.n_covid == len(covid_window)
    assert report.n_in_distribution == len(validation_examples)


def test_evaluate_ood_without_retuning_rejects_empty_covid_window() -> None:
    observations = _real_observations()
    store = build_point_in_time_store(observations)
    months = sorted({o.observation_at for o in observations})
    examples = build_transition_dataset(store, DEFAULT_DESIGN_SPEC, months)
    pre_covid, _ = split_pre_and_during_covid(examples)
    train_examples, validation_examples = chronological_split(pre_covid, train_fraction=0.8)

    state_scaler = fit_scaler(np.array([e.state for e in train_examples]))
    regime_scaler = fit_scaler(np.array([e.regime for e in train_examples]))
    trained = train_neural_sde(
        train_examples,
        validation_examples,
        state_scaler,
        regime_scaler,
        seed=0,
        max_epochs=5,
        patience=3,
    )
    with pytest.raises(ValueError, match="covid_window"):
        evaluate_ood_without_retuning(trained, validation_examples, [], train_examples)
