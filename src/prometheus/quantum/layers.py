"""A differentiable quantum circuit layer bridged into PyTorch via
PennyLane (QUANTUM-LAB gates Q1/Q003/Q004/Q005/Q006: device/backend
selection with explicit simulation metadata; reusable encoding/ansatz/
measurement; gradient, shape, dtype, serialization and error-handling
tests).

Architecture, deliberately a single small module rather than the
originally proposed `core/{devices,encodings,ansatz,measurements,
quantum_layers}.py` five-file split: angle embedding, a strongly
entangling variational ansatz and Pauli-Z measurement are each one
line of PennyLane and have no independent behavior worth testing in
isolation from the circuit they compose into -- splitting them would
be exactly the kind of premature abstraction this project's own style
avoids. What *is* kept as its own seam is `QuantumDeviceSpec` (the
"explicit simulation metadata" Q-003 calls for), since device choice,
qubit count, layer depth and shot budget are things a caller/benchmark
genuinely needs to vary and report independently of the layer's
forward/backward behavior.

Differentiation: PennyLane's `default.qubit` device, used here, runs
on an exact (non-finite-shot by default) state vector and
differentiates through it with PyTorch's own autograd (the "backprop"
diff method, not a hardware-realistic parameter-shift rule) --
appropriate for CPU research simulation, NOT a claim that this would
work the same way on real quantum hardware (parameter-shift would be
required there, and is far more expensive per gradient). `shots` is
exposed on `QuantumDeviceSpec` precisely so a finite-shot (hardware-
realistic) noise-robustness experiment can be run later (Q-014) without
changing this module.
"""

from __future__ import annotations

from dataclasses import dataclass

import pennylane as qml
import torch
from torch import nn

_ROTATIONS_PER_ANSATZ_LAYER = 3
"""StronglyEntanglingLayers applies one 3-angle (Rot) gate per qubit
per layer -- fixed by PennyLane's own template, not a free parameter
here."""


@dataclass(frozen=True, slots=True)
class QuantumDeviceSpec:
    """Explicit simulation metadata (Q-003): every quantity a benchmark
    comparing quantum challengers needs to vary or report, gathered in
    one place rather than scattered as bare constructor arguments."""

    n_qubits: int
    n_layers: int = 2
    device_name: str = "default.qubit"
    shots: int | None = None
    """None = exact state-vector simulation (the default used by every
    test and benchmark in this PR). An integer = finite-shot sampling,
    the hardware-realistic noise regime Q-014 is reserved for -- NOT
    exercised here."""

    def __post_init__(self) -> None:
        if self.n_qubits < 1:
            raise ValueError("n_qubits must be a positive integer")
        if self.n_layers < 1:
            raise ValueError("n_layers must be a positive integer")
        if self.shots is not None and self.shots < 1:
            raise ValueError("shots must be None (exact) or a positive integer")

    @property
    def weight_shape(self) -> tuple[int, int, int]:
        return (self.n_layers, self.n_qubits, _ROTATIONS_PER_ANSATZ_LAYER)

    @property
    def n_trainable_parameters(self) -> int:
        n_layers, n_qubits, n_rot = self.weight_shape
        return n_layers * n_qubits * n_rot

    def describe(self) -> dict[str, object]:
        """A plain-data summary suitable for a benchmark/manifest
        record -- "simulation metadata," not executing-on-real-hardware
        metadata (there is no real quantum hardware access here)."""
        return {
            "device_name": self.device_name,
            "n_qubits": self.n_qubits,
            "n_layers": self.n_layers,
            "shots": "exact_statevector" if self.shots is None else self.shots,
            "n_trainable_parameters": self.n_trainable_parameters,
            "simulated_hardware": False,
        }


def make_device(spec: QuantumDeviceSpec) -> qml.devices.Device:
    return qml.device(spec.device_name, wires=spec.n_qubits, shots=spec.shots)


class QuantumLayer(nn.Module):
    """Classical-encoder output (one angle per qubit, expected roughly
    in [-pi, pi] -- callers pass values through `torch.tanh * pi` or
    similar; this layer does not rescale its input itself, so a shape
    mismatch or a wildly out-of-range input is the caller's bug, not
    silently absorbed here) -> angle embedding -> `n_layers` strongly
    entangling variational layers -> one Pauli-Z expectation value per
    qubit.

    `forward_calls` / `samples_processed` are plain diagnostic counters
    (Q-012's "circuit evaluations"), not a claim about how many times
    PennyLane's simulator itself re-evaluates the circuit internally
    (which depends on batching and is not something this wrapper
    controls or inspects).
    """

    def __init__(self, spec: QuantumDeviceSpec) -> None:
        super().__init__()
        self.spec = spec
        device = make_device(spec)
        wires = tuple(range(spec.n_qubits))

        @qml.qnode(device, interface="torch", diff_method="backprop")  # type: ignore[untyped-decorator]
        def circuit(
            inputs: torch.Tensor, weights: torch.Tensor
        ) -> list[torch.Tensor]:
            qml.AngleEmbedding(inputs, wires=wires)
            qml.StronglyEntanglingLayers(weights, wires=wires)
            return [qml.expval(qml.PauliZ(w)) for w in wires]

        self._circuit = qml.qnn.TorchLayer(circuit, {"weights": spec.weight_shape})
        self.forward_calls = 0
        self.samples_processed = 0

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        if x.shape[-1] != self.spec.n_qubits:
            raise ValueError(
                f"QuantumLayer expects {self.spec.n_qubits} input features "
                f"(one angle per qubit), got {x.shape[-1]}"
            )
        self.forward_calls += 1
        self.samples_processed += x.shape[0] if x.dim() > 1 else 1
        output: torch.Tensor = self._circuit(x)
        return output
