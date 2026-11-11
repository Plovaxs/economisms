import math

import pytest
import torch

from prometheus.inflationcast.models import (
    ClassicalMatchedRegressor,
    HybridQuantumRegressor,
    InflationGRU,
    LinearRegressionModel,
    NaivePersistence,
    gaussian_nll,
)


def test_naive_persistence_predicts_the_given_value() -> None:
    assert NaivePersistence.predict(3.5) == 3.5


def test_inflation_gru_forward_returns_mean_and_log_var_shaped_like_batch() -> None:
    model = InflationGRU(n_series=3, hidden_size=8)
    x = torch.zeros(5, 4, 6)  # (batch, window, 2 * n_series)
    mean, log_var = model(x)
    assert mean.shape == (5,)
    assert log_var.shape == (5,)


def test_inflation_gru_count_parameters_is_positive() -> None:
    model = InflationGRU(n_series=3, hidden_size=8)
    assert model.count_parameters() > 0


def test_gaussian_nll_is_minimized_at_the_true_mean_with_tiny_variance() -> None:
    target = torch.tensor([2.0])
    exact = gaussian_nll(torch.tensor([2.0]), torch.tensor([-10.0]), target)
    off = gaussian_nll(torch.tensor([5.0]), torch.tensor([-10.0]), target)
    assert exact.item() < off.item()


def test_gaussian_nll_matches_the_closed_form_normal_log_density() -> None:
    mean, log_var, target = torch.tensor([1.0]), torch.tensor([0.0]), torch.tensor([2.5])
    variance = math.exp(0.0)
    expected = 0.5 * (0.0 + (2.5 - 1.0) ** 2 / variance + math.log(2 * math.pi))
    assert gaussian_nll(mean, log_var, target).item() == pytest.approx(expected, rel=1e-6)


def test_linear_regression_model_accepts_a_flat_input_dim() -> None:
    model = LinearRegressionModel(input_dim=12)
    out = model(torch.zeros(4, 12))
    assert out.shape == (4,)


def test_classical_matched_regressor_accepts_a_flat_input_dim() -> None:
    model = ClassicalMatchedRegressor(input_dim=12)
    out = model(torch.zeros(4, 12))
    assert out.shape == (4,)


def test_hybrid_quantum_regressor_accepts_a_flat_input_dim() -> None:
    model = HybridQuantumRegressor(input_dim=12)
    out = model(torch.zeros(4, 12))
    assert out.shape == (4,)
