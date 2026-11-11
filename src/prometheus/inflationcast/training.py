"""Training for every learned INFLATIONCAST candidate.

The flattened-window candidates (`LinearRegressionModel`,
`ClassicalMatchedRegressor`, `HybridQuantumRegressor`) reuse
`recessionnet.training.train_classifier_with_early_stopping` UNCHANGED
with `loss_fn=nn.MSELoss()` -- the identical composition Q-MACRO
(`macrocore.quantum_benchmark`) already relies on; nothing in that
loop is classification- or recession-specific once the loss function
is pulled out as a parameter.

`InflationGRU` gets its own dedicated loop (`train_inflation_gru_with_
early_stopping`), the same way `neural_sde.training.train_neural_sde`
has its own rather than being forced through the generic one: its
`forward` returns a (mean, log_var) PAIR, not a single tensor, so it
cannot be scored by a plain `loss_fn(output, target)` call -- the
Gaussian NLL (`models.gaussian_nll`) IS this model's loss, used for
both training and validation-based model selection, so there is no
separate "validation metric" to bolt on afterward."""

from __future__ import annotations

import copy
import time
from collections.abc import Callable
from dataclasses import dataclass

import numpy as np
import torch
from torch import nn

from prometheus.inflationcast.models import InflationGRU, gaussian_nll
from prometheus.recessionnet.training import EarlyStoppedModel, train_classifier_with_early_stopping


def train_flattened_candidate_with_early_stopping(
    model_factory: Callable[[], nn.Module],
    train_features: np.ndarray,
    train_targets: np.ndarray,
    validation_features: np.ndarray,
    validation_targets: np.ndarray,
    *,
    seed: int,
    max_epochs: int,
    patience: int,
    learning_rate: float = 0.05,
) -> EarlyStoppedModel:
    """Trains `model_factory()` (`LinearRegressionModel`,
    `ClassicalMatchedRegressor`, or `HybridQuantumRegressor`, each
    parameterized only by `input_dim`) on the SAME flat (window *
    n_series * 2)-wide feature layout `inflationcast.data` builds --
    an unmodified call into
    `recessionnet.training.train_classifier_with_early_stopping` with
    `loss_fn=nn.MSELoss()` and an identity `output_transform`, the
    exact composition Q-MACRO (`macrocore.quantum_benchmark`) already
    relies on for its own regression candidates. No new training-loop
    code for these three candidates."""
    return train_classifier_with_early_stopping(
        model_factory,
        train_features,
        train_targets,
        validation_features,
        validation_targets,
        seed=seed,
        max_epochs=max_epochs,
        patience=patience,
        learning_rate=learning_rate,
        loss_fn=nn.MSELoss(),
        output_transform=lambda t: t,
    )


@dataclass(frozen=True, slots=True)
class EpochLogEntry:
    epoch: int
    loss: float


@dataclass(frozen=True, slots=True)
class TrainedInflationGRU:
    model: InflationGRU
    epoch_log: tuple[EpochLogEntry, ...]
    selected_epoch: int
    best_validation_nll: float
    seed: int
    n_parameters: int
    train_seconds: float


def train_inflation_gru_with_early_stopping(
    train_features: np.ndarray,
    train_targets: np.ndarray,
    validation_features: np.ndarray,
    validation_targets: np.ndarray,
    *,
    n_series: int,
    seed: int,
    max_epochs: int,
    patience: int,
    hidden_size: int = 24,
    learning_rate: float = 0.01,
) -> TrainedInflationGRU:
    """`train_features`/`validation_features` have shape (n_examples,
    window * n_series * 2) -- the SAME flat layout `inflationcast.data`
    builds for every other candidate -- reshaped here to (n_examples,
    window, 2 * n_series) for the GRU; `window` is inferred from the
    flat width so callers never have to pass it redundantly."""
    if max_epochs < 1:
        raise ValueError("max_epochs must be a positive integer")
    if patience < 1:
        raise ValueError("patience must be a positive integer")
    if train_features.shape[0] != train_targets.shape[0]:
        raise ValueError("train_features and train_targets must have the same number of rows")
    if validation_features.shape[0] != validation_targets.shape[0]:
        raise ValueError(
            "validation_features and validation_targets must have the same number of rows"
        )
    if validation_features.shape[0] == 0:
        raise ValueError("validation set must be non-empty")
    flat_width = train_features.shape[1]
    if flat_width % (2 * n_series) != 0:
        raise ValueError("feature width is not a whole number of (window * n_series * 2) slots")
    window = flat_width // (2 * n_series)

    def reshape(features: np.ndarray) -> torch.Tensor:
        return torch.tensor(
            features.reshape(features.shape[0], window, 2 * n_series), dtype=torch.float32
        )

    train_x, validation_x = reshape(train_features), reshape(validation_features)
    train_y = torch.tensor(train_targets, dtype=torch.float32)
    validation_y = torch.tensor(validation_targets, dtype=torch.float32)

    torch.manual_seed(seed)
    model = InflationGRU(n_series=n_series, hidden_size=hidden_size)
    optimizer = torch.optim.Adam(model.parameters(), lr=learning_rate)

    epoch_log: list[EpochLogEntry] = []
    best_state: dict[str, torch.Tensor] | None = None
    best_validation_nll = float("inf")
    best_epoch = -1
    epochs_since_improvement = 0
    start = time.perf_counter()

    for epoch in range(max_epochs):
        model.train()
        optimizer.zero_grad()
        mean, log_var = model(train_x)
        loss = gaussian_nll(mean, log_var, train_y)
        loss.backward()  # type: ignore[no-untyped-call]
        optimizer.step()
        epoch_log.append(EpochLogEntry(epoch=epoch, loss=float(loss.item())))

        model.eval()
        with torch.no_grad():
            val_mean, val_log_var = model(validation_x)
            validation_nll = float(gaussian_nll(val_mean, val_log_var, validation_y).item())

        if validation_nll < best_validation_nll:
            best_validation_nll = validation_nll
            best_epoch = epoch
            best_state = copy.deepcopy(model.state_dict())
            epochs_since_improvement = 0
        else:
            epochs_since_improvement += 1
            if epochs_since_improvement >= patience:
                break

    if best_state is not None:
        model.load_state_dict(best_state)
    train_seconds = time.perf_counter() - start

    return TrainedInflationGRU(
        model=model,
        epoch_log=tuple(epoch_log),
        selected_epoch=best_epoch,
        best_validation_nll=best_validation_nll,
        seed=seed,
        n_parameters=model.count_parameters(),
        train_seconds=train_seconds,
    )
