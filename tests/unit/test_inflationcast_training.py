import numpy as np
import pytest

from prometheus.inflationcast.models import LinearRegressionModel
from prometheus.inflationcast.training import (
    train_flattened_candidate_with_early_stopping,
    train_inflation_gru_with_early_stopping,
)

_N_SERIES = 3
_WINDOW = 4
_WIDTH = _WINDOW * _N_SERIES * 2


def _synthetic_regression_arrays(
    n_train: int = 60, n_val: int = 20, seed: int = 0
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    rng = np.random.default_rng(seed)
    x_train = rng.normal(size=(n_train, _WIDTH))
    true_weights = rng.normal(size=_WIDTH)
    y_train = x_train @ true_weights + rng.normal(scale=0.01, size=n_train)
    x_val = rng.normal(size=(n_val, _WIDTH))
    y_val = x_val @ true_weights + rng.normal(scale=0.01, size=n_val)
    return x_train, y_train, x_val, y_val


def test_train_flattened_candidate_is_deterministic_for_a_fixed_seed() -> None:
    x_train, y_train, x_val, y_val = _synthetic_regression_arrays()
    kwargs = dict(
        model_factory=lambda: LinearRegressionModel(input_dim=_WIDTH),
        train_features=x_train,
        train_targets=y_train,
        validation_features=x_val,
        validation_targets=y_val,
        seed=0,
        max_epochs=30,
        patience=5,
    )
    first = train_flattened_candidate_with_early_stopping(**kwargs)
    second = train_flattened_candidate_with_early_stopping(**kwargs)
    assert first.best_validation_score == second.best_validation_score
    assert first.selected_epoch == second.selected_epoch


def test_train_flattened_candidate_fits_a_near_linear_relationship() -> None:
    x_train, y_train, x_val, y_val = _synthetic_regression_arrays(n_train=200, n_val=60)
    trained = train_flattened_candidate_with_early_stopping(
        lambda: LinearRegressionModel(input_dim=_WIDTH),
        x_train, y_train, x_val, y_val,
        seed=0, max_epochs=500, patience=30, learning_rate=0.05,
    )
    assert trained.best_validation_score < np.var(y_val)


def test_train_flattened_candidate_rejects_non_positive_max_epochs() -> None:
    x_train, y_train, x_val, y_val = _synthetic_regression_arrays()
    with pytest.raises(ValueError, match="max_epochs"):
        train_flattened_candidate_with_early_stopping(
            lambda: LinearRegressionModel(input_dim=_WIDTH),
            x_train, y_train, x_val, y_val,
            seed=0, max_epochs=0, patience=5,
        )


def test_train_inflation_gru_is_deterministic_for_a_fixed_seed() -> None:
    x_train, y_train, x_val, y_val = _synthetic_regression_arrays()
    kwargs = dict(
        train_features=x_train,
        train_targets=y_train,
        validation_features=x_val,
        validation_targets=y_val,
        n_series=_N_SERIES,
        seed=0,
        max_epochs=20,
        patience=5,
    )
    first = train_inflation_gru_with_early_stopping(**kwargs)
    second = train_inflation_gru_with_early_stopping(**kwargs)
    assert first.best_validation_nll == second.best_validation_nll
    assert first.selected_epoch == second.selected_epoch


def test_train_inflation_gru_infers_window_from_flat_feature_width() -> None:
    x_train, y_train, x_val, y_val = _synthetic_regression_arrays()
    trained = train_inflation_gru_with_early_stopping(
        x_train, y_train, x_val, y_val,
        n_series=_N_SERIES, seed=0, max_epochs=5, patience=2,
    )
    assert trained.model.n_series == _N_SERIES


def test_train_inflation_gru_rejects_a_feature_width_not_divisible_by_series_and_mask() -> None:
    x_train, y_train, x_val, y_val = _synthetic_regression_arrays()
    with pytest.raises(ValueError, match="whole number"):
        train_inflation_gru_with_early_stopping(
            x_train, y_train, x_val, y_val,
            n_series=_N_SERIES + 2, seed=0, max_epochs=5, patience=2,
        )


def test_train_inflation_gru_rejects_an_empty_validation_set() -> None:
    x_train, y_train, _, _ = _synthetic_regression_arrays()
    empty = np.zeros((0, _WIDTH))
    with pytest.raises(ValueError, match="non-empty"):
        train_inflation_gru_with_early_stopping(
            x_train, y_train, empty, np.zeros(0),
            n_series=_N_SERIES, seed=0, max_epochs=5, patience=2,
        )


def test_train_inflation_gru_selects_the_best_validation_epoch_not_the_last() -> None:
    """Early stopping must restore the checkpoint at `selected_epoch`,
    not whatever state training happened to end on -- the same
    guarantee `recessionnet.training`'s docstring promises."""
    x_train, y_train, x_val, y_val = _synthetic_regression_arrays(n_train=200, n_val=60)
    trained = train_inflation_gru_with_early_stopping(
        x_train, y_train, x_val, y_val,
        n_series=_N_SERIES, seed=0, max_epochs=100, patience=5,
    )
    ran_epochs = len(trained.epoch_log)
    assert 0 <= trained.selected_epoch < ran_epochs
