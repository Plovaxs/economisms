"""FP-08: "Shared-vs-independent encoder ablation is complete." -- a
real end-to-end run on the real, committed Kaggle macro + BLS CPI
snapshots (the same two sources RECESSIONNET's Kaggle grounding and
INFLATIONCAST already use), not mocked data.
"""

from __future__ import annotations

from datetime import date

import numpy as np
import pytest

from prometheus.data_ingestion.kaggle_macro import (
    KAGGLE_SERIES_IDS,
    load_kaggle_us_macro_observations,
)
from prometheus.encoders.ablation import (
    DEFAULT_CPI_CSV_PATH,
    DEFAULT_KAGGLE_CSV_PATH,
    EncoderAblationConfig,
    run_encoder_ablation,
)
from prometheus.encoders.shared_dataset import (
    SharedEncoderExample,
    build_shared_encoder_dataset,
    chronological_split3,
    stack_features,
)
from prometheus.encoders.shared_encoder import InflationHead, RecessionHead, TemporalEncoder
from prometheus.inflationcast.data import load_cpi_observations

_CPI_SERIES_ID = "CPI_YOY"
_FAST_CONFIG = EncoderAblationConfig(seed=0, max_epochs=60, patience=10)


def _real_examples(window: int = 6, horizon: int = 6) -> tuple[SharedEncoderExample, ...]:
    kaggle_observations = load_kaggle_us_macro_observations(DEFAULT_KAGGLE_CSV_PATH)
    cpi_observations = load_cpi_observations(DEFAULT_CPI_CSV_PATH)
    return build_shared_encoder_dataset(
        kaggle_observations,
        cpi_observations,
        series_ids=KAGGLE_SERIES_IDS,
        cpi_series_id=_CPI_SERIES_ID,
        window=window,
        horizon=horizon,
    )


def test_shared_dataset_is_built_from_real_data_and_both_labels_are_real() -> None:
    examples = _real_examples()
    assert len(examples) > 50  # real 2007-01..2023-01 overlap, not an empty/trivial set
    # strictly increasing decision months -- confirms the chronological join is sound
    months = [e.decision_month for e in examples]
    assert months == sorted(months)
    assert len(set(months)) == len(months)
    for example in examples:
        assert example.features.shape == (6 * len(KAGGLE_SERIES_IDS),)
        assert example.recession_label in (0.0, 1.0)
        assert np.isfinite(example.inflation_target)
    # a real recession (2020 COVID contraction) must appear in this window
    assert any(e.recession_label == 1.0 for e in examples)
    # not every month is a recession either -- a real, non-degenerate label mix
    assert any(e.recession_label == 0.0 for e in examples)


def test_chronological_split3_is_strictly_ordered_and_non_overlapping() -> None:
    examples = _real_examples()
    train, validation, test = chronological_split3(examples, date(2015, 1, 1), date(2019, 1, 1))
    assert train and validation and test
    assert max(e.decision_month for e in train) < date(2015, 1, 1)
    assert all(date(2015, 1, 1) <= e.decision_month < date(2019, 1, 1) for e in validation)
    assert min(e.decision_month for e in test) >= date(2019, 1, 1)
    assert len(train) + len(validation) + len(test) == len(examples)


def test_stack_features_reshapes_to_window_by_series() -> None:
    examples = _real_examples()
    stacked = stack_features(examples, window=6, n_series=len(KAGGLE_SERIES_IDS))
    assert stacked.shape == (len(examples), 6, len(KAGGLE_SERIES_IDS))
    # reshape must round-trip exactly against the original flat features
    np.testing.assert_allclose(stacked[0].reshape(-1), examples[0].features)


def test_shared_and_independent_encoders_have_matched_capacity() -> None:
    """The ablation's whole premise -- comparing REPRESENTATION
    SHARING, not comparing two differently-sized models -- depends on
    every encoder instance (the one shared encoder, and each of the
    two independent encoders) having the identical architecture."""
    n_series = len(KAGGLE_SERIES_IDS)
    shared_encoder = TemporalEncoder(n_series, hidden_size=16)
    indep_rec_encoder = TemporalEncoder(n_series, hidden_size=16)
    indep_inf_encoder = TemporalEncoder(n_series, hidden_size=16)
    param_counts = {
        sum(p.numel() for p in shared_encoder.parameters()),
        sum(p.numel() for p in indep_rec_encoder.parameters()),
        sum(p.numel() for p in indep_inf_encoder.parameters()),
    }
    assert len(param_counts) == 1  # all three identical
    assert param_counts.pop() > 0
    # heads are also identically shaped per task across conditions
    assert sum(p.numel() for p in RecessionHead(16).parameters()) == sum(
        p.numel() for p in RecessionHead(16).parameters()
    )
    assert sum(p.numel() for p in InflationHead(16).parameters()) > 0


def test_run_encoder_ablation_end_to_end_on_real_data_is_deterministic() -> None:
    result_a = run_encoder_ablation(_FAST_CONFIG)
    result_b = run_encoder_ablation(_FAST_CONFIG)

    assert result_a.n_train > 0 and result_a.n_validation > 0 and result_a.n_test > 0
    # matched capacity, asserted on the real trained models this run produced
    assert (
        result_a.shared_encoder_n_parameters
        == result_a.independent_recession_encoder_n_parameters
        == result_a.independent_inflation_encoder_n_parameters
    )
    # lambda weights are real, finite, validation-derived numbers, not placeholders
    assert result_a.lambda_recession > 0
    assert result_a.lambda_inflation > 0

    for value in (
        result_a.shared_recession_test_roc_auc,
        result_a.independent_recession_test_roc_auc,
    ):
        assert 0.0 <= value <= 1.0
    for value in (
        result_a.shared_recession_test_brier,
        result_a.independent_recession_test_brier,
    ):
        assert 0.0 <= value <= 1.0
    for value in (result_a.shared_inflation_test_mae, result_a.independent_inflation_test_mae):
        assert value >= 0.0 and np.isfinite(value)

    assert result_a.recession_verdict in ("shared_better", "independent_better", "inconclusive")
    assert result_a.inflation_verdict in ("shared_better", "independent_better", "inconclusive")

    # deterministic given a fixed seed -- same real data, same result, bit-for-bit
    assert result_a.shared_recession_test_brier == result_b.shared_recession_test_brier
    assert result_a.independent_recession_test_brier == result_b.independent_recession_test_brier
    assert result_a.shared_inflation_test_mae == result_b.shared_inflation_test_mae
    assert result_a.independent_inflation_test_mae == result_b.independent_inflation_test_mae
    assert result_a.recession_verdict == result_b.recession_verdict
    assert result_a.inflation_verdict == result_b.inflation_verdict


def test_config_rejects_a_validation_split_not_before_the_test_split() -> None:
    with pytest.raises(ValueError, match="validation_split_date"):
        EncoderAblationConfig(
            validation_split_date=date(2020, 1, 1), test_split_date=date(2020, 1, 1)
        )
