from datetime import date, timedelta

import numpy as np
import pytest
import torch

from prometheus.neural_sde.dataset import FittedScaler, TransitionExample, fit_scaler
from prometheus.neural_sde.model import DriftDiffusionNet
from prometheus.neural_sde.training import (
    TrainingIntegrityError,
    _check_integrity,
    gaussian_transition_nll,
    train_neural_sde,
)


def test_gaussian_transition_nll_matches_closed_form_standard_normal_case() -> None:
    """With drift=0 and Sigma=I*dt (achieved by zeroing the network's
    weights by construction, then checking what the untrained net's
    bias-only output implies) the NLL reduces to the standard
    multivariate Gaussian formula: 0.5*(||z||^2 + k*log(2*pi)) with
    z = residual (since Sigma=I). We instead verify the identity
    directly against hand-computed scipy-free arithmetic for a tensor
    constructed to have a KNOWN residual and a KNOWN (identity)
    covariance, bypassing the network entirely via a tiny stand-in
    module."""

    class _IdentityDiffusionConstantDrift(torch.nn.Module):
        def __init__(self, state_dim: int) -> None:
            super().__init__()
            self.state_dim = state_dim

        def forward(self, t, state, regime):  # noqa: ANN001
            batch = state.shape[0]
            drift = torch.zeros(batch, self.state_dim)
            sigma = torch.eye(self.state_dim).unsqueeze(0).expand(batch, -1, -1)
            return drift, sigma

    model = _IdentityDiffusionConstantDrift(state_dim=2)
    t = torch.zeros(3, 1)
    state = torch.zeros(3, 2)
    regime = torch.zeros(3, 1)
    next_state = torch.tensor([[1.0, 0.0], [0.0, 2.0], [1.0, 1.0]])

    nll = gaussian_transition_nll(model, t, state, regime, next_state, dt_scaled=1.0)

    residuals = next_state  # drift=0, state=0
    quadratic = (residuals**2).sum(dim=-1)
    expected = (0.5 * (quadratic + 2 * torch.log(torch.tensor(2 * torch.pi)))).mean()
    assert nll.item() == pytest.approx(expected.item(), abs=1e-5)


def _toy_examples(n: int, state_dim: int = 1, regime_dim: int = 1) -> list[TransitionExample]:
    base = date(2000, 1, 1)
    examples = []
    for i in range(n):
        examples.append(
            TransitionExample(
                t_scaled=float(i),
                state=tuple(float(i + d) for d in range(state_dim)),
                regime=tuple(float(i * 0.1 + d) for d in range(regime_dim)),
                next_state=tuple(float(i + 1 + d) for d in range(state_dim)),
                decision_time=base + timedelta(days=30 * i),
                next_time=base + timedelta(days=30 * (i + 1)),
            )
        )
    return examples


def test_train_neural_sde_runs_and_returns_a_populated_result() -> None:
    train_examples = _toy_examples(30)
    validation_examples = _toy_examples(10)
    state_scaler = fit_scaler(np.array([e.state for e in train_examples]))
    regime_scaler = fit_scaler(np.array([e.regime for e in train_examples]))

    result = train_neural_sde(
        train_examples,
        validation_examples,
        state_scaler,
        regime_scaler,
        seed=0,
        max_epochs=15,
        patience=5,
    )
    assert len(result.epoch_log) <= 15
    assert len(result.epoch_log) == len(result.validation_log)
    assert result.selected_epoch >= 0
    assert result.n_parameters > 0
    assert isinstance(result.model, DriftDiffusionNet)


def test_train_neural_sde_rejects_empty_splits() -> None:
    examples = _toy_examples(5)
    scaler = FittedScaler(mean=(0.0,), std=(1.0,))
    with pytest.raises(ValueError, match="non-empty"):
        train_neural_sde([], examples, scaler, scaler, seed=0, max_epochs=5, patience=2)
    with pytest.raises(ValueError, match="non-empty"):
        train_neural_sde(examples, [], scaler, scaler, seed=0, max_epochs=5, patience=2)


# -- NSD-12: integrity checks -------------------------------------------
#
# The architecture is deliberately overflow-resistant by construction
# (neural_sde.model's bounded tanh/sigmoid squashing -- see that
# module's NSD-04 docstring): tanh/sigmoid of even an astronomically
# large FINITE pre-activation is still a finite, bounded output, so an
# "organic" explosion (e.g. via a pathologically large learning rate)
# is hard to trigger from finite inputs by design, which is itself a
# second piece of evidence the NSD-04 bound is doing its job, not a gap
# in this test. `_check_integrity` is therefore exercised directly with
# deterministic fault injection -- a non-finite loss, and a non-finite
# gradient -- rather than a hyperparameter search for an organic failure.


def test_check_integrity_raises_on_non_finite_loss() -> None:
    model = DriftDiffusionNet(state_dim=1, regime_dim=1)
    with pytest.raises(TrainingIntegrityError, match="non-finite"):
        _check_integrity(model, torch.tensor(float("nan")), epoch=3)
    with pytest.raises(TrainingIntegrityError, match="non-finite"):
        _check_integrity(model, torch.tensor(float("inf")), epoch=3)


def test_check_integrity_raises_on_non_finite_gradient() -> None:
    model = DriftDiffusionNet(state_dim=1, regime_dim=1)
    first_param = next(model.parameters())
    first_param.grad = torch.full_like(first_param, float("nan"))
    with pytest.raises(TrainingIntegrityError, match="gradient"):
        _check_integrity(model, torch.tensor(0.5), epoch=0)


def test_check_integrity_passes_on_a_healthy_step() -> None:
    model = DriftDiffusionNet(state_dim=1, regime_dim=1)
    for param in model.parameters():
        param.grad = torch.zeros_like(param)
    _check_integrity(model, torch.tensor(1.23), epoch=0)  # must not raise


def test_a_nan_parameter_is_caught_by_the_models_own_output_guard() -> None:
    """A NaN PARAMETER (as opposed to a NaN input, covered by
    `test_neural_sde_model.py`) is not caught by
    `DriftDiffusionNet`'s input guard -- it flows silently through
    tanh/sigmoid (both pass NaN through unchanged, unlike their
    behavior at actual infinity) into a corrupted drift/sigma. The
    model's OUTPUT guard (added specifically for this) is what makes
    this raise instead of silently returning a NaN-valued model output
    that `_check_integrity` would otherwise have to catch one step
    later, after an unnecessary `.backward()` call."""
    torch.manual_seed(0)
    model = DriftDiffusionNet(state_dim=1, regime_dim=1, hidden_size=4)
    with torch.no_grad():
        next(model.parameters()).fill_(float("nan"))

    t = torch.zeros(4, 1)
    state = torch.zeros(4, 1)
    regime = torch.zeros(4, 1)
    with pytest.raises(ValueError, match="NaN or Inf"):
        model(t, state, regime)


def test_check_integrity_catches_a_corrupted_gradient_after_a_real_backward_pass() -> None:
    """The realistic failure path `train_neural_sde` actually exercises:
    a real forward+backward pass, then a gradient corrupted (standing in
    for whatever produced the corruption -- an exploding update, bad
    data, etc.), caught by `_check_integrity`, the exact function the
    training loop calls every epoch."""
    torch.manual_seed(0)
    model = DriftDiffusionNet(state_dim=1, regime_dim=1, hidden_size=4)
    t = torch.zeros(4, 1)
    state = torch.zeros(4, 1)
    regime = torch.zeros(4, 1)

    loss = model(t, state, regime)[0].sum()
    loss.backward()
    with torch.no_grad():
        next(model.parameters()).grad.fill_(float("nan"))
    with pytest.raises(TrainingIntegrityError):
        _check_integrity(model, loss, epoch=0)
