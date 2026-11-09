import numpy as np
import pytest
import torch

from prometheus.neural_sde.model import (
    DIFFUSION_SCALE,
    DRIFT_BOUND,
    MIN_DIFFUSION_DIAGONAL,
    DriftDiffusionNet,
)

_EIGENVALUE_TOLERANCE = -1e-6


def _random_inputs(batch: int, state_dim: int, regime_dim: int, scale: float = 1.0) -> tuple:
    torch.manual_seed(0)
    t = torch.rand(batch, 1) * scale
    state = torch.randn(batch, state_dim) * scale
    regime = torch.randn(batch, regime_dim) * scale
    return t, state, regime


@pytest.mark.parametrize("state_dim,regime_dim", [(1, 0), (1, 3), (2, 3), (3, 2)])
def test_sigma_is_psd_for_every_random_input(state_dim: int, regime_dim: int) -> None:
    model = DriftDiffusionNet(state_dim=state_dim, regime_dim=regime_dim)
    t, state, regime = _random_inputs(200, state_dim, regime_dim)
    _, sigma = model(t, state, regime)
    eigenvalues = torch.linalg.eigvalsh(sigma).detach().numpy()
    assert np.all(eigenvalues > _EIGENVALUE_TOLERANCE), eigenvalues.min()


def test_sigma_is_symmetric() -> None:
    model = DriftDiffusionNet(state_dim=2, regime_dim=3)
    t, state, regime = _random_inputs(50, 2, 3)
    _, sigma = model(t, state, regime)
    assert torch.allclose(sigma, sigma.transpose(-2, -1), atol=1e-5)


@pytest.mark.parametrize("magnitude", [1e3, 1e6, 1e9])
def test_adversarial_large_finite_inputs_stay_bounded_and_finite(magnitude: float) -> None:
    model = DriftDiffusionNet(state_dim=2, regime_dim=3)
    t, state, regime = _random_inputs(20, 2, 3, scale=magnitude)
    drift, sigma = model(t, state, regime)

    assert torch.all(torch.isfinite(drift))
    assert torch.all(torch.isfinite(sigma))
    assert torch.all(drift.abs() <= DRIFT_BOUND + 1e-4)

    eigenvalues = torch.linalg.eigvalsh(sigma)
    assert torch.all(eigenvalues > _EIGENVALUE_TOLERANCE)
    max_possible_diag = MIN_DIFFUSION_DIAGONAL + DIFFUSION_SCALE
    # trace(Sigma) = sum of squared Cholesky row norms <= state_dim * (sum of
    # bounded L entries)^2 -- loosely bounded via a generous multiple of the
    # per-entry bound rather than a tight analytic constant.
    state_dim = sigma.shape[-1]
    bound = (state_dim * 2) * (max_possible_diag + DIFFUSION_SCALE) ** 2
    assert torch.all(torch.diagonal(sigma, dim1=-2, dim2=-1) <= bound)


def test_nan_input_is_rejected_not_silently_propagated() -> None:
    model = DriftDiffusionNet(state_dim=2, regime_dim=3)
    t, state, regime = _random_inputs(5, 2, 3)
    state[0, 0] = float("nan")
    with pytest.raises(ValueError, match="NaN or Inf"):
        model(t, state, regime)


def test_inf_input_is_rejected_not_silently_propagated() -> None:
    model = DriftDiffusionNet(state_dim=2, regime_dim=3)
    t, state, regime = _random_inputs(5, 2, 3)
    regime[0, 0] = float("inf")
    with pytest.raises(ValueError, match="NaN or Inf"):
        model(t, state, regime)


def test_wrong_trailing_dimension_rejected() -> None:
    model = DriftDiffusionNet(state_dim=2, regime_dim=3)
    t = torch.zeros(4, 1)
    state = torch.zeros(4, 3)
    regime = torch.zeros(4, 3)
    with pytest.raises(ValueError, match="trailing dimension"):
        model(t, state, regime)


def test_state_dim_must_be_positive() -> None:
    with pytest.raises(ValueError, match="state_dim"):
        DriftDiffusionNet(state_dim=0, regime_dim=1)
