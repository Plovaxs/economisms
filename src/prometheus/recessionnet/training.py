"""Training loop shared by every RECESSIONNET candidate architecture
(base rate excepted -- it has no parameters to train). Full-batch Adam
on `nn.BCEWithLogitsLoss`: the datasets built by `recessionnet.dataset`
are a few hundred to a couple of thousand monthly samples, small
enough that mini-batching would add complexity (a `DataLoader`,
shuffling, an extra RNG stream to seed) without changing the result in
any way that matters for this comparison.

Mirrors `hedging.deep_hedge.train_deep_hedge`'s own MLO-05 "epoch log
contains step/epoch metadata" convention (`epoch_log` of per-epoch
loss values) for the same reason: a benchmark report should be able to
show a learning curve, not just a final number.

`train_classifier_with_early_stopping` exists because a real
diagnostic run of `train_classifier` on RECESSIONNET's actual data
(PR-142) found the hybrid quantum classifier's held-out test Brier
score bottoming out around epoch 20-60 and then degrading steadily
through epoch 500 while its OWN training loss kept falling toward
zero -- textbook overfitting from a higher-parameter-count model
(493 params) with no capacity control, not a quantum-specific
pathology (no vanishing-gradient plateau was observed: training loss
decreased smoothly and monotonically the entire run). Picking a fixed
epoch count and reporting whichever number it lands on is not a fair
comparison once one candidate overfits and another does not; model
selection by a held-out VALIDATION set (never the test set itself,
which would be exactly the leakage this project's whole `econosim.pit`
discipline exists to prevent) is the standard, honest fix.
"""

from __future__ import annotations

import copy
import time
from collections.abc import Callable
from dataclasses import dataclass

import numpy as np
import torch
from torch import nn

from prometheus.quantum.models import count_parameters


@dataclass(frozen=True, slots=True)
class EpochLogEntry:
    epoch: int
    loss: float


@dataclass(frozen=True, slots=True)
class TrainedModel:
    model: nn.Module
    epoch_log: tuple[EpochLogEntry, ...]
    seed: int
    n_parameters: int
    train_seconds: float


def train_classifier(
    model_factory: Callable[[], nn.Module],
    features: np.ndarray,
    labels: np.ndarray,
    *,
    seed: int,
    n_epochs: int,
    learning_rate: float = 0.05,
) -> TrainedModel:
    if n_epochs < 1:
        raise ValueError("n_epochs must be a positive integer")
    if features.shape[0] != labels.shape[0]:
        raise ValueError("features and labels must have the same number of rows")

    torch.manual_seed(seed)
    model = model_factory()
    optimizer = torch.optim.Adam(model.parameters(), lr=learning_rate)
    loss_fn = nn.BCEWithLogitsLoss()

    x = torch.tensor(features, dtype=torch.float32)
    y = torch.tensor(labels, dtype=torch.float32)

    epoch_log: list[EpochLogEntry] = []
    start = time.perf_counter()
    for epoch in range(n_epochs):
        optimizer.zero_grad()
        logits = model(x)
        loss = loss_fn(logits, y)
        loss.backward()
        optimizer.step()
        epoch_log.append(EpochLogEntry(epoch=epoch, loss=float(loss.item())))
    train_seconds = time.perf_counter() - start

    return TrainedModel(
        model=model,
        epoch_log=tuple(epoch_log),
        seed=seed,
        n_parameters=count_parameters(model),
        train_seconds=train_seconds,
    )


@dataclass(frozen=True, slots=True)
class EarlyStoppedModel:
    model: nn.Module
    """Restored to its state_dict AT `selected_epoch`, not the final
    epoch trained -- the whole point of early stopping."""
    epoch_log: tuple[EpochLogEntry, ...]
    """Training loss for every epoch actually run (stops early if
    `patience` epochs pass with no validation improvement)."""
    validation_log: tuple[tuple[int, float], ...]
    """(epoch, validation_brier_score) for every epoch actually run."""
    selected_epoch: int
    best_validation_brier: float
    seed: int
    n_parameters: int
    train_seconds: float


def train_classifier_with_early_stopping(
    model_factory: Callable[[], nn.Module],
    train_features: np.ndarray,
    train_labels: np.ndarray,
    validation_features: np.ndarray,
    validation_labels: np.ndarray,
    *,
    seed: int,
    max_epochs: int,
    patience: int,
    learning_rate: float = 0.05,
) -> EarlyStoppedModel:
    """Trains on (train_features, train_labels); after every epoch,
    scores the CURRENT model on (validation_features, validation_labels)
    by Brier score and checkpoints it if that is the best validation
    score seen so far. Stops once `patience` consecutive epochs pass
    with no improvement, or at `max_epochs`, whichever comes first.
    Returns the model restored to its best-validation checkpoint, never
    whatever state training happened to end on."""
    if max_epochs < 1:
        raise ValueError("max_epochs must be a positive integer")
    if patience < 1:
        raise ValueError("patience must be a positive integer")
    if train_features.shape[0] != train_labels.shape[0]:
        raise ValueError("train_features and train_labels must have the same number of rows")
    if validation_features.shape[0] != validation_labels.shape[0]:
        raise ValueError(
            "validation_features and validation_labels must have the same number of rows"
        )
    if validation_features.shape[0] == 0:
        raise ValueError("validation set must be non-empty")

    torch.manual_seed(seed)
    model = model_factory()
    optimizer = torch.optim.Adam(model.parameters(), lr=learning_rate)
    loss_fn = nn.BCEWithLogitsLoss()

    x_train = torch.tensor(train_features, dtype=torch.float32)
    y_train = torch.tensor(train_labels, dtype=torch.float32)
    x_val = torch.tensor(validation_features, dtype=torch.float32)
    y_val = np.asarray(validation_labels, dtype=float)

    epoch_log: list[EpochLogEntry] = []
    validation_log: list[tuple[int, float]] = []
    best_validation_brier = float("inf")
    best_state: dict[str, torch.Tensor] | None = None
    best_epoch = -1
    epochs_since_improvement = 0

    start = time.perf_counter()
    for epoch in range(max_epochs):
        optimizer.zero_grad()
        loss = loss_fn(model(x_train), y_train)
        loss.backward()
        optimizer.step()
        epoch_log.append(EpochLogEntry(epoch=epoch, loss=float(loss.item())))

        model.eval()
        with torch.no_grad():
            validation_probs = torch.sigmoid(model(x_val)).numpy()
        model.train()
        validation_brier = float(np.mean((validation_probs - y_val) ** 2))
        validation_log.append((epoch, validation_brier))

        if validation_brier < best_validation_brier:
            best_validation_brier = validation_brier
            best_state = copy.deepcopy(model.state_dict())
            best_epoch = epoch
            epochs_since_improvement = 0
        else:
            epochs_since_improvement += 1
            if epochs_since_improvement >= patience:
                break
    train_seconds = time.perf_counter() - start

    if best_state is None:
        raise RuntimeError("no epoch completed despite max_epochs >= 1 -- this is a bug")
    model.load_state_dict(best_state)

    return EarlyStoppedModel(
        model=model,
        epoch_log=tuple(epoch_log),
        validation_log=tuple(validation_log),
        selected_epoch=best_epoch,
        best_validation_brier=best_validation_brier,
        seed=seed,
        n_parameters=count_parameters(model),
        train_seconds=train_seconds,
    )
