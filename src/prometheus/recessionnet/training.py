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
"""

from __future__ import annotations

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
