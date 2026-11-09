import numpy as np
import pytest
import torch

from prometheus.quantum.models import LogisticRegressionClassifier
from prometheus.recessionnet.training import train_classifier


def _toy_data(n: int = 40, input_dim: int = 3, seed: int = 0) -> tuple[np.ndarray, np.ndarray]:
    rng = np.random.default_rng(seed)
    features = rng.normal(size=(n, input_dim))
    labels = (features[:, 0] > 0).astype(float)
    return features, labels


def test_train_classifier_reduces_loss_over_epochs() -> None:
    features, labels = _toy_data()
    trained = train_classifier(
        lambda: LogisticRegressionClassifier(features.shape[1]),
        features,
        labels,
        seed=0,
        n_epochs=200,
    )
    assert len(trained.epoch_log) == 200
    assert trained.epoch_log[-1].loss < trained.epoch_log[0].loss


def test_train_classifier_rejects_non_positive_epochs() -> None:
    features, labels = _toy_data()
    with pytest.raises(ValueError, match="n_epochs"):
        train_classifier(
            lambda: LogisticRegressionClassifier(features.shape[1]),
            features,
            labels,
            seed=0,
            n_epochs=0,
        )


def test_train_classifier_rejects_mismatched_row_counts() -> None:
    features, labels = _toy_data()
    with pytest.raises(ValueError, match="same number of rows"):
        train_classifier(
            lambda: LogisticRegressionClassifier(features.shape[1]),
            features,
            labels[:-1],
            seed=0,
            n_epochs=5,
        )


def test_train_classifier_reports_parameter_count_and_timing() -> None:
    features, labels = _toy_data(input_dim=4)
    trained = train_classifier(
        lambda: LogisticRegressionClassifier(features.shape[1]),
        features,
        labels,
        seed=0,
        n_epochs=10,
    )
    assert trained.n_parameters == 4 + 1
    assert trained.train_seconds >= 0.0
    assert trained.seed == 0


def test_train_classifier_is_reproducible_given_the_same_seed() -> None:
    features, labels = _toy_data()
    trained_a = train_classifier(
        lambda: LogisticRegressionClassifier(features.shape[1]),
        features,
        labels,
        seed=5,
        n_epochs=30,
    )
    trained_b = train_classifier(
        lambda: LogisticRegressionClassifier(features.shape[1]),
        features,
        labels,
        seed=5,
        n_epochs=30,
    )
    params_a = torch.cat([p.flatten() for p in trained_a.model.parameters()])
    params_b = torch.cat([p.flatten() for p in trained_b.model.parameters()])
    assert torch.allclose(params_a, params_b)
