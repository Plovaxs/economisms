"""NSD-13: "Register model version, training range and limitations --
Reproducible model card with environmental dependencies."

`model_card_from_trained_model` builds a `ModelCard` directly from a
`TrainedNeuralSDE` and the `TransitionExample`s it was trained on, so
the training range is read from the data actually used (the first and
last `decision_time` in the training split), not hand-typed and liable
to drift out of sync. `sys.version`/`torch.__version__`/`np.__version__`
are captured at card-creation time, matching this repository's own
running environment -- "reproducible" here means another run in an
environment with the same recorded versions and the same `seed` can be
expected to reproduce this training run, not that the card embeds a
cryptographic reproducibility proof.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from datetime import UTC, date, datetime

import numpy as np
import torch

from prometheus.neural_sde.dataset import TransitionExample
from prometheus.neural_sde.design import NeuralSDEDesignSpec
from prometheus.neural_sde.training import TrainedNeuralSDE

MODEL_VERSION = "neural-sde-v1"

KNOWN_LIMITATIONS: tuple[str, ...] = (
    "trained on ~40 years of MONTHLY observations (a few hundred rows) -- "
    "too little data to support a high-capacity architecture, hence the "
    "deliberately small hidden_size used throughout this package",
    "regime features (KAGGLE_FEDFUNDS/CLAIMS_YOY/M2_YOY) are treated as "
    "exogenous/observed, not themselves modeled as stochastic -- a joint "
    "model of regime evolution is out of scope",
    "the diffusion covariance is state- and time-dependent but has no "
    "explicit mean-reversion term the way Heston's CIR variance process "
    "does -- nothing prevents the network from learning an "
    "unconditionally explosive-feeling (though always architecturally "
    "bounded, see neural_sde.model) diffusion surface in regions far "
    "from the training data's support",
    "evaluated against one real out-of-distribution event (the 2020 "
    "COVID window, neural_sde.ood) -- this is one data point about OOD "
    "behavior, not a general OOD guarantee",
    "the GARCH/AR1/persistence baselines in neural_sde.benchmark are "
    "univariate-only or structurally simplified (see that module's own "
    "docstring) -- they are comparison points, not independently "
    "production-grade models",
)


@dataclass(frozen=True, slots=True)
class ModelCard:
    model_version: str
    seed: int
    n_parameters: int
    selected_epoch: int
    best_validation_nll: float
    training_range_start: date
    training_range_end: date
    n_training_examples: int
    state_series_ids: tuple[str, ...]
    regime_series_ids: tuple[str, ...]
    limitations: tuple[str, ...]
    python_version: str
    torch_version: str
    numpy_version: str
    created_at: str


def model_card_from_trained_model(
    trained: TrainedNeuralSDE,
    train_examples: list[TransitionExample],
    spec: NeuralSDEDesignSpec,
) -> ModelCard:
    if len(train_examples) == 0:
        raise ValueError("train_examples must be non-empty")
    decision_times = [e.decision_time for e in train_examples]
    return ModelCard(
        model_version=MODEL_VERSION,
        seed=trained.seed,
        n_parameters=trained.n_parameters,
        selected_epoch=trained.selected_epoch,
        best_validation_nll=trained.best_validation_nll,
        training_range_start=min(decision_times),
        training_range_end=max(decision_times),
        n_training_examples=len(train_examples),
        state_series_ids=spec.state_series_ids,
        regime_series_ids=spec.regime_series_ids,
        limitations=KNOWN_LIMITATIONS,
        python_version=sys.version.split()[0],
        torch_version=torch.__version__,
        numpy_version=np.__version__,
        created_at=datetime.now(UTC).isoformat(),
    )
