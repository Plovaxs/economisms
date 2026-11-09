import pytest
import torch

from prometheus.neural_sde.integration import simulate_euler_maruyama, simulate_stochastic_heun
from prometheus.neural_sde.model import DriftDiffusionNet


def test_gradcheck_on_a_toy_low_dimensional_case() -> None:
    """NSD-02: "autograd gradient finite and numerically consistent on
    toy cases" -- `torch.autograd.gradcheck` compares the analytic
    (autograd) Jacobian against a finite-difference approximation and
    raises if they disagree beyond its tolerance. Requires float64
    (gradcheck's finite-difference step is too coarse for float32)."""
    torch.manual_seed(0)
    model = DriftDiffusionNet(state_dim=1, regime_dim=1, hidden_size=4).double()
    t = torch.rand(3, 1, dtype=torch.float64, requires_grad=True)
    state = torch.randn(3, 1, dtype=torch.float64, requires_grad=True)
    regime = torch.randn(3, 1, dtype=torch.float64, requires_grad=True)

    def forward_drift_and_trace_sigma(
        t_: torch.Tensor, state_: torch.Tensor, regime_: torch.Tensor
    ) -> torch.Tensor:
        drift, sigma = model(t_, state_, regime_)
        return torch.cat([drift, torch.diagonal(sigma, dim1=-2, dim2=-1)], dim=-1)

    assert torch.autograd.gradcheck(
        forward_drift_and_trace_sigma, (t, state, regime), eps=1e-6, atol=1e-4
    )


def test_gradients_flow_finite_through_a_multi_step_simulated_path() -> None:
    torch.manual_seed(1)
    model = DriftDiffusionNet(state_dim=2, regime_dim=2, hidden_size=8)
    x0 = torch.zeros(5, 2, requires_grad=False)
    regime_path = torch.randn(6, 2)
    generator = torch.Generator().manual_seed(0)

    path = simulate_euler_maruyama(model, x0, 0.0, 1.0, regime_path, generator)
    assert path.shape == (5, 7, 2)
    assert torch.all(torch.isfinite(path))

    loss = path[:, -1, :].pow(2).sum()
    loss.backward()
    for param in model.parameters():
        assert param.grad is not None
        assert torch.all(torch.isfinite(param.grad))


def test_euler_and_heun_agree_closely_at_a_small_time_step() -> None:
    """Both schemes converge to the same SDE as dt -> 0; at a small
    shared dt and the SAME noise draws (same seed, same generator
    construction), their paths should be close, not merely the same
    shape -- a sanity check that `simulate_stochastic_heun` is a real
    perturbation of Euler-Maruyama, not a disconnected implementation."""
    torch.manual_seed(2)
    model = DriftDiffusionNet(state_dim=1, regime_dim=1, hidden_size=8)
    x0 = torch.full((10, 1), 0.5)
    regime_path = torch.zeros(20, 1)

    euler_path = simulate_euler_maruyama(
        model, x0, 0.0, 0.01, regime_path, torch.Generator().manual_seed(7)
    )
    heun_path = simulate_stochastic_heun(
        model, x0, 0.0, 0.01, regime_path, torch.Generator().manual_seed(7)
    )
    assert torch.allclose(euler_path[:, -1, :], heun_path[:, -1, :], atol=0.05)


def test_simulate_rejects_non_positive_dt() -> None:
    model = DriftDiffusionNet(state_dim=1, regime_dim=1)
    x0 = torch.zeros(2, 1)
    regime_path = torch.zeros(3, 1)
    generator = torch.Generator().manual_seed(0)

    with pytest.raises(ValueError, match="dt_scaled"):
        simulate_euler_maruyama(model, x0, 0.0, 0.0, regime_path, generator)
    with pytest.raises(ValueError, match="dt_scaled"):
        simulate_stochastic_heun(model, x0, 0.0, -1.0, regime_path, generator)


def test_euler_maruyama_is_deterministic_given_the_same_generator_seed() -> None:
    torch.manual_seed(3)
    model = DriftDiffusionNet(state_dim=1, regime_dim=1, hidden_size=4)
    x0 = torch.zeros(4, 1)
    regime_path = torch.randn(5, 1)

    path_a = simulate_euler_maruyama(
        model, x0, 0.0, 1.0, regime_path, torch.Generator().manual_seed(42)
    )
    path_b = simulate_euler_maruyama(
        model, x0, 0.0, 1.0, regime_path, torch.Generator().manual_seed(42)
    )
    assert torch.equal(path_a, path_b)
