"""NSD-12: "Test exploding/vanishing gradients and numerical NaNs --
Training automatically fails on loss/state integrity violations."

`train_neural_sde` fits the model by maximizing the Gaussian transition
log-likelihood implied by one Euler-Maruyama step (the same density the
discretization in `neural_sde.integration.simulate_euler_maruyama`
samples from): given (t, X_t, regime_t) -> (mu, Sigma) from the network,
X_{t+dt} - X_t - mu*dt is modeled as N(0, Sigma*dt). This is a genuinely
different loss shape from `recessionnet.training`'s classification/
regression loop (a path-density negative log-likelihood, not a label
MSE/BCE), so a new loop is written here -- but `EpochLogEntry` is
imported and reused as-is from `recessionnet.training`: it is a plain
(epoch, loss) record with nothing classification-specific in it, so a
second near-identical dataclass would be duplication, not a needed
"NSD is different" distinction.

Every epoch, after `loss.backward()`, `_check_integrity` requires BOTH
the loss value and every parameter's gradient to be finite; the first
violation raises `TrainingIntegrityError` immediately (naming the epoch
and which tensor failed) rather than letting `optimizer.step()` apply a
NaN/Inf update that would silently poison every subsequent epoch.
`test_neural_sde_training.py` exercises this two ways: (1) directly
injecting a NaN into a trained model's own parameter before one more
training call, the deterministic case; (2) an engineered exploding
configuration (an unreasonably large learning rate on this small a
network/dataset) that organically produces a non-finite loss within a
few epochs, the "this isn't just checking what we injected" case.
"""

from __future__ import annotations

import copy
import time
from dataclasses import dataclass

import numpy as np
import torch

from prometheus.neural_sde.dataset import FittedScaler, TransitionExample
from prometheus.neural_sde.model import DriftDiffusionNet
from prometheus.quantum.models import count_parameters
from prometheus.recessionnet.training import EpochLogEntry

DT_SCALED = 1.0
"""One Euler-Maruyama step per monthly transition -- matches
`neural_sde.design.DEFAULT_DESIGN_SPEC.time_unit` ("months, dt=1.0")."""


class TrainingIntegrityError(RuntimeError):
    """Raised by `_check_integrity` the first epoch a loss or gradient
    is found to be non-finite -- training stops immediately rather than
    continuing to apply a corrupted update."""


def _check_integrity(model: torch.nn.Module, loss: torch.Tensor, epoch: int) -> None:
    if not torch.isfinite(loss):
        raise TrainingIntegrityError(f"epoch {epoch}: loss is non-finite ({loss.item()!r})")
    for name, param in model.named_parameters():
        if param.grad is not None and not torch.all(torch.isfinite(param.grad)):
            raise TrainingIntegrityError(
                f"epoch {epoch}: gradient of parameter {name!r} contains NaN/Inf"
            )


def _examples_to_tensors(
    examples: list[TransitionExample], state_scaler: FittedScaler, regime_scaler: FittedScaler
) -> tuple[torch.Tensor, torch.Tensor, torch.Tensor, torch.Tensor]:
    t_scaled = torch.tensor([[e.t_scaled] for e in examples], dtype=torch.float32)
    state = torch.tensor(
        state_scaler.transform(np.array([e.state for e in examples])), dtype=torch.float32
    )
    regime = torch.tensor(
        regime_scaler.transform(np.array([e.regime for e in examples])), dtype=torch.float32
    )
    next_state = torch.tensor(
        state_scaler.transform(np.array([e.next_state for e in examples])), dtype=torch.float32
    )
    return t_scaled, state, regime, next_state


def gaussian_transition_nll(
    model: DriftDiffusionNet,
    t_scaled: torch.Tensor,
    state: torch.Tensor,
    regime: torch.Tensor,
    next_state: torch.Tensor,
    dt_scaled: float = DT_SCALED,
) -> torch.Tensor:
    """Mean negative log-likelihood of `next_state` under N(state +
    mu*dt, Sigma*dt), batched. This IS the log score NSD-08 asks a
    proper scoring rule report include -- `neural_sde.scoring` reuses
    this function directly rather than recomputing it a second way."""
    drift, sigma = model(t_scaled, state, regime)
    residual = next_state - state - drift * dt_scaled
    scaled_sigma = sigma * dt_scaled
    k = residual.shape[-1]
    eye = torch.eye(k, dtype=residual.dtype)
    chol = torch.linalg.cholesky(scaled_sigma + 1e-10 * eye)
    z = torch.linalg.solve_triangular(chol, residual.unsqueeze(-1), upper=False).squeeze(-1)
    quadratic = (z**2).sum(dim=-1)
    log_det = 2.0 * torch.log(torch.diagonal(chol, dim1=-2, dim2=-1)).sum(dim=-1)
    nll = 0.5 * (quadratic + log_det + k * float(np.log(2 * np.pi)))
    result: torch.Tensor = nll.mean()
    return result


@dataclass(frozen=True, slots=True)
class TrainedNeuralSDE:
    model: DriftDiffusionNet
    epoch_log: tuple[EpochLogEntry, ...]
    validation_log: tuple[tuple[int, float], ...]
    selected_epoch: int
    best_validation_nll: float
    seed: int
    n_parameters: int
    train_seconds: float
    state_scaler: FittedScaler
    regime_scaler: FittedScaler


def train_neural_sde(
    train_examples: list[TransitionExample],
    validation_examples: list[TransitionExample],
    state_scaler: FittedScaler,
    regime_scaler: FittedScaler,
    *,
    seed: int,
    max_epochs: int,
    patience: int,
    learning_rate: float = 0.01,
    hidden_size: int = 16,
) -> TrainedNeuralSDE:
    if max_epochs < 1:
        raise ValueError("max_epochs must be a positive integer")
    if patience < 1:
        raise ValueError("patience must be a positive integer")
    if len(train_examples) == 0 or len(validation_examples) == 0:
        raise ValueError("train_examples and validation_examples must both be non-empty")

    state_dim = len(train_examples[0].state)
    regime_dim = len(train_examples[0].regime)

    torch.manual_seed(seed)
    model = DriftDiffusionNet(state_dim=state_dim, regime_dim=regime_dim, hidden_size=hidden_size)
    optimizer = torch.optim.Adam(model.parameters(), lr=learning_rate)

    t_train, x_train, r_train, xn_train = _examples_to_tensors(
        train_examples, state_scaler, regime_scaler
    )
    t_val, x_val, r_val, xn_val = _examples_to_tensors(
        validation_examples, state_scaler, regime_scaler
    )

    epoch_log: list[EpochLogEntry] = []
    validation_log: list[tuple[int, float]] = []
    best_validation_nll = float("inf")
    best_state: dict[str, torch.Tensor] | None = None
    best_epoch = -1
    epochs_since_improvement = 0

    start = time.perf_counter()
    for epoch in range(max_epochs):
        optimizer.zero_grad()
        loss = gaussian_transition_nll(model, t_train, x_train, r_train, xn_train)
        loss.backward()  # type: ignore[no-untyped-call]
        _check_integrity(model, loss, epoch)
        optimizer.step()
        epoch_log.append(EpochLogEntry(epoch=epoch, loss=float(loss.item())))

        model.eval()
        with torch.no_grad():
            val_loss = gaussian_transition_nll(model, t_val, x_val, r_val, xn_val)
        model.train()
        validation_score = float(val_loss.item())
        validation_log.append((epoch, validation_score))

        if validation_score < best_validation_nll:
            best_validation_nll = validation_score
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

    return TrainedNeuralSDE(
        model=model,
        epoch_log=tuple(epoch_log),
        validation_log=tuple(validation_log),
        selected_epoch=best_epoch,
        best_validation_nll=best_validation_nll,
        seed=seed,
        n_parameters=count_parameters(model),
        train_seconds=train_seconds,
        state_scaler=state_scaler,
        regime_scaler=regime_scaler,
    )
