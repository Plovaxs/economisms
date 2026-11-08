from datetime import date

import numpy as np
import pytest

from prometheus.evidence.dataset_card import build_dataset_card
from prometheus.evidence.dataset_provenance import (
    ProvenanceMismatchError,
    build_dataset_provenance,
)
from prometheus.evidence.model_package import build_model_package
from prometheus.evidence.reproducible_inference import InputContract
from prometheus.experiments.dataset_fingerprint import compute_dataset_fingerprint
from prometheus.experiments.holdout_manifest import DataSplit, build_holdout_manifest
from prometheus.stochastica.gbm import simulate_gbm_paths


def _real_fingerprint():
    rng = np.random.default_rng(0)
    paths = simulate_gbm_paths(100.0, 0.08, 0.2, 1.0, n_steps=10, n_paths=5, rng=rng)
    log_returns = np.diff(np.log(paths), axis=1)
    return compute_dataset_fingerprint(log_returns, "log_returns_v1")


def _manifest():
    return build_holdout_manifest(
        [
            DataSplit("train", "train", date(2024, 1, 1), date(2024, 6, 30)),
            DataSplit("val", "validation", date(2024, 7, 1), date(2024, 9, 30)),
            DataSplit("test", "test", date(2024, 10, 1), date(2024, 12, 31)),
        ]
    )


def _package():
    return build_model_package("hedge_policy_v0", "v1", b"model weights go here")


def _contract(model_id: str = "hedge_policy_v0") -> InputContract:
    return InputContract(model_id, ("log_moneyness", "remaining_fraction", "prior_holding"))


def test_a_consistent_provenance_record_assembles_from_four_real_primitives() -> None:
    """MLO-03's own acceptance criterion: "model artifact includes
    unambiguous dataset provenance," assembled here from four real
    primitives this project already built for other checklist items
    (MLO-07, DAT-12, MLO-11, EXP-04), not reinvented."""
    provenance = build_dataset_provenance(_package(), _real_fingerprint(), _contract(), _manifest())
    assert provenance.model_package.model_id == "hedge_policy_v0"
    assert provenance.training_cutoff_date == date(2024, 6, 30)


def test_dataset_card_is_optional_but_carried_when_supplied() -> None:
    card = build_dataset_card("gbm_demo", "synthetic", "stochastica.gbm simulation", "demo paths")
    provenance = build_dataset_provenance(
        _package(), _real_fingerprint(), _contract(), _manifest(), card
    )
    assert provenance.dataset_card is card


def test_a_mismatched_feature_contract_is_rejected() -> None:
    """The discriminating half: a provenance record assembled from a
    feature contract naming a DIFFERENT model than the package it is
    attached to would not be "unambiguous," it would be actively
    misleading -- rejected before the record is ever constructed."""
    mismatched_contract = _contract(model_id="some_other_model")
    with pytest.raises(ProvenanceMismatchError, match="two different models"):
        build_dataset_provenance(_package(), _real_fingerprint(), mismatched_contract, _manifest())


def test_a_manifest_with_no_train_split_is_rejected() -> None:
    manifest_without_train = build_holdout_manifest(
        [DataSplit("val", "validation", date(2024, 7, 1), date(2024, 9, 30))]
    )
    with pytest.raises(ProvenanceMismatchError, match="no 'train' split"):
        build_dataset_provenance(
            _package(), _real_fingerprint(), _contract(), manifest_without_train
        )


def test_training_cutoff_is_the_latest_end_date_among_multiple_train_splits() -> None:
    """If a manifest happens to carry more than one 'train'-labeled
    split, the cutoff must be the LATEST of them -- the most recent
    point any training data was locked in, not an arbitrary one."""
    manifest = build_holdout_manifest(
        [
            DataSplit("train_early", "train", date(2023, 1, 1), date(2023, 6, 30)),
            DataSplit("train_late", "train", date(2023, 7, 1), date(2024, 1, 1)),
            DataSplit("test", "test", date(2024, 2, 1), date(2024, 12, 31)),
        ]
    )
    provenance = build_dataset_provenance(_package(), _real_fingerprint(), _contract(), manifest)
    assert provenance.training_cutoff_date == date(2024, 1, 1)
