from datetime import date, timedelta

import numpy as np
import pytest
import torch

from prometheus.neural_sde.benchmark import (
    CANDIDATE_NAMES,
    benchmark_report,
    fit_ar1,
    fit_garch11,
    fit_gbm_constant,
    multi_seed_multi_solver_sensitivity,
    predict_candidate,
)
from prometheus.neural_sde.dataset import TransitionExample, fit_scaler
from prometheus.neural_sde.model import DriftDiffusionNet
from prometheus.neural_sde.training import train_neural_sde
from prometheus.stochastica.garch import GarchParams, simulate_garch_paths


def _examples(n: int, state_dim: int = 2, regime_dim: int = 3, seed: int = 0) -> list:
    rng = np.random.default_rng(seed)
    base = date(2000, 1, 1)
    examples = []
    state = rng.normal(size=state_dim)
    for i in range(n):
        next_state = state + rng.normal(scale=0.5, size=state_dim)
        examples.append(
            TransitionExample(
                t_scaled=float(i),
                state=tuple(state.tolist()),
                regime=tuple(rng.normal(size=regime_dim).tolist()),
                next_state=tuple(next_state.tolist()),
                decision_time=base + timedelta(days=30 * i),
                next_time=base + timedelta(days=30 * (i + 1)),
            )
        )
        state = next_state
    return examples


def test_fit_gbm_constant_recovers_known_mean_and_covariance() -> None:
    rng = np.random.default_rng(0)
    true_mean = np.array([0.2, -0.1])
    true_cov = np.array([[1.0, 0.3], [0.3, 0.5]])
    deltas = rng.multivariate_normal(true_mean, true_cov, size=20000)
    base = date(2000, 1, 1)
    examples = [
        TransitionExample(
            t_scaled=float(i),
            state=(0.0, 0.0),
            regime=(0.0,),
            next_state=tuple(deltas[i].tolist()),
            decision_time=base + timedelta(days=i),
            next_time=base + timedelta(days=i + 1),
        )
        for i in range(len(deltas))
    ]
    mean, cov = fit_gbm_constant(examples)
    assert mean == pytest.approx(true_mean, abs=0.05)
    assert cov == pytest.approx(true_cov, abs=0.05)


def test_fit_garch11_recovers_parameters_from_simulated_garch_data() -> None:
    """Cross-validates the GARCH(1,1) QMLE fitter using this
    repository's OWN existing GARCH simulator (`stochastica.garch`):
    simulate from a known (mu, omega, alpha, beta), refit, and check the
    recovered parameters are in the right ballpark (QMLE on ~2000 points
    has real sampling noise, so tolerances are loose, not exact)."""
    true_params = GarchParams(mu=0.0, omega=0.05, alpha=0.1, beta=0.8)
    rng = np.random.default_rng(1)
    returns, _conditional_variance = simulate_garch_paths(
        true_params, n_steps=2000, n_paths=1, rng=rng
    )
    returns = returns[0]

    fitted = fit_garch11(returns)
    assert fitted.alpha == pytest.approx(true_params.alpha, abs=0.15)
    assert fitted.beta == pytest.approx(true_params.beta, abs=0.25)
    assert fitted.alpha + fitted.beta < 1.0


def test_fit_ar1_recovers_known_linear_relationship() -> None:
    rng = np.random.default_rng(2)
    base = date(2000, 1, 1)
    examples = []
    x = 0.0
    for i in range(500):
        next_x = 2.0 + 0.5 * x + rng.normal(scale=0.01)
        examples.append(
            TransitionExample(
                t_scaled=float(i),
                state=(x,),
                regime=(0.0,),
                next_state=(next_x,),
                decision_time=base + timedelta(days=i),
                next_time=base + timedelta(days=i + 1),
            )
        )
        x = next_x
    fits = fit_ar1(examples)
    a, b, resid_std = fits[0]
    assert a == pytest.approx(2.0, abs=0.1)
    assert b == pytest.approx(0.5, abs=0.05)
    assert resid_std < 0.1


def test_benchmark_report_runs_end_to_end_and_every_candidate_is_finite() -> None:
    train_examples = _examples(60, seed=0)
    held_out = _examples(20, seed=1)
    state_scaler = fit_scaler(np.array([e.state for e in train_examples]))
    regime_scaler = fit_scaler(np.array([e.regime for e in train_examples]))
    trained = train_neural_sde(
        train_examples, held_out, state_scaler, regime_scaler, seed=0, max_epochs=10, patience=5
    )

    report = benchmark_report(held_out, train_examples, trained.model, state_scaler, regime_scaler)
    assert report.candidate_names == CANDIDATE_NAMES
    assert report.n_held_out == len(held_out)
    for name in CANDIDATE_NAMES:
        assert np.isfinite(report.log_score[name])
        assert np.isfinite(report.crps[name]["mean_crps"])


def test_predict_candidate_rejects_unknown_name() -> None:
    examples = _examples(5)
    with pytest.raises(ValueError, match="unknown candidate"):
        predict_candidate("not_a_real_candidate", examples, examples)


def test_multi_seed_multi_solver_sensitivity_is_reproducible_given_the_same_seed() -> None:
    torch.manual_seed(0)
    model = DriftDiffusionNet(state_dim=1, regime_dim=1, hidden_size=4)
    x0 = torch.zeros(1, 1)
    regime_path = torch.zeros(5, 1)

    report_a = multi_seed_multi_solver_sensitivity(model, x0, regime_path, seeds=(0, 1, 2))
    report_b = multi_seed_multi_solver_sensitivity(model, x0, regime_path, seeds=(0, 1, 2))
    assert report_a == report_b
    assert set(report_a.schemes) == {"euler_maruyama", "stochastic_heun"}
    assert report_a.terminal_std_across_schemes_at_matched_seed >= 0
