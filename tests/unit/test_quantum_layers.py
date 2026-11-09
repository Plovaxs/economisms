import copy

import pytest
import torch

from prometheus.quantum.layers import QuantumDeviceSpec, QuantumLayer, make_device
from prometheus.quantum.models import (
    ClassicalMatchedClassifier,
    ClassicalMatchedRegressor,
    HybridQuantumClassifier,
    HybridQuantumRegressor,
    LinearRegressionModel,
    LogisticRegressionClassifier,
    base_rate_logit,
    count_parameters,
)


def test_device_spec_rejects_non_positive_qubits() -> None:
    with pytest.raises(ValueError, match="n_qubits"):
        QuantumDeviceSpec(n_qubits=0)


def test_device_spec_rejects_non_positive_layers() -> None:
    with pytest.raises(ValueError, match="n_layers"):
        QuantumDeviceSpec(n_qubits=2, n_layers=0)


def test_device_spec_rejects_non_positive_shots() -> None:
    with pytest.raises(ValueError, match="shots"):
        QuantumDeviceSpec(n_qubits=2, shots=0)


def test_weight_shape_and_parameter_count_are_consistent() -> None:
    spec = QuantumDeviceSpec(n_qubits=4, n_layers=3)
    assert spec.weight_shape == (3, 4, 3)
    assert spec.n_trainable_parameters == 3 * 4 * 3


def test_describe_reports_exact_statevector_by_default() -> None:
    spec = QuantumDeviceSpec(n_qubits=4, n_layers=2)
    description = spec.describe()
    assert description["shots"] == "exact_statevector"
    assert description["simulated_hardware"] is False
    assert description["n_qubits"] == 4


def test_describe_reports_a_finite_shot_budget_when_set() -> None:
    spec = QuantumDeviceSpec(n_qubits=4, shots=256)
    assert spec.describe()["shots"] == 256


def test_make_device_builds_a_real_pennylane_device() -> None:
    device = make_device(QuantumDeviceSpec(n_qubits=3))
    assert device.wires.tolist() == [0, 1, 2]


def test_quantum_layer_output_shape_and_dtype() -> None:
    torch.manual_seed(0)
    layer = QuantumLayer(QuantumDeviceSpec(n_qubits=4, n_layers=2))
    x = torch.randn(5, 4)
    out = layer(x)
    assert out.shape == (5, 4)
    assert out.dtype == torch.float32


def test_quantum_layer_single_sample_shape() -> None:
    torch.manual_seed(0)
    layer = QuantumLayer(QuantumDeviceSpec(n_qubits=3, n_layers=1))
    out = layer(torch.randn(3))
    assert out.shape == (3,)


def test_quantum_layer_rejects_mismatched_input_width() -> None:
    layer = QuantumLayer(QuantumDeviceSpec(n_qubits=4, n_layers=1))
    with pytest.raises(ValueError, match="4 input features"):
        layer(torch.randn(2, 5))


def test_quantum_layer_tracks_forward_call_diagnostics() -> None:
    layer = QuantumLayer(QuantumDeviceSpec(n_qubits=3, n_layers=1))
    assert layer.forward_calls == 0
    layer(torch.randn(7, 3))
    layer(torch.randn(2, 3))
    assert layer.forward_calls == 2
    assert layer.samples_processed == 9


def test_quantum_layer_outputs_are_bounded_pauli_z_expectations() -> None:
    torch.manual_seed(1)
    layer = QuantumLayer(QuantumDeviceSpec(n_qubits=4, n_layers=2))
    out = layer(torch.randn(20, 4))
    assert torch.all(out >= -1.0 - 1e-6)
    assert torch.all(out <= 1.0 + 1e-6)


def test_quantum_layer_gradients_are_finite_and_nonzero() -> None:
    torch.manual_seed(2)
    layer = QuantumLayer(QuantumDeviceSpec(n_qubits=4, n_layers=2))
    x = torch.randn(6, 4, requires_grad=True)
    loss = layer(x).sum()
    loss.backward()
    assert x.grad is not None
    assert torch.isfinite(x.grad).all()
    assert torch.any(x.grad != 0.0)
    for param in layer.parameters():
        assert param.grad is not None
        assert torch.isfinite(param.grad).all()


def test_quantum_layer_gradient_matches_independent_finite_difference() -> None:
    """Q-005's "finite-difference/independent gradient sanity check":
    perturb ONE trainable weight by +/-eps and confirm the resulting
    central-difference slope of the summed output matches autograd's
    reported gradient for that same weight -- an independent numerical
    check, not just "the gradient exists and is not NaN"."""
    torch.manual_seed(3)
    layer = QuantumLayer(QuantumDeviceSpec(n_qubits=2, n_layers=1))
    x = torch.randn(4, 2)
    weights = next(layer.parameters())

    output = layer(x).sum()
    output.backward()
    assert weights.grad is not None
    autograd_grad = weights.grad.clone()

    eps = 1e-3
    flat_index = (0, 0, 0)
    with torch.no_grad():
        weights[flat_index] += eps
        plus = layer(x).sum().item()
        weights[flat_index] -= 2 * eps
        minus = layer(x).sum().item()
        weights[flat_index] += eps  # restore

    finite_diff = (plus - minus) / (2 * eps)
    assert finite_diff == pytest.approx(autograd_grad[flat_index].item(), abs=1e-2)


def test_quantum_layer_is_deterministic_given_the_same_seed() -> None:
    x = torch.randn(4, 4)
    torch.manual_seed(42)
    layer_a = QuantumLayer(QuantumDeviceSpec(n_qubits=4, n_layers=2))
    out_a = layer_a(x)

    torch.manual_seed(42)
    layer_b = QuantumLayer(QuantumDeviceSpec(n_qubits=4, n_layers=2))
    out_b = layer_b(x)

    assert torch.allclose(out_a, out_b)


def test_quantum_layer_different_seeds_give_different_weights() -> None:
    torch.manual_seed(1)
    layer_a = QuantumLayer(QuantumDeviceSpec(n_qubits=4, n_layers=2))
    torch.manual_seed(2)
    layer_b = QuantumLayer(QuantumDeviceSpec(n_qubits=4, n_layers=2))
    weights_a = next(layer_a.parameters())
    weights_b = next(layer_b.parameters())
    assert not torch.allclose(weights_a, weights_b)


def test_quantum_layer_state_dict_round_trip_reproduces_inference() -> None:
    torch.manual_seed(7)
    layer = QuantumLayer(QuantumDeviceSpec(n_qubits=4, n_layers=2))
    x = torch.randn(10, 4)
    original_output = layer(x).detach().clone()

    state = copy.deepcopy(layer.state_dict())

    torch.manual_seed(999)  # scramble, to prove the reload actually matters
    reloaded = QuantumLayer(QuantumDeviceSpec(n_qubits=4, n_layers=2))
    reloaded.load_state_dict(state)
    reloaded_output = reloaded(x).detach()

    assert torch.allclose(original_output, reloaded_output, atol=1e-6)


def test_base_rate_logit_recovers_the_empirical_rate() -> None:
    import math

    labels = [1.0, 1.0, 0.0, 0.0]
    logit = base_rate_logit(labels)
    assert 1 / (1 + math.exp(-logit)) == pytest.approx(0.5, abs=1e-6)


def test_base_rate_logit_rejects_empty_labels() -> None:
    with pytest.raises(ValueError, match="non-empty"):
        base_rate_logit([])


def test_base_rate_logit_handles_a_degenerate_all_positive_sample() -> None:
    logit = base_rate_logit([1.0, 1.0, 1.0])
    assert logit > 0
    assert math_is_finite(logit)


def math_is_finite(value: float) -> bool:
    return value == value and abs(value) != float("inf")


def test_logistic_regression_classifier_is_linear_in_raw_features() -> None:
    model = LogisticRegressionClassifier(input_dim=5)
    x = torch.randn(3, 5)
    out = model(x)
    assert out.shape == (3,)
    assert count_parameters(model) == 5 + 1  # weight + bias


def test_classical_matched_classifier_runs_end_to_end() -> None:
    model = ClassicalMatchedClassifier(input_dim=6, n_qubits=4, hidden_size=8)
    out = model(torch.randn(3, 6))
    assert out.shape == (3,)
    assert count_parameters(model) > 0


def test_hybrid_quantum_classifier_runs_end_to_end_and_is_differentiable() -> None:
    torch.manual_seed(0)
    model = HybridQuantumClassifier(input_dim=6, n_qubits=4, hidden_size=8)
    x = torch.randn(5, 6)
    logits = model(x)
    assert logits.shape == (5,)
    loss = torch.nn.functional.binary_cross_entropy_with_logits(
        logits, torch.tensor([1.0, 0.0, 1.0, 0.0, 1.0])
    )
    loss.backward()
    grads = [p.grad for p in model.parameters() if p.requires_grad]
    assert all(g is not None and torch.isfinite(g).all() for g in grads)


def test_hybrid_and_classical_matched_models_have_different_parameter_counts() -> None:
    """Documents, rather than hides, the parameter-count mismatch this
    module's own docstring flags between the quantum layer and its
    classical substitute."""
    hybrid = HybridQuantumClassifier(input_dim=6, n_qubits=4, hidden_size=8)
    classical = ClassicalMatchedClassifier(input_dim=6, n_qubits=4, hidden_size=8)
    assert count_parameters(hybrid) != count_parameters(classical)


def test_regressor_subclasses_have_identical_architecture_to_their_classifier_parents() -> None:
    """LinearRegressionModel/ClassicalMatchedRegressor/HybridQuantumRegressor
    exist purely as clearly-named subclasses with NO behavioral change
    -- confirmed here by comparing parameter counts and forward output
    shapes directly against their parent classes."""
    assert count_parameters(LinearRegressionModel(5)) == count_parameters(
        LogisticRegressionClassifier(5)
    )
    assert count_parameters(ClassicalMatchedRegressor(6, n_qubits=4)) == count_parameters(
        ClassicalMatchedClassifier(6, n_qubits=4)
    )
    assert count_parameters(HybridQuantumRegressor(6, n_qubits=4)) == count_parameters(
        HybridQuantumClassifier(6, n_qubits=4)
    )

    x = torch.randn(3, 6)
    assert ClassicalMatchedRegressor(6, n_qubits=4)(x).shape == (3,)
    torch.manual_seed(0)
    assert HybridQuantumRegressor(6, n_qubits=4)(x).shape == (3,)


def test_regressor_subclasses_are_genuinely_trainable_with_mse_loss() -> None:
    torch.manual_seed(0)
    model = HybridQuantumRegressor(6, n_qubits=4)
    x = torch.randn(5, 6)
    y = torch.randn(5)
    optimizer = torch.optim.Adam(model.parameters(), lr=0.05)
    loss_fn = torch.nn.MSELoss()
    first_loss = loss_fn(model(x), y).item()
    for _ in range(20):
        optimizer.zero_grad()
        loss = loss_fn(model(x), y)
        loss.backward()
        optimizer.step()
    last_loss = loss_fn(model(x), y).item()
    assert last_loss < first_loss
