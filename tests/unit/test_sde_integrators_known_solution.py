"""The repository's SDE integrators against a case with a known solution (audit item M-01).

Geometric Brownian motion dX = mu X dt + s X dW has the exact solution
X_T = X_0 exp((mu - s^2/2) T + s W_T) and E[X_T] = X_0 exp(mu T). A stand-in model with that drift
and diffusion runs through the repository's `simulate_euler_maruyama` and `simulate_stochastic_heun`
unchanged. Two things are measured:

- STRONG error, E|X_T(scheme) - X_T(exact)| on the SAME Brownian path: the generator that drives the
  scheme is replayed to rebuild W_T, so the comparison is pathwise. Both schemes treat the noise the
  Euler way, so both should converge at strong order 1/2 (measured 0.486 and 0.489).
- the MEAN of the scheme against the closed form of what the scheme computes (per step the mean
  multiplies by 1 + mu dt for Euler-Maruyama and 1 + mu dt + (mu dt)^2/2 for the drift-corrected
  scheme), and against the exact mean: the corrected scheme is far closer to it (weak order about 2
  in the mean against 1).

The last test pins what the first two imply: the two schemes' pathwise errors are almost the same
(the diffusion term is untouched by the drift correction) while their errors in the mean differ by
an order of magnitude.
"""

from __future__ import annotations

import numpy as np
import pytest
import torch
from torch import nn

from prometheus.neural_sde.integration import simulate_euler_maruyama, simulate_stochastic_heun

SCHEMES = {
    "euler_maruyama": (simulate_euler_maruyama, lambda mu_dt: 1.0 + mu_dt),
    "stochastic_heun": (simulate_stochastic_heun, lambda mu_dt: 1.0 + mu_dt + 0.5 * mu_dt**2),
}


class _Gbm(nn.Module):
    """The integrators' interface: `state_dim`, and forward(t, x, regime) -> (drift, Sigma)."""

    state_dim = 1

    def __init__(self, mu: float, s: float) -> None:
        super().__init__()
        self.mu, self.s = mu, s

    def forward(self, t: torch.Tensor, x: torch.Tensor, regime: torch.Tensor):  # type: ignore[no-untyped-def]
        return self.mu * x, ((self.s * x) ** 2).unsqueeze(-1)


def _run(name: str, mu: float, s: float, n_steps: int, n_paths: int, seed: int):  # type: ignore[no-untyped-def]
    scheme = SCHEMES[name][0]
    x0 = torch.ones(n_paths, 1, dtype=torch.float64)
    regime = torch.zeros(n_steps, 1, dtype=torch.float64)
    path = scheme(_Gbm(mu, s), x0, 0.0, 1.0 / n_steps, regime, torch.Generator().manual_seed(seed))
    return path[:, -1, 0]


def _exact_terminal(mu: float, s: float, n_steps: int, n_paths: int, seed: int) -> torch.Tensor:
    """X_T from the Brownian path the scheme saw: replay its generator, one normal per step."""
    replay = torch.Generator().manual_seed(seed)
    w = sum(torch.randn(n_paths, 1, generator=replay, dtype=torch.float64) for _ in range(n_steps))
    return torch.exp((mu - 0.5 * s * s) + s * w[:, 0] / n_steps**0.5)


def _strong_errors(name: str, steps: list[int], seed: int) -> list[float]:
    out = []
    for n in steps:
        numerical = _run(name, 0.05, 0.4, n, 30_000, seed)
        out.append(float((numerical - _exact_terminal(0.05, 0.4, n, 30_000, seed)).abs().mean()))
    return out


@pytest.mark.parametrize("name", list(SCHEMES))
def test_the_strong_order_is_one_half_on_geometric_brownian_motion(name: str) -> None:
    steps = [4, 8, 16, 32, 64]
    slopes = []
    for seed in (1, 101, 201):
        errors = _strong_errors(name, steps, seed)
        assert errors == sorted(errors, reverse=True)
        slopes.append(np.polyfit(np.log([1.0 / n for n in steps]), np.log(errors), 1)[0])
    assert float(np.mean(slopes)) == pytest.approx(0.5, abs=0.07)
    assert float(np.std(slopes, ddof=1)) < 0.05  # the estimate does not depend on the seed


@pytest.mark.parametrize("name", list(SCHEMES))
def test_the_mean_of_each_scheme_equals_the_closed_form_of_what_it_computes(name: str) -> None:
    mu, s, n_paths = 1.5, 0.3, 400_000
    factor = SCHEMES[name][1]
    for n in (2, 4, 8, 16):
        terminal = _run(name, mu, s, n, n_paths, seed=7 + n).numpy()
        standard_error = terminal.std(ddof=1) / np.sqrt(n_paths)
        expected = factor(mu / n) ** n
        assert abs(terminal.mean() - expected) < 4.0 * standard_error, (name, n)


def test_the_corrected_scheme_is_far_closer_in_the_mean_yet_no_closer_pathwise() -> None:
    mu, s, exact_mean, n_paths = 1.5, 0.3, float(np.exp(1.5)), 400_000
    bias = {
        name: [
            abs(_run(name, mu, s, n, n_paths, 7 + n).numpy().mean() - exact_mean) for n in (8, 16)
        ]
        for name in SCHEMES
    }
    em, heun = bias["euler_maruyama"], bias["stochastic_heun"]
    assert all(
        h < e / 5.0 for h, e in zip(heun, em, strict=True)
    )  # measured: about 15x and 25x smaller
    assert 1.6 < em[0] / em[1] < 2.1  # Euler-Maruyama's bias halves with the step: first order
    strong = {name: _strong_errors(name, [16], seed=1)[0] for name in SCHEMES}
    assert strong["stochastic_heun"] == pytest.approx(strong["euler_maruyama"], rel=0.05)
