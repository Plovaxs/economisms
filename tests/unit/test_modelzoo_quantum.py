"""Model zoo tranche 4: the quantum simulator, amplitude estimation, QAOA, VQE, the quantum
reservoir
and the tensor train, on small cases with known answers."""

from __future__ import annotations

import math

import numpy as np
import pytest

from prometheus.modelzoo import quantum as qm
from prometheus.modelzoo import tensornet as tn
from prometheus.orchestration import modelzoo_quantum_study as study

# ----- the simulator ----------------------------------------------------------------------------


def test_single_qubit_gates_and_cnot_act_on_the_right_qubits() -> None:
    n = 3
    zero = np.zeros(8, dtype=complex)
    zero[0] = 1.0
    flipped = qm.apply_one(zero, qm._X, 1, n)  # |000> -> |010>
    assert np.argmax(np.abs(flipped)) == 0b010
    assert np.argmax(np.abs(qm.apply_cnot(flipped, 1, 2, n))) == 0b011  # control 1 set: flip 2
    assert np.argmax(np.abs(qm.apply_cnot(flipped, 2, 0, n))) == 0b010  # control 2 clear: nothing
    assert np.argmax(np.abs(qm.apply_cnot(flipped, 1, 0, n))) == 0b110  # target before control
    psi = np.random.default_rng(0).standard_normal(8) + 0j
    psi /= np.linalg.norm(psi)
    via_matrix = qm.single_site(qm.ry(0.7), 2, n) @ psi
    assert np.allclose(qm.apply_one(psi, qm.ry(0.7), 2, n), via_matrix)


# ----- amplitude estimation ---------------------------------------------------------------------


def test_the_prepared_state_has_the_option_amplitude_and_grover_rotates_it_exactly() -> None:
    dist = qm.option_distribution(5)
    psi = qm.prepared_state(dist)
    assert np.linalg.norm(psi) == pytest.approx(1.0)
    assert float(np.sum(psi[1::2] ** 2)) == pytest.approx(dist.amplitude)
    theta = math.asin(math.sqrt(dist.amplitude))
    for k in (0, 1, 4):
        assert qm.grover_probability(dist, k) == pytest.approx(math.sin((2 * k + 1) * theta) ** 2)
    assert (dist.payoff >= 0).all() and (dist.payoff <= 1).all()


def test_the_amplitude_matches_a_discounted_black_scholes_call_up_to_discretisation() -> None:
    dist = qm.option_distribution(8, span=5.0)
    top = qm.option_distribution(8, span=5.0)
    assert dist.amplitude > 0.0
    # undiscounted expected payoff = amplitude * (highest payoff); compare to the forward call
    from scipy.stats import norm

    sd, mean, strike = 0.2, math.log(100) + (0.03 - 0.02), 100.0
    forward = math.exp(mean + 0.5 * sd**2)
    d1 = (math.log(forward / strike) + 0.5 * sd**2) / sd
    exact = forward * norm.cdf(d1) - strike * norm.cdf(d1 - sd)
    edges = np.linspace(mean - 5 * sd, mean + 5 * sd, 257)
    centres = np.exp(0.5 * (edges[:-1] + edges[1:]))
    scale = centres.max() - strike
    assert dist.amplitude * scale == pytest.approx(exact, rel=2e-2)
    assert top.amplitude == dist.amplitude


def test_maximum_likelihood_estimation_recovers_the_amplitude_with_many_shots() -> None:
    dist = qm.option_distribution(6)
    rng = np.random.default_rng(1)
    estimate, calls = qm.mlae_estimate(dist.amplitude, qm.mlae_schedule(4), 2000, rng)
    assert estimate == pytest.approx(dist.amplitude, abs=2e-3)
    assert calls == 2000 * sum(2 * k + 1 for k in qm.mlae_schedule(4))
    # depolarising noise the estimator does not know about biases it
    noisy, _ = qm.mlae_estimate(dist.amplitude, qm.mlae_schedule(6), 2000, rng, depolarising=0.2)
    assert abs(noisy - dist.amplitude) > abs(estimate - dist.amplitude)


def test_the_monte_carlo_amplitude_is_unbiased() -> None:
    dist = qm.option_distribution(5)
    estimate = qm.monte_carlo_amplitude(dist, 200_000, np.random.default_rng(2))
    assert estimate == pytest.approx(dist.amplitude, abs=4e-3)


# ----- QAOA -------------------------------------------------------------------------------------


def test_the_qubo_costs_every_bitstring_and_qaoa_is_a_normalised_state() -> None:
    qubo = qm.make_portfolio_qubo(5, 2, seed=1)
    assert qubo.cost.shape == (32,)
    best = int(np.argmin(qubo.cost))
    assert bin(best).count("1") == 2  # the penalty makes the optimum pick exactly two assets
    psi = qm.qaoa_state(qubo, np.array([0.3, 0.1]), np.array([0.2, 0.4]))
    assert np.linalg.norm(psi) == pytest.approx(1.0)
    zero_depth = qm.qaoa_expectation(qubo, np.array([0.0, 0.0]))  # gamma = beta = 0: uniform state
    assert zero_depth == pytest.approx(float(qubo.cost.mean()))


def test_qaoa_beats_random_guessing_on_a_small_instance() -> None:
    qubo = qm.make_portfolio_qubo(6, 3, seed=2)
    result = qm.run_qaoa(qubo, 2, seed=1, restarts=2)
    assert 0.0 <= result.approximation_ratio <= 1.0
    assert result.expectation < float(qubo.cost.mean())
    assert result.optimum_probability > result.uniform_probability


# ----- VQE --------------------------------------------------------------------------------------


def test_the_ising_hamiltonian_is_hermitian_and_vqe_never_goes_below_the_exact_energy() -> None:
    h = qm.ising_hamiltonian(4)
    assert np.allclose(h, h.conj().T)
    exact = float(np.linalg.eigvalsh(h)[0])
    energy, reported = qm.run_vqe(4, 2, seed=1, maxiter=60)
    assert reported == pytest.approx(exact)
    assert energy >= exact - 1e-9 and (energy - exact) / abs(exact) < 0.05


def test_the_parameter_shift_gradient_matches_finite_differences() -> None:
    n, layers = 3, 2
    h = qm.ising_hamiltonian(n)
    params = np.random.default_rng(3).uniform(-1, 1, (layers + 1) * n)
    grad = qm.parameter_shift_gradient(params, h, n, layers)
    eye = np.eye(len(params))
    fd = np.array(
        [
            (
                qm.vqe_energy(params + 1e-6 * e, h, n, layers)
                - qm.vqe_energy(params - 1e-6 * e, h, n, layers)
            )
            / 2e-6
            for e in eye
        ]
    )
    assert np.allclose(grad, fd, atol=1e-6)


# ----- reservoir --------------------------------------------------------------------------------


def test_the_reservoir_is_deterministic_bounded_and_depends_on_its_input() -> None:
    inputs = np.random.default_rng(4).random(30)
    a = qm.QuantumReservoir(seed=1).run(inputs)
    b = qm.QuantumReservoir(seed=1).run(inputs)
    assert np.array_equal(a, b) and a.shape == (30, 21)
    assert (np.abs(a[:, :-1]) <= 1.0 + 1e-9).all() and (a[:, -1] == 1.0).all()
    assert not np.allclose(a, qm.QuantumReservoir(seed=1).run(1.0 - inputs))


def test_the_chaotic_series_and_the_baseline_features_behave() -> None:
    series = qm.mackey_glass(600, seed=1)
    assert 0.3 < series.min() and series.max() < 1.6 and series.std() > 0.1
    u = (series - series.min()) / (series.max() - series.min())
    ar = qm.autoregressive_features(u, 3)
    assert (
        ar.shape == (600, 4) and np.allclose(ar[3:, 0], u[3:]) and np.allclose(ar[3:, 1], u[2:-1])
    )
    assert qm.echo_state_features(u, 10, seed=1).shape == (600, 11)
    weights = qm.ridge_readout(ar[10:], u[10:], 1e-6)
    assert qm.nrmse(ar[10:] @ weights, u[10:]) < 0.2  # an AR(3) predicts its own next value well


# ----- tensor train -----------------------------------------------------------------------------


def test_tt_svd_recovers_a_low_rank_tensor_and_the_integral_agrees() -> None:
    rng = np.random.default_rng(5)
    a, b, c = (rng.standard_normal(6) for _ in range(3))
    tensor = np.einsum("i,j,k->ijk", a, b, c) + np.einsum("i,j,k->ijk", c, a, b)  # rank 2
    cores = tn.tt_svd(tensor, 1e-10)
    assert max(tn.tt_ranks(cores)) == 2
    assert np.allclose(tn.tt_to_full(cores), tensor)
    weights = rng.random(6)
    full = float(np.einsum("ijk,i,j,k->", tensor, weights, weights, weights))
    assert tn.tt_integrate(cores, weights) == pytest.approx(full, rel=1e-10)
    assert tn.tt_parameters(cores) < tensor.size


def test_gauss_hermite_weights_sum_to_one_and_the_basket_integral_is_sane() -> None:
    z, w = tn.gauss_hermite(9)
    assert w.sum() == pytest.approx(1.0) and (z * w).sum() == pytest.approx(0.0, abs=1e-12)
    tensor, weights = tn.basket_payoff_tensor(3, 9)
    full = study._full_integral(tensor, weights)
    assert full == pytest.approx(tn.monte_carlo_basket(3, 400_000, 1), rel=2e-2)
    smooth, _ = tn.basket_payoff_tensor(3, 9, smoothing=0.2)
    assert (smooth >= tensor - 1e-12).all()  # softplus dominates the kinked payoff


# ----- the study --------------------------------------------------------------------------------


def test_the_study_states_every_hypothesis_and_discloses_what_was_seen() -> None:
    doc = study.__doc__ or ""
    for label in [f"Z-Q{i}" for i in range(1, 12)] + ["Z-T1", "Z-T2", "Z-T3"]:
        assert label in doc
    assert "What I had looked at before writing this" in doc


def test_tiny_runs_of_every_family_return_their_verdicts() -> None:
    a = study.amplitude_study(repetitions=5, sizes=(2, 3))
    assert {"Z-Q1", "Z-Q2", "Z-Q3"} <= set(a) and len(a["rows"]) == 2
    q = study.qaoa_study(instances=2)
    assert {"Z-Q4", "Z-Q5", "Z-Q6"} <= set(q)
    v = study.vqe_study(seeds=2, n=3)
    assert {"Z-Q7", "Z-Q8", "Z-Q9"} <= set(v)
    r = study.reservoir_study(seeds=2, length=2800)
    assert {"Z-Q10", "Z-Q11"} <= set(r)
    t = study.tensor_study(dimensions=(3, 4, 5, 6, 7), nodes=5)
    assert {"Z-T1", "Z-T2", "Z-T3"} <= set(t) and len(t["rows"]) == 5
