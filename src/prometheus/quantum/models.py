"""Candidate classifier architectures for a binary economic
classification task (used by `recessionnet` -- FP-06, and directly
answering RQ2 of the user-supplied quantum blueprint: "Can VQC-based
... classification improve ... calibration or ... discrimination
relative to logistic regression, MLP"). Every model here returns raw
logits (not probabilities) so a single `nn.BCEWithLogitsLoss` is the
correct, numerically-stable loss for all of them -- comparing them is
then a fair "same loss, same optimizer, same data" comparison, not an
artifact of different output conventions.

Four architectures, matching the blueprint's own required baseline
set (section 4.2) minus gradient-boosted trees (would need a new
non-torch dependency; explicitly not attempted here):

- `base_rate_logit`: the trivial constant-prediction baseline.
- `LogisticRegressionClassifier`: linear in the raw features -- no
  encoder, no nonlinearity. This IS logistic regression, not an
  approximation of it (BCEWithLogitsLoss on a linear layer's output is
  exactly the logistic regression log-likelihood).
- `ClassicalMatchedClassifier`: the SAME classical encoder the hybrid
  model below uses, with the quantum layer replaced by a classical
  nonlinear layer of matching output width -- the "identical temporal
  encoder with a classical head" arm the blueprint's evaluation
  protocol (section 8, point 5) specifically requires so a quantum
  challenger is never compared against a weaker classical model than
  necessary.
- `HybridQuantumClassifier`: the same encoder feeding
  `quantum.layers.QuantumLayer`. The encoder's `tanh` output (range
  (-1, 1)) is scaled by pi/2, not pi, before angle embedding. Under a
  single-qubit RX(theta) angle embedding starting from |0>, <Z> =
  cos(theta), so d<Z>/d(theta) = -sin(theta): zero at theta=0 AND at
  theta=+/-pi, maximized in magnitude at theta=+/-pi/2. A trained
  `tanh` layer tends to saturate toward its +/-1 extremes -- scaling
  by pi previously pushed most saturated inputs toward the +/-pi
  DEAD zone (near-zero local gradient); scaling by pi/2 instead pushes
  them toward the +/-pi/2 PEAK-sensitivity zone. This was found by
  diagnosing an initial benchmark run where the hybrid model's fitted
  calibration slope was ~0.1 (see `recessionnet.evaluation`) --
  consistent with angles clustered in a flat region of the circuit's
  response curve, not genuine inability to discriminate.

Parameter counts are NOT identical between `ClassicalMatchedClassifier`
and `HybridQuantumClassifier` (the quantum layer has
`n_layers * n_qubits * 3` parameters driving an `n_qubits`-dimensional
highly nonlinear, entangled transform; its classical substitute is an
ordinary `Linear(n_qubits, n_qubits)` with `n_qubits * (n_qubits + 1)`
parameters) -- both counts are reported by `count_parameters` so this
is visible and auditable in any benchmark report, not glossed over.
"""

from __future__ import annotations

import math
from collections.abc import Sequence

import torch
from torch import nn

from prometheus.quantum.layers import QuantumDeviceSpec, QuantumLayer


def base_rate_logit(labels: Sequence[float]) -> float:
    """logit(mean(labels)), clipped away from +/-inf for a degenerate
    all-0 or all-1 sample -- the trivial baseline every other model
    must beat to be worth reporting at all."""
    if len(labels) == 0:
        raise ValueError("labels must be non-empty")
    rate = sum(labels) / len(labels)
    rate = min(max(rate, 1e-6), 1 - 1e-6)
    return math.log(rate / (1 - rate))


class LogisticRegressionClassifier(nn.Module):
    def __init__(self, input_dim: int) -> None:
        super().__init__()
        self.linear = nn.Linear(input_dim, 1)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        output: torch.Tensor = self.linear(x).squeeze(-1)
        return output


def _shared_encoder(input_dim: int, hidden_size: int, n_qubits: int) -> nn.Sequential:
    return nn.Sequential(
        nn.Linear(input_dim, hidden_size),
        nn.Tanh(),
        nn.Linear(hidden_size, n_qubits),
        nn.Tanh(),
    )


class ClassicalMatchedClassifier(nn.Module):
    def __init__(self, input_dim: int, n_qubits: int = 4, hidden_size: int = 16) -> None:
        super().__init__()
        self.encoder = _shared_encoder(input_dim, hidden_size, n_qubits)
        self.classical_substitute = nn.Sequential(nn.Linear(n_qubits, n_qubits), nn.Tanh())
        self.head = nn.Linear(n_qubits, 1)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        encoded = self.encoder(x)
        features = self.classical_substitute(encoded)
        output: torch.Tensor = self.head(features).squeeze(-1)
        return output


class HybridQuantumClassifier(nn.Module):
    def __init__(
        self,
        input_dim: int,
        n_qubits: int = 4,
        n_quantum_layers: int = 2,
        hidden_size: int = 16,
    ) -> None:
        super().__init__()
        self.encoder = _shared_encoder(input_dim, hidden_size, n_qubits)
        self.quantum = QuantumLayer(QuantumDeviceSpec(n_qubits=n_qubits, n_layers=n_quantum_layers))
        self.head = nn.Linear(n_qubits, 1)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        encoded = self.encoder(x)
        features = self.quantum(encoded * (math.pi / 2))
        output: torch.Tensor = self.head(features).squeeze(-1)
        return output


def count_parameters(model: nn.Module) -> int:
    return sum(p.numel() for p in model.parameters() if p.requires_grad)
