"""Candidate architectures for CPI nowcasting.

`NaivePersistence` and the flattened-window `LinearRegressionModel`/
`ClassicalMatchedRegressor`/`HybridQuantumRegressor` (reused UNCHANGED
from `prometheus.quantum.models` -- the same Q-MACRO regression trio,
since nothing in those forward passes is specific to Mkt-RF, only to
"a real-valued regression target from a flat feature vector") give the
classical/hybrid-quantum point-forecast comparison this project's
other two forecasting tasks already use.

`InflationGRU` is the one genuinely NEW architecture class here: a
recurrent (not flattened-MLP) encoder over the real trailing window of
mixed-frequency (value, mask) pairs, producing a CALIBRATED forecast --
a (mean, log-variance) pair, not just a point estimate -- trained by
Gaussian negative log-likelihood (`gaussian_nll`). This is the one
candidate that can be scored on uncertainty calibration as well as
point accuracy (`evaluation.py`'s coverage test), directly answering
the "uncertainty calibration" half of this project's research
question, which RECESSIONNET/Q-MACRO's point-only candidates do not
attempt.
"""

from __future__ import annotations

import math

import torch
from torch import nn

from prometheus.quantum.models import (
    ClassicalMatchedRegressor,
    HybridQuantumRegressor,
    LinearRegressionModel,
)

__all__ = [
    "ClassicalMatchedRegressor",
    "HybridQuantumRegressor",
    "InflationGRU",
    "LinearRegressionModel",
    "NaivePersistence",
    "gaussian_nll",
]


class NaivePersistence:
    """The trivial zero-parameter baseline: nowcast CPI_YOY[M] as
    CPI_YOY[M-1], the most recent real, already-published value. Not an
    `nn.Module` -- it has no parameters to train, so it is applied
    directly to a feature array rather than wrapped in the training
    loop every learned candidate shares."""

    @staticmethod
    def predict(most_recent_known_cpi_yoy: float) -> float:
        return most_recent_known_cpi_yoy


class InflationGRU(nn.Module):
    """A real recurrent encoder: processes the trailing window of
    mixed-frequency (value, mask) pairs one month at a time (a GRU,
    not a flattened MLP), then a small head produces (mean, log_var)
    for the next month's CPI_YOY. `n_series` is the number of series
    per step (each contributing a value and a mask bit, hence
    `2 * n_series` features per step)."""

    def __init__(self, n_series: int, hidden_size: int = 24, n_layers: int = 1) -> None:
        super().__init__()
        self.n_series = n_series
        self.gru = nn.GRU(
            input_size=2 * n_series, hidden_size=hidden_size, num_layers=n_layers, batch_first=True
        )
        self.head = nn.Linear(hidden_size, 2)  # [mean, log_var]

    def forward(self, x: torch.Tensor) -> tuple[torch.Tensor, torch.Tensor]:
        """`x` has shape (batch, window, 2 * n_series). Returns
        (mean, log_var), each shape (batch,)."""
        _, hidden = self.gru(x)
        last_hidden = hidden[-1]
        out = self.head(last_hidden)
        mean: torch.Tensor = out[:, 0]
        log_var: torch.Tensor = out[:, 1]
        return mean, log_var

    def count_parameters(self) -> int:
        return sum(p.numel() for p in self.parameters() if p.requires_grad)


def gaussian_nll(mean: torch.Tensor, log_var: torch.Tensor, target: torch.Tensor) -> torch.Tensor:
    """Mean negative log-likelihood of `target` under N(mean,
    exp(log_var)), batched -- the univariate counterpart to
    `neural_sde.training.gaussian_transition_nll`'s multivariate
    Cholesky form, written directly here rather than forcing that
    multivariate machinery onto a scalar target."""
    variance = torch.exp(log_var)
    nll = 0.5 * (log_var + (target - mean) ** 2 / variance + math.log(2 * math.pi))
    result: torch.Tensor = nll.mean()
    return result
