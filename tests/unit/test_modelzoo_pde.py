"""Model zoo tranche 1: operator learning, continuous dynamics, mesh-free solvers, and the decision
rules the study judges them by. Everything here is small and fast; the recorded study is checked in
`test_modelzoo_pde_records.py`."""

from __future__ import annotations

import math
from datetime import date

import numpy as np
import pytest
import torch

from prometheus.modelzoo import dynamics as dyn
from prometheus.modelzoo import operators as ops
from prometheus.modelzoo import variational as var
from prometheus.modelzoo.verdicts import (
    direction_verdict,
    paired_bootstrap_ci,
    summarise_difference,
    threshold_verdict,
)
from prometheus.orchestration import modelzoo_pde_study as study
from prometheus.volterra.black_scholes import black_scholes_price
from prometheus.volterra.instruments import EuropeanOption
from prometheus.volterra.market import MarketSnapshot

# ----- decision rules ---------------------------------------------------------------------------


def test_direction_and_threshold_verdicts() -> None:
    assert direction_verdict(0.01, 0.5) == "SUPPORTED"
    assert direction_verdict(-0.5, -0.01) == "CONTRADICTED"
    assert direction_verdict(-0.1, 0.3) == "INCONCLUSIVE"
    assert direction_verdict(0.0, 0.3) == "INCONCLUSIVE"  # zero on the edge is not support
    assert threshold_verdict(0.05, 0.05, 0.10) == "SUPPORTED"
    assert threshold_verdict(0.0500001, 0.05, 0.10) == "INCONCLUSIVE"
    assert threshold_verdict(0.1, 0.05, 0.10) == "INCONCLUSIVE"
    assert threshold_verdict(0.11, 0.05, 0.10) == "CONTRADICTED"
    with pytest.raises(ValueError, match="must not exceed"):
        threshold_verdict(0.1, 0.2, 0.1)


def test_bootstrap_interval_is_deterministic_and_needs_two_seeds() -> None:
    values = [0.1, 0.2, 0.15, 0.3]
    assert paired_bootstrap_ci(values, seed=3) == paired_bootstrap_ci(values, seed=3)
    low, high = paired_bootstrap_ci(values, seed=3)
    assert min(values) <= low <= high <= max(values)
    with pytest.raises(ValueError, match="at least two"):
        paired_bootstrap_ci([1.0])
    assert summarise_difference([1.0, 2.0, 3.0])["verdict"] == "SUPPORTED"
    assert summarise_difference([-1.0, -2.0, -3.0])["verdict"] == "CONTRADICTED"


# ----- operators --------------------------------------------------------------------------------


def test_the_closed_form_call_matches_the_projects_own_pricer() -> None:
    market = MarketSnapshot(
        as_of=date(2024, 1, 1), spot=100.0, risk_free_rate=ops.RATE, volatility=0.25
    )
    option = EuropeanOption(strike=95.0, maturity=ops.MATURITY, option_type="call")
    ours = float(ops.bs_call(np.array(100.0), np.array(95.0), np.array(0.25)))
    assert ours == pytest.approx(black_scholes_price(market, option), rel=1e-10)


def test_operator_data_is_scaled_and_reproducible() -> None:
    a = ops.make_operator_data(20, 32, seed=1)
    b = ops.make_operator_data(20, 32, seed=1)
    assert np.array_equal(a.payoff, b.payoff) and np.array_equal(a.price, b.price)
    assert a.payoff.shape == (20, 32) and np.abs(a.payoff).max() == pytest.approx(1.0)
    assert (a.sigma >= ops.SIGMA_LOW).all() and (a.sigma <= ops.SIGMA_HIGH).all()
    with pytest.raises(ValueError, match="grid_size"):
        ops.make_operator_data(5, 4, seed=1)


def test_every_operator_runs_on_the_training_grid_and_on_a_finer_one() -> None:
    train = ops.make_operator_data(8, 64, seed=3)
    fine = ops.make_operator_data(8, 128, seed=4)
    for name in ("fno", "deeponet", "mlp"):
        model = ops.build_model(name, 64)
        assert ops.predict(model, train).shape == (8, 64)
        assert ops.predict(model, fine).shape == (8, 128)
    with pytest.raises(ValueError, match="unknown operator model"):
        ops.build_model("transformer", 64)


def test_the_fno_is_resolution_free_and_uses_only_low_modes() -> None:
    model = ops.FNO1d(width=8, modes=4, layers=2)
    for size in (32, 100):
        out = model(torch.zeros(2, size), torch.zeros(2))
        assert out.shape == (2, size)
    assert model.spectral[0].weight.shape[-1] == 4


def test_training_reduces_the_loss_and_fits_better_than_the_trivial_answer() -> None:
    train = ops.make_operator_data(200, 32, seed=5)
    test = ops.make_operator_data(60, 32, seed=6)
    model = ops.build_model("mlp", 32)
    before = ops.relative_l2(ops.predict(model, test), test.price)
    fit = ops.train_operator(model, train, epochs=30, seed=7)
    after = ops.relative_l2(ops.predict(model, test), test.price)
    assert fit.parameters > 0 and after < before
    assert after < ops.relative_l2(test.payoff, test.price)
    with pytest.raises(ValueError, match="epochs"):
        ops.train_operator(model, train, epochs=0, seed=1)


# ----- dynamics ---------------------------------------------------------------------------------


@pytest.mark.parametrize("name", ["pendulum", "goodwin"])
def test_the_true_systems_conserve_their_energy_under_the_integrator(name: str) -> None:
    system = dyn.SYSTEMS[name]
    y0 = torch.tensor([system.start], dtype=torch.float64)
    path = dyn.rollout(system.field, y0, 0.05, 400)
    energy = system.energy(path)
    assert float((energy - energy[0]).abs().max()) < 1e-6
    assert math.isfinite(dyn.period_of(system, 0.1))


def test_the_goodwin_hamiltonian_generates_the_goodwin_field() -> None:
    y = torch.tensor([[0.3, -0.2]], dtype=torch.float64, requires_grad=True)
    (grad,) = torch.autograd.grad(dyn.SYSTEMS["goodwin"].energy(y).sum(), y)
    field = dyn.SYSTEMS["goodwin"].field(y.detach())
    assert float(field[0, 0]) == pytest.approx(float(grad[0, 1]))  # q' = dH/dp
    assert float(field[0, 1]) == pytest.approx(-float(grad[0, 0]))  # p' = -dH/dq


def test_an_hnn_conserves_its_own_energy_by_construction() -> None:
    model = dyn.HNN(width=16)
    y = torch.randn(5, 2, requires_grad=True)
    field = model(y)
    (grad,) = torch.autograd.grad(model.energy(y).sum(), y)
    assert (
        float((grad * field).sum(-1).abs().max().detach()) < 1e-5
    )  # dH/dt = grad H . J grad H = 0


def test_a_sympnet_is_symplectic_for_any_parameters_and_trains() -> None:
    model = dyn.SympNet(layers=4, width=8)
    points = torch.randn(6, 2)
    assert dyn.symplectic_defect(model, points) < 1e-5
    system = dyn.SYSTEMS["pendulum"]
    data = dyn.make_dynamics_data(system, 200, 0.1, seed=3)
    first = dyn.train_map(model, data, epochs=2, seed=1)
    later = dyn.train_map(model, data, epochs=100, seed=1)
    assert later < first


def test_field_models_learn_a_field_and_rollouts_score_themselves() -> None:
    system = dyn.SYSTEMS["pendulum"]
    data = dyn.make_dynamics_data(system, 300, 0.1, seed=2)
    for model in (dyn.MLPField(16), dyn.HNN(16)):
        loss = dyn.train_field(model, data, epochs=40, seed=1)
        assert math.isfinite(loss)
        score = dyn.score_rollout(system, model, 0.1, 30, (10, 30, 99))
        assert set(score.state_error_at) == {10, 30}  # a checkpoint beyond the horizon is dropped
        assert score.energy_drift >= 0.0 and score.max_energy_drift >= score.energy_drift - 1e-12


def test_a_neural_cde_reads_an_irregularly_sampled_path_and_is_differentiable() -> None:
    model = dyn.NeuralCDE(input_channels=2, hidden=8, width=16)
    times = torch.sort(torch.rand(4, 12) * 5.0, dim=1).values
    values = torch.sin(times).unsqueeze(-1)
    out = model(times, values)
    assert out.shape == (4,)
    out.sum().backward()  # type: ignore[no-untyped-call]
    assert any(p.grad is not None and float(p.grad.abs().sum()) > 0 for p in model.parameters())


# ----- mesh-free solvers ------------------------------------------------------------------------


def test_the_put_is_consistent_with_the_projects_pricer_through_put_call_parity() -> None:
    market = MarketSnapshot(
        as_of=date(2024, 1, 1), spot=1.1, risk_free_rate=var.RATE, volatility=var.SIGMA
    )
    put = black_scholes_price(market, EuropeanOption(var.STRIKE, var.MATURITY, "put"))
    assert float(var.bs_put(np.array([1.1]))[0]) == pytest.approx(put, rel=1e-10)


def test_the_geometric_basket_closed_form_matches_a_large_monte_carlo() -> None:
    x = np.full((1, 3), 1.05)
    exact = float(var.geometric_basket_price(x)[0])
    rng = np.random.default_rng(0)
    estimate = float(var.simulate_payoff(np.repeat(x, 400_000, axis=0), rng).mean())
    assert estimate == pytest.approx(exact, abs=4e-4)


def test_finite_differences_solve_the_poisson_problem_and_ritz_runs() -> None:
    points, solution = var.poisson_finite_difference(31)
    assert var.relative_l2_error(solution, var.poisson_exact(points)) < 2e-3
    result = var.train_deep_ritz(steps=3, seed=1, batch=64)
    assert math.isfinite(result.final_energy) and result.seconds >= 0.0


def test_dgm_trains_for_both_puts_and_the_american_reference_dominates_the_european() -> None:
    for american in (False, True):
        fit = var.train_dgm(american=american, steps=3, seed=1, batch=32)
        values = var.dgm_value(fit.net, np.array([0.9, 1.0, 1.1]))
        assert values.shape == (3,) and np.isfinite(values).all()
    spots = np.array([0.8, 1.0])
    assert (var.american_put_reference(spots, 200) >= var.bs_put(spots) - 1e-3).all()


def test_deep_kolmogorov_trains_predicts_and_the_monte_carlo_baseline_is_unbiased() -> None:
    fit = var.train_deep_kolmogorov(4, steps=5, seed=1, batch=64)
    x = var.kolmogorov_test_points(4, 10, 2)
    assert var.kolmogorov_predict(fit, x).shape == (10,) and fit.samples_used == 5 * 64
    mc = var.monte_carlo_estimate(x[:3], 20_000, 3)
    assert np.allclose(mc, var.geometric_basket_price(x[:3]), atol=3e-3)


# ----- the study --------------------------------------------------------------------------------


def test_the_study_states_every_hypothesis_and_discloses_what_was_seen() -> None:
    doc = study.__doc__ or ""
    for label in (
        "Z-O1",
        "Z-O2",
        "Z-O3",
        "Z-O4",
        "Z-D1",
        "Z-D2",
        "Z-D3",
        "Z-V1",
        "Z-V2",
        "Z-V3",
        "Z-V4",
    ):
        assert label in doc
    assert "What I had looked at before writing this" in doc


def test_a_tiny_operator_study_returns_every_verdict() -> None:
    result = study.operator_study((1, 2), epochs=1, n_train=40, n_test=20)
    for key in ("Z-O1", "Z-O2", "Z-O3", "Z-O4"):
        assert key in result
    assert result["Z-O2"]["verdict"] in {"SUPPORTED", "CONTRADICTED", "INCONCLUSIVE"}
    assert len(result["rows"]) == 2


def test_a_tiny_dynamics_study_returns_every_verdict() -> None:
    result = study.dynamics_study((1, 2), epochs=3, steps=20)
    assert {"Z-D1", "Z-D2", "Z-D3"} <= set(result)
    assert len(result["rows"]) == 4  # two seeds, two systems
    assert set(result["Z-D1_detail"]) == {
        f"{s}:{k}" for s in ("pendulum", "goodwin") for k in ("hnn", "sympnet")
    }


def test_a_tiny_variational_study_returns_every_verdict() -> None:
    result = study.variational_study((1, 2), solver_steps=2, kolmogorov_steps=2, dimensions=(3,))
    assert {"Z-V1", "Z-V2", "Z-V3", "Z-V4"} <= set(result)
    assert result["Z-V4_dimension"] == 3
