import numpy as np
import pytest
import torch
from torch import nn

from prometheus.quantum.models import LogisticRegressionClassifier
from prometheus.recessionnet.training import train_classifier, train_classifier_with_early_stopping


def _toy_data(n: int = 40, input_dim: int = 3, seed: int = 0) -> tuple[np.ndarray, np.ndarray]:
    rng = np.random.default_rng(seed)
    features = rng.normal(size=(n, input_dim))
    labels = (features[:, 0] > 0).astype(float)
    return features, labels


class _OverfittableToyMLP(nn.Module):
    """A deliberately high-capacity model (two 64-unit hidden layers)
    relative to a tiny dataset, used only to force genuine overfitting
    within a few epochs for a fast, reliable early-stopping test."""

    def __init__(self, input_dim: int) -> None:
        super().__init__()
        self.net = nn.Sequential(
            nn.Linear(input_dim, 64), nn.ReLU(), nn.Linear(64, 64), nn.ReLU(), nn.Linear(64, 1)
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        output: torch.Tensor = self.net(x).squeeze(-1)
        return output


def _unrelated_train_val_data(
    seed: int = 0,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Labels drawn independently of the features on BOTH sides, so any
    training beyond chance is memorization, not generalization -- a
    high-capacity model should overfit almost immediately, making
    early stopping trigger well before `max_epochs`."""
    rng = np.random.default_rng(seed)
    train_features = rng.normal(size=(30, 5))
    train_labels = rng.integers(0, 2, size=30).astype(float)
    val_features = rng.normal(size=(20, 5))
    val_labels = rng.integers(0, 2, size=20).astype(float)
    return train_features, train_labels, val_features, val_labels


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


def test_early_stopping_rejects_non_positive_max_epochs() -> None:
    tf, tl, vf, vl = _unrelated_train_val_data()
    with pytest.raises(ValueError, match="max_epochs"):
        train_classifier_with_early_stopping(
            lambda: _OverfittableToyMLP(5), tf, tl, vf, vl, seed=0, max_epochs=0, patience=5
        )


def test_early_stopping_rejects_non_positive_patience() -> None:
    tf, tl, vf, vl = _unrelated_train_val_data()
    with pytest.raises(ValueError, match="patience"):
        train_classifier_with_early_stopping(
            lambda: _OverfittableToyMLP(5), tf, tl, vf, vl, seed=0, max_epochs=10, patience=0
        )


def test_early_stopping_rejects_mismatched_train_rows() -> None:
    tf, tl, vf, vl = _unrelated_train_val_data()
    with pytest.raises(ValueError, match="train_features and train_labels"):
        train_classifier_with_early_stopping(
            lambda: _OverfittableToyMLP(5), tf, tl[:-1], vf, vl, seed=0, max_epochs=10, patience=5
        )


def test_early_stopping_rejects_mismatched_validation_rows() -> None:
    tf, tl, vf, vl = _unrelated_train_val_data()
    with pytest.raises(ValueError, match="validation_features and validation_labels"):
        train_classifier_with_early_stopping(
            lambda: _OverfittableToyMLP(5), tf, tl, vf, vl[:-1], seed=0, max_epochs=10, patience=5
        )


def test_early_stopping_rejects_an_empty_validation_set() -> None:
    tf, tl, vf, vl = _unrelated_train_val_data()
    with pytest.raises(ValueError, match="non-empty"):
        train_classifier_with_early_stopping(
            lambda: _OverfittableToyMLP(5),
            tf, tl, vf[:0], vl[:0],
            seed=0, max_epochs=10, patience=5,
        )


def test_early_stopping_triggers_before_max_epochs_on_an_overfittable_problem() -> None:
    tf, tl, vf, vl = _unrelated_train_val_data()
    result = train_classifier_with_early_stopping(
        lambda: _OverfittableToyMLP(5), tf, tl, vf, vl, seed=0, max_epochs=500, patience=10
    )
    assert len(result.epoch_log) < 500
    assert len(result.epoch_log) == len(result.validation_log)
    assert result.selected_epoch <= len(result.epoch_log) - 1


def test_early_stopping_restores_the_best_checkpoint_not_the_final_epoch() -> None:
    """The discriminating case: confirms the returned model's weights
    are genuinely the best-validation checkpoint, not whatever state
    training happened to end on after `patience` more (worse) epochs."""
    tf, tl, vf, vl = _unrelated_train_val_data()
    result = train_classifier_with_early_stopping(
        lambda: _OverfittableToyMLP(5), tf, tl, vf, vl, seed=0, max_epochs=500, patience=10
    )
    result.model.eval()
    with torch.no_grad():
        probs = torch.sigmoid(result.model(torch.tensor(vf, dtype=torch.float32))).numpy()
    recomputed_brier = float(np.mean((probs - vl) ** 2))
    assert recomputed_brier == pytest.approx(result.best_validation_score, abs=1e-6)
    # And it must genuinely differ from the final (worse, overfit) epoch's loss trajectory --
    # otherwise "restoring the checkpoint" would be a no-op.
    assert result.selected_epoch < len(result.epoch_log) - 1


def test_early_stopping_reports_parameter_count_and_timing() -> None:
    tf, tl, vf, vl = _unrelated_train_val_data()
    result = train_classifier_with_early_stopping(
        lambda: LogisticRegressionClassifier(5), tf, tl, vf, vl, seed=0, max_epochs=20, patience=20
    )
    assert result.n_parameters == 5 + 1
    assert result.train_seconds >= 0.0
    assert result.seed == 0


def test_early_stopping_is_reproducible_given_the_same_seed() -> None:
    tf, tl, vf, vl = _unrelated_train_val_data()
    result_a = train_classifier_with_early_stopping(
        lambda: _OverfittableToyMLP(5), tf, tl, vf, vl, seed=3, max_epochs=200, patience=10
    )
    result_b = train_classifier_with_early_stopping(
        lambda: _OverfittableToyMLP(5), tf, tl, vf, vl, seed=3, max_epochs=200, patience=10
    )
    assert result_a.selected_epoch == result_b.selected_epoch
    params_a = torch.cat([p.flatten() for p in result_a.model.parameters()])
    params_b = torch.cat([p.flatten() for p in result_b.model.parameters()])
    assert torch.allclose(params_a, params_b)


def test_early_stopping_runs_the_full_max_epochs_when_validation_never_worsens() -> None:
    """A low-capacity model on an easy, learnable problem should never
    trigger patience -- confirms the loop's OTHER exit path (reaching
    max_epochs) also works, not just the early-break path."""
    features, labels = _toy_data(n=60, input_dim=3)
    result = train_classifier_with_early_stopping(
        lambda: LogisticRegressionClassifier(3),
        features,
        labels,
        features,
        labels,
        seed=0,
        max_epochs=15,
        patience=1000,
    )
    assert len(result.epoch_log) == 15
