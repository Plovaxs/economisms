from datetime import date, timedelta

import numpy as np
import pytest

from prometheus.neural_sde.dataset import TransitionExample, fit_scaler
from prometheus.neural_sde.design import DEFAULT_DESIGN_SPEC
from prometheus.neural_sde.registry import MODEL_VERSION, model_card_from_trained_model
from prometheus.neural_sde.training import train_neural_sde


def _examples(n: int) -> list[TransitionExample]:
    base = date(2000, 1, 1)
    return [
        TransitionExample(
            t_scaled=float(i),
            state=(float(i), float(i) * 0.5),
            regime=(float(i) * 0.1, float(i) * 0.2, float(i) * 0.3),
            next_state=(float(i + 1), float(i + 1) * 0.5),
            decision_time=base + timedelta(days=30 * i),
            next_time=base + timedelta(days=30 * (i + 1)),
        )
        for i in range(n)
    ]


def test_model_card_round_trip_from_a_real_trained_model() -> None:
    train_examples = _examples(20)
    validation_examples = _examples(8)
    state_scaler = fit_scaler(np.array([e.state for e in train_examples]))
    regime_scaler = fit_scaler(np.array([e.regime for e in train_examples]))
    trained = train_neural_sde(
        train_examples,
        validation_examples,
        state_scaler,
        regime_scaler,
        seed=42,
        max_epochs=5,
        patience=3,
    )

    card = model_card_from_trained_model(trained, train_examples, DEFAULT_DESIGN_SPEC)

    assert card.model_version == MODEL_VERSION
    assert card.seed == 42
    assert card.n_parameters == trained.n_parameters
    assert card.training_range_start == train_examples[0].decision_time
    assert card.training_range_end == train_examples[-1].decision_time
    assert card.n_training_examples == len(train_examples)
    assert card.state_series_ids == DEFAULT_DESIGN_SPEC.state_series_ids
    assert card.regime_series_ids == DEFAULT_DESIGN_SPEC.regime_series_ids
    assert len(card.limitations) > 0
    assert card.python_version
    assert card.torch_version
    assert card.numpy_version
    assert card.created_at


def test_model_card_rejects_empty_training_examples() -> None:
    train_examples = _examples(10)
    validation_examples = _examples(5)
    state_scaler = fit_scaler(np.array([e.state for e in train_examples]))
    regime_scaler = fit_scaler(np.array([e.regime for e in train_examples]))
    trained = train_neural_sde(
        train_examples,
        validation_examples,
        state_scaler,
        regime_scaler,
        seed=0,
        max_epochs=3,
        patience=2,
    )
    with pytest.raises(ValueError, match="non-empty"):
        model_card_from_trained_model(trained, [], DEFAULT_DESIGN_SPEC)
