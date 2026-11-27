"""Model zoo tranche 3: structural macro, portfolio layer, production networks, causal and
survival."""

from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import pytest
import torch
from scipy.optimize import minimize

from prometheus.modelzoo import causal as cz
from prometheus.modelzoo import networks as nw
from prometheus.modelzoo import portfolio as pf
from prometheus.modelzoo import structural as st
from prometheus.orchestration import modelzoo_macro_study as study

DATA = Path(__file__).resolve().parents[2] / "data_cache" / "ff3_monthly_snapshot.csv"


# ----- structural -------------------------------------------------------------------------------


class _ExactPolicy:
    def savings_rate(self, k: torch.Tensor, log_z: torch.Tensor) -> torch.Tensor:
        del log_z
        return torch.full_like(k, st.exact_savings_rate())


def test_the_exact_policy_has_a_zero_euler_residual_in_the_closed_form_economy() -> None:
    k, log_z = st.evaluation_states(st.CLOSED_FORM, 50, 1)
    residual = st.euler_residual(st.CLOSED_FORM, _ExactPolicy(), k, log_z)
    assert float(residual.abs().max()) < 2e-3  # only the five-node quadrature is approximate


def test_a_wrong_policy_has_a_visible_residual_and_value_iteration_finds_the_exact_one() -> None:
    class Wrong:
        def savings_rate(self, k: torch.Tensor, log_z: torch.Tensor) -> torch.Tensor:
            del log_z
            return torch.full_like(k, 0.6)

    k, log_z = st.evaluation_states(st.CLOSED_FORM, 50, 1)
    assert float(st.euler_residual(st.CLOSED_FORM, Wrong(), k, log_z).abs().mean()) > 0.1
    vfi = st.solve_vfi(st.CLOSED_FORM, n_k=120, n_z=5)
    values = st.policy_values(vfi, k, log_z)
    assert np.abs(values - st.exact_savings_rate()).mean() < 0.01


def test_the_deep_equilibrium_net_trains_and_the_steady_state_is_consistent() -> None:
    fit = st.train_deq(st.GENERAL, steps=20, seed=1, batch=64)
    assert math.isfinite(fit.final_loss)
    k, log_z = st.evaluation_states(st.GENERAL, 20, 2)
    assert (
        (st.policy_values(fit.net, k, log_z) > 0) & (st.policy_values(fit.net, k, log_z) < 1)
    ).all()
    # at the deterministic steady state the Euler equation holds: 1 = beta (a k^(a-1) + 1 - delta)
    e = st.GENERAL
    gross = st.ALPHA * e.k_steady ** (st.ALPHA - 1.0) + 1.0 - e.delta
    assert st.BETA * gross == pytest.approx(1.0, abs=1e-9)


def test_the_tauchen_chain_is_a_proper_stochastic_matrix() -> None:
    grid, trans = st.tauchen(7)
    assert np.allclose(trans.sum(axis=1), 1.0) and (trans >= 0).all() and len(grid) == 7


# ----- portfolio --------------------------------------------------------------------------------


def _covariance(seed: int) -> np.ndarray:
    sample = np.random.default_rng(seed).standard_normal((200, 3))
    return np.asarray(np.cov(sample.T) * 0.01 + 1e-4 * np.eye(3))


def test_the_long_only_qp_matches_a_numerical_optimiser() -> None:
    for seed in range(6):
        cov = _covariance(seed)
        mu = np.random.default_rng(seed + 50).normal(0, 0.01, 3)
        w, _ = pf.solve_long_only(cov, mu, 2.0)
        assert w.sum() == pytest.approx(1.0) and (w >= -1e-12).all()
        ref = minimize(
            lambda x, cov=cov, mu=mu: 0.5 * x @ cov @ x - mu @ x / 2.0,
            np.full(3, 1 / 3),
            bounds=[(0, 1)] * 3,
            constraints=[{"type": "eq", "fun": lambda x: x.sum() - 1.0}],
            method="SLSQP",
            options={"ftol": 1e-14},
        )
        assert np.allclose(w, ref.x, atol=1e-5)


def test_the_qp_gradient_equals_a_finite_difference() -> None:
    cov = torch.as_tensor(_covariance(3)[None], dtype=torch.float64)
    mu = torch.tensor([[0.01, 0.005, -0.002]], dtype=torch.float64, requires_grad=True)
    probe = torch.tensor([[1.0, 0.3, -0.2]], dtype=torch.float64)
    w = pf.long_only_weights(mu, cov, 2.0)
    grad = torch.autograd.grad((w * probe).sum(), mu)[0].numpy()[0]
    for i in range(3):
        shifted = mu.detach().clone()
        shifted[0, i] += 1e-7
        fd = float(((pf.long_only_weights(shifted, cov, 2.0) - w.detach()) * probe).sum() / 1e-7)
        assert fd == pytest.approx(float(grad[i]), abs=1e-5)


def test_a_zero_forecast_gives_the_minimum_variance_portfolio() -> None:
    cov = _covariance(4)
    w, _ = pf.solve_long_only(cov, np.zeros(3), 1.0)
    inverse = np.linalg.inv(cov)
    expected = inverse @ np.ones(3) / (np.ones(3) @ inverse @ np.ones(3))
    if (expected >= 0).all():
        assert np.allclose(w, expected, atol=1e-8)


def test_factor_data_has_no_look_ahead_and_the_predictors_train() -> None:
    data = pf.load_factor_data(str(DATA))
    assert data.returns.shape[1] == 3 and np.isnan(data.features[:60]).all()
    # the features of month i use only months before i
    i = 200
    assert np.allclose(data.features[i, :3], data.returns[i - 1])
    assert np.linalg.eigvalsh(data.covariance[i]).min() > 0
    rows = np.arange(60, 400)
    for focused in (False, True):
        net = pf.fit_predictor(
            data, rows, decision_focused=focused, risk_aversion=4.0, epochs=1, seed=1
        )
        w = pf.predicted_weights(net, data, rows, np.arange(400, 420), 4.0)
        assert w.shape == (20, 3) and np.allclose(w.sum(axis=1), 1.0)
    assert pf.sharpe(np.array([0.01, 0.02, 0.0, 0.03])) > 0 and pf.sharpe(np.zeros(5)) == 0.0


# ----- production networks ----------------------------------------------------------------------


def test_the_io_matrix_is_productive_and_the_leontief_series_converges_to_the_inverse() -> None:
    a = nw.random_io_matrix(25, seed=1)
    assert float(np.max(np.abs(np.linalg.eigvals(a)))) == pytest.approx(0.7, abs=1e-6)
    demand = np.random.default_rng(2).standard_normal(25)
    exact = nw.leontief_response(a, demand)
    assert np.allclose(nw.truncated_response(a, demand, 200), exact, atol=1e-8)
    assert not np.allclose(nw.truncated_response(a, demand, 1), exact, atol=1e-3)


def test_the_gnn_runs_on_graphs_of_any_size_and_the_graph_matters() -> None:
    small, large = nw.make_graph_batch(12, 4, seed=1), nw.make_graph_batch(40, 4, seed=2)
    model = nw.ShockGNN(layers=2, width=8)
    assert model(small.adjacency, small.demand).shape == (4, 12)
    assert model(large.adjacency, large.demand).shape == (4, 40)
    blind = nw.ShockGNN(layers=2, width=8, use_graph=False)
    blind.load_state_dict(model.state_dict())
    assert not torch.allclose(
        model(small.adjacency, small.demand), blind(small.adjacency, small.demand)
    )


def test_training_improves_the_gnn_and_the_truncation_error_falls_with_reach() -> None:
    graphs = [nw.make_graph_batch(15, 8, seed=10 + i) for i in range(8)]
    model = nw.ShockGNN(layers=2, width=8)
    before = nw.evaluate_gnn(model, graphs[0])
    nw.train_gnn(model, graphs, epochs=15, seed=1)
    assert nw.evaluate_gnn(model, graphs[0]) < before
    errors = [nw.evaluate_truncation(graphs[0], k) for k in (1, 3, 8)]
    assert errors[0] > errors[1] > errors[2]


# ----- causal and survival ----------------------------------------------------------------------


def test_partially_linear_data_and_the_two_effect_estimators_run() -> None:
    data = cz.make_partially_linear(300, seed=1)
    assert data.x.shape == (300, 10)
    assert math.isfinite(cz.ols_effect(data))
    assert math.isfinite(cz.double_ml_effect(data, epochs=2, seed=1))


def test_deep_iv_trains_and_the_linear_iv_curve_is_a_line() -> None:
    data = cz.make_iv_data(300, seed=2)
    grid = np.linspace(-1, 1, 20)
    net = cz.deep_iv_fit(data, epochs=5, seed=1)
    assert cz.deep_iv_curve(net, grid).shape == (20,)
    line = cz.two_stage_least_squares_curve(data, grid)
    assert np.allclose(np.diff(line, 2), 0.0, atol=1e-9)
    assert cz.curve_rmse(cz.structural_f(grid), grid) == pytest.approx(0.0, abs=1e-12)


def test_the_cox_partial_likelihood_matches_a_hand_computation() -> None:
    risk = torch.tensor([0.2, -0.1, 0.5])
    time = torch.tensor([1.0, 2.0, 3.0])
    event = torch.tensor([1.0, 1.0, 0.0])
    r = risk.numpy()
    expected = (
        -(
            (r[0] - math.log(sum(math.exp(x) for x in r)))
            + (r[1] - math.log(math.exp(r[1]) + math.exp(r[2])))
        )
        / 2.0
    )
    assert float(cz.cox_partial_likelihood(risk, time, event)) == pytest.approx(expected, rel=1e-6)


def test_concordance_is_one_for_a_perfect_ranking_and_survival_models_train() -> None:
    time = np.array([1.0, 2.0, 3.0, 4.0])
    event = np.ones(4)
    assert cz.concordance(np.array([4.0, 3.0, 2.0, 1.0]), time, event) == 1.0
    assert cz.concordance(np.array([1.0, 2.0, 3.0, 4.0]), time, event) == 0.0
    data = cz.make_survival(300, seed=3)
    assert 0.0 < data.event.mean() <= 1.0
    for hidden in (0, 8):
        net = cz.fit_cox(data, hidden=hidden, epochs=5, seed=1)
        assert cz.risk_scores(net, data.x).shape == (300,)
    assert cz.concordance(data.true_risk, data.time, data.event) > 0.6


# ----- the study --------------------------------------------------------------------------------


def test_the_study_states_every_hypothesis_and_discloses_what_was_seen() -> None:
    doc = study.__doc__ or ""
    labels = ("Z-M1", "Z-M2", "Z-M3", "Z-P1", "Z-P2", "Z-P3", "Z-P4", "Z-G1", "Z-G2", "Z-G3")
    for label in (*labels, "Z-C1", "Z-C2", "Z-C3", "Z-S1", "Z-S2"):
        assert label in doc
    assert "What I had looked at before writing this" in doc


def test_tiny_runs_of_every_family_return_their_verdicts() -> None:
    s = study.structural_study((1, 2), steps=3)
    assert {"Z-M1", "Z-M2", "Z-M3"} <= set(s)
    p = study.portfolio_study((1, 2), epochs=1, resamples=50, gradient_cases=2)
    assert {"Z-P1", "Z-P2", "Z-P3", "Z-P4"} <= set(p) and p["Z-P4"] == "SUPPORTED"
    n = study.network_study((1, 2), epochs=1, train_graphs=2, test_graphs=2)
    assert {"Z-G1", "Z-G2", "Z-G3"} <= set(n)
    c = study.causal_study(
        dml_replications=2,
        iv_replications=2,
        survival_replications=2,
        dml_epochs=1,
        iv_epochs=3,
        survival_epochs=3,
    )
    assert {"Z-C1", "Z-C2", "Z-C3", "Z-S1", "Z-S2"} <= set(c)
