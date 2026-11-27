"""Quantum algorithms for finance and PDEs, run on an ideal state-vector simulator written in NumPy.

Everything here is a SIMULATION of a noiseless (or, where stated, simply depolarised) quantum
computer
on at most eight qubits. No quantum hardware is used, and no result here is evidence about what real
hardware would do at a useful size; the point is to implement each algorithm correctly and to
measure the
one thing that can be measured honestly on a classical machine: how it behaves against a classical
method *as a function of the resources it is charged for*.

* `mlae_*`: **Quantum amplitude estimation**, in its maximum-likelihood form (Suzuki et al. 2020).
An
  option's discounted expected payoff is the amplitude `a = sin^2(theta)` of a prepared state;
  applying
  the Grover operator `k` times gives `P(1) = sin^2((2k+1) theta)`, and `theta` is estimated from
  measurements at several `k`. Charged by the number of calls to the state-preparation circuit
  (`shots * (2k+1)`), against a classical Monte Carlo charged one call per sample.
* `qaoa_*`: the **Quantum Approximate Optimisation Algorithm** (Farhi et al. 2014) on a cardinality-
  constrained portfolio-selection QUBO, against the exact optimum by enumeration.
* `vqe_*`: the **Variational Quantum Eigensolver** (Peruzzo et al. 2014) with a hardware-efficient
ansatz
  on a transverse-field Ising chain, trained with parameter-shift gradients, against exact
  diagonalisation.
* `QuantumReservoir`: **quantum reservoir computing** (Fujii and Nakajima 2017): fixed random Ising
  dynamics on five qubits driven by an input stream, a linear readout trained on measured
  expectation
  values, against an echo-state network and a linear autoregression.
"""

from __future__ import annotations

import itertools
import math
from dataclasses import dataclass
from typing import Any

import numpy as np
from scipy.linalg import expm
from scipy.optimize import minimize
from scipy.stats import norm

# ----- state-vector primitives --------------------------------------------------------------------

_X = np.array([[0, 1], [1, 0]], dtype=complex)
_Z = np.array([[1, 0], [0, -1]], dtype=complex)
_I = np.eye(2, dtype=complex)


def ry(angle: float) -> np.ndarray:
    c, s = math.cos(angle / 2), math.sin(angle / 2)
    return np.array([[c, -s], [s, c]], dtype=complex)


def rx(angle: float) -> np.ndarray:
    c, s = math.cos(angle / 2), -1j * math.sin(angle / 2)
    return np.array([[c, s], [s, c]], dtype=complex)


def apply_one(state: np.ndarray, gate: np.ndarray, qubit: int, n: int) -> np.ndarray:
    psi = state.reshape((2,) * n)
    psi = np.moveaxis(np.tensordot(gate, psi, axes=([1], [qubit])), 0, qubit)
    return np.asarray(psi.reshape(-1))


def apply_cnot(state: np.ndarray, control: int, target: int, n: int) -> np.ndarray:
    psi = state.reshape((2,) * n).copy()
    index: list[Any] = [slice(None)] * n
    index[control] = 1
    sub = psi[tuple(index)]
    axis = target if target < control else target - 1
    psi[tuple(index)] = np.flip(sub, axis=axis)
    return np.asarray(psi.reshape(-1))


def kron_all(operators: list[np.ndarray]) -> np.ndarray:
    out = np.array([[1.0 + 0j]])
    for op in operators:
        out = np.kron(out, op)
    return out


def single_site(op: np.ndarray, site: int, n: int) -> np.ndarray:
    return kron_all([op if i == site else _I for i in range(n)])


# ----- amplitude estimation -----------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class OptionDistribution:
    """A discretised risk-neutral price distribution and a normalised call payoff on it."""

    probabilities: np.ndarray
    payoff: np.ndarray  # in [0, 1]

    @property
    def amplitude(self) -> float:
        return float(self.probabilities @ self.payoff)


def option_distribution(
    qubits: int = 6,
    *,
    spot: float = 100.0,
    strike: float = 100.0,
    rate: float = 0.03,
    sigma: float = 0.2,
    maturity: float = 1.0,
    span: float = 4.0,
) -> OptionDistribution:
    """Lognormal terminal price on 2^qubits points (+/- `span` standard deviations of the log
    price)."""
    m = 2**qubits
    sd = sigma * math.sqrt(maturity)
    mean = math.log(spot) + (rate - 0.5 * sigma**2) * maturity
    edges = np.linspace(mean - span * sd, mean + span * sd, m + 1)
    cdf = norm.cdf((edges - mean) / sd)
    probabilities = np.diff(cdf)
    probabilities = probabilities / probabilities.sum()
    centres = np.exp(0.5 * (edges[:-1] + edges[1:]))
    top = max(centres.max() - strike, 1e-9)
    return OptionDistribution(
        probabilities, np.clip(np.maximum(centres - strike, 0.0) / top, 0.0, 1.0)
    )


def prepared_state(dist: OptionDistribution) -> np.ndarray:
    """sum_i sqrt(p_i) |i> (sqrt(1-f_i)|0> + sqrt(f_i)|1>): the 'good' amplitude squared is E[f]."""
    amp = np.sqrt(dist.probabilities)
    out = np.zeros((len(amp), 2))
    out[:, 0] = amp * np.sqrt(1.0 - dist.payoff)
    out[:, 1] = amp * np.sqrt(dist.payoff)
    return out.reshape(-1)


def grover_probability(dist: OptionDistribution, k: int) -> float:
    """P(ancilla = 1) after k Grover iterations, by explicit state-vector simulation."""
    psi0 = prepared_state(dist)
    good = np.zeros_like(psi0)
    good[1::2] = 1.0  # ancilla = 1
    psi = psi0.copy()
    for _ in range(k):
        psi = psi * (1.0 - 2.0 * good)  # oracle: flip the sign of the good subspace
        psi = 2.0 * psi0 * (psi0 @ psi) - psi  # reflection about the prepared state
    return float(np.sum(np.abs(psi[1::2]) ** 2))


def mlae_schedule(max_power_of_two: int) -> tuple[int, ...]:
    return (0,) + tuple(2**j for j in range(max_power_of_two + 1))


def mlae_estimate(
    amplitude: float,
    schedule: tuple[int, ...],
    shots: int,
    rng: np.random.Generator,
    *,
    depolarising: float = 0.0,
) -> tuple[float, int]:
    """Estimate `amplitude` by maximum likelihood; return (estimate, calls to the state
    preparation).

    `depolarising` is the chance that any single application of the state preparation or the Grover
    operator scrambles the qubit, which shrinks each measured probability toward 1/2 by (1 -
    d)^(2k+1);
    the estimator is NOT told about it.
    """
    theta = math.asin(math.sqrt(amplitude))
    hits: list[int] = []
    for k in schedule:
        p = math.sin((2 * k + 1) * theta) ** 2
        p = 0.5 + (p - 0.5) * (1.0 - depolarising) ** (2 * k + 1)
        hits.append(int(rng.binomial(shots, min(max(p, 0.0), 1.0))))
    grid = np.linspace(1e-6, math.pi / 2 - 1e-6, 40001)
    log_likelihood = np.zeros_like(grid)
    for k, h in zip(schedule, hits, strict=True):
        q = np.clip(np.sin((2 * k + 1) * grid) ** 2, 1e-12, 1 - 1e-12)
        log_likelihood += h * np.log(q) + (shots - h) * np.log(1.0 - q)
    best = float(grid[int(np.argmax(log_likelihood))])
    calls = shots * sum(2 * k + 1 for k in schedule)
    return math.sin(best) ** 2, calls


def monte_carlo_amplitude(
    dist: OptionDistribution, samples: int, rng: np.random.Generator
) -> float:
    idx = rng.choice(len(dist.probabilities), size=samples, p=dist.probabilities)
    return float(np.mean(rng.random(samples) < dist.payoff[idx]))


# ----- QAOA ---------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class PortfolioQUBO:
    cost: np.ndarray  # cost of every bitstring, index = integer value of the bits
    n: int


def make_portfolio_qubo(
    n: int, picks: int, *, seed: int, risk: float = 2.0, penalty: float = 2.0
) -> PortfolioQUBO:
    """Choose `picks` of `n` assets: minimise risk x'Sx - mu'x + penalty (sum x - picks)^2
    (SIMULATED data)."""
    rng = np.random.default_rng(seed)
    mu = rng.normal(0.06, 0.03, n)
    load = rng.normal(0, 0.15, (n, 3))
    cov = load @ load.T + np.diag(rng.uniform(0.01, 0.04, n))
    cost = np.zeros(2**n)
    for i, bits in enumerate(itertools.product((0, 1), repeat=n)):
        x = np.array(bits, dtype=float)
        cost[i] = risk * x @ cov @ x - mu @ x + penalty * (x.sum() - picks) ** 2
    return PortfolioQUBO(cost, n)


def qaoa_state(qubo: PortfolioQUBO, gammas: np.ndarray, betas: np.ndarray) -> np.ndarray:
    n = qubo.n
    psi = np.full(2**n, 1.0 / math.sqrt(2**n), dtype=complex)
    scale = float(np.abs(qubo.cost).max())
    for gamma, beta in zip(gammas, betas, strict=True):
        psi = psi * np.exp(-1j * gamma * qubo.cost / scale)
        mixer = rx(2.0 * beta)
        for q in range(n):
            psi = apply_one(psi, mixer, q, n)
    return psi


def qaoa_expectation(qubo: PortfolioQUBO, params: np.ndarray) -> float:
    depth = len(params) // 2
    psi = qaoa_state(qubo, params[:depth], params[depth:])
    return float(np.sum(np.abs(psi) ** 2 * qubo.cost))


@dataclass(frozen=True, slots=True)
class QAOAResult:
    expectation: float
    optimum: float
    worst: float
    approximation_ratio: float
    optimum_probability: float
    uniform_probability: float


def run_qaoa(qubo: PortfolioQUBO, depth: int, *, seed: int, restarts: int = 4) -> QAOAResult:
    rng = np.random.default_rng(seed)
    best = None
    for _ in range(restarts):
        start = rng.uniform(0.0, math.pi, 2 * depth)
        res = minimize(  # type: ignore[call-overload]
            lambda p: qaoa_expectation(qubo, p), start, method="COBYLA", options={"maxiter": 200}
        )
        if best is None or res.fun < best.fun:
            best = res
    assert best is not None  # noqa: S101 - restarts >= 1 by construction
    psi = qaoa_state(qubo, best.x[:depth], best.x[depth:])
    probabilities = np.abs(psi) ** 2
    optimum, worst = float(qubo.cost.min()), float(qubo.cost.max())
    return QAOAResult(
        expectation=float(best.fun),
        optimum=optimum,
        worst=worst,
        approximation_ratio=(worst - float(best.fun)) / (worst - optimum),
        optimum_probability=float(probabilities[int(np.argmin(qubo.cost))]),
        uniform_probability=1.0 / len(qubo.cost),
    )


# ----- VQE ----------------------------------------------------------------------------------------


def ising_hamiltonian(n: int, field: float = 1.0) -> np.ndarray:
    """Open transverse-field Ising chain: H = -sum Z_i Z_{i+1} - field * sum X_i."""
    h = np.zeros((2**n, 2**n), dtype=complex)
    for i in range(n - 1):
        h -= single_site(_Z, i, n) @ single_site(_Z, i + 1, n)
    for i in range(n):
        h -= field * single_site(_X, i, n)
    return h


def ansatz_state(params: np.ndarray, n: int, layers: int) -> np.ndarray:
    """Hardware-efficient ansatz: `layers` of (RY on every qubit, CNOT chain), then a final RY
    layer."""
    psi = np.zeros(2**n, dtype=complex)
    psi[0] = 1.0
    p = params.reshape(layers + 1, n)
    for layer in range(layers):
        for q in range(n):
            psi = apply_one(psi, ry(p[layer, q]), q, n)
        for q in range(n - 1):
            psi = apply_cnot(psi, q, q + 1, n)
    for q in range(n):
        psi = apply_one(psi, ry(p[layers, q]), q, n)
    return psi


def vqe_energy(params: np.ndarray, hamiltonian: np.ndarray, n: int, layers: int) -> float:
    psi = ansatz_state(params, n, layers)
    return float(np.real(np.conj(psi) @ hamiltonian @ psi))


def parameter_shift_gradient(
    params: np.ndarray, hamiltonian: np.ndarray, n: int, layers: int
) -> np.ndarray:
    """Exact for rotation gates: dE/dtheta_j = (E(theta_j + pi/2) - E(theta_j - pi/2)) / 2."""
    grad = np.zeros_like(params)
    for j in range(len(params)):
        plus, minus = params.copy(), params.copy()
        plus[j] += math.pi / 2
        minus[j] -= math.pi / 2
        grad[j] = 0.5 * (
            vqe_energy(plus, hamiltonian, n, layers) - vqe_energy(minus, hamiltonian, n, layers)
        )
    return grad


def run_vqe(
    n: int, layers: int, *, seed: int, field: float = 1.0, maxiter: int = 150
) -> tuple[float, float]:
    """Return (VQE energy, exact ground energy)."""
    h = ising_hamiltonian(n, field)
    exact = float(np.linalg.eigvalsh(h)[0])
    start = np.random.default_rng(seed).uniform(-0.1, 0.1, (layers + 1) * n)
    res = minimize(  # type: ignore[call-overload]
        lambda p: vqe_energy(p, h, n, layers),
        start,
        jac=lambda p: parameter_shift_gradient(p, h, n, layers),
        method="BFGS",
        options={"maxiter": maxiter},
    )
    return float(res.fun), exact


# ----- quantum reservoir computing ----------------------------------------------------------------


class QuantumReservoir:
    """Five-qubit random Ising reservoir with the first qubit re-prepared from the input at
    every step."""

    def __init__(self, n: int = 5, *, seed: int, tau: float = 1.0) -> None:
        rng = np.random.default_rng(seed)
        self.n = n
        h = np.zeros((2**n, 2**n), dtype=complex)
        for i, j in itertools.combinations(range(n), 2):
            h += rng.uniform(-1, 1) * single_site(_Z, i, n) @ single_site(_Z, j, n)
        for i in range(n):
            h += rng.uniform(0.5, 1.5) * single_site(_X, i, n)
        self.unitary = expm(-1j * h * tau)
        self.observables = (
            [single_site(_Z, i, n) for i in range(n)]
            + [single_site(_X, i, n) for i in range(n)]
            + [
                single_site(_Z, i, n) @ single_site(_Z, j, n)
                for i, j in itertools.combinations(range(n), 2)
            ]
        )

    @property
    def feature_count(self) -> int:
        return len(self.observables) + 1

    def run(self, inputs: np.ndarray) -> np.ndarray:
        """Features after each input in [0, 1]: expectation values of Z, X and ZZ, plus a
        constant."""
        dim = 2**self.n
        rho = np.zeros((dim, dim), dtype=complex)
        rho[0, 0] = 1.0
        features = np.zeros((len(inputs), self.feature_count))
        for t, u in enumerate(inputs):
            tail = rho.reshape(2, dim // 2, 2, dim // 2)
            reduced = np.einsum("aiaj->ij", tail)  # trace out qubit 0
            qubit = np.array([math.cos(math.pi * u / 2), math.sin(math.pi * u / 2)], dtype=complex)
            rho = np.kron(np.outer(qubit, qubit.conj()), reduced)
            rho = self.unitary @ rho @ self.unitary.conj().T
            features[t, :-1] = [float(np.real(np.trace(rho @ obs))) for obs in self.observables]
            features[t, -1] = 1.0
        return features


def mackey_glass(length: int, *, tau: int = 17, seed: int = 0) -> np.ndarray:
    """The Mackey-Glass delay equation, sampled once per time unit (Euler steps of 0.1)."""
    rng = np.random.default_rng(seed)
    steps_per_unit = 10
    history = 1.2 + 0.05 * rng.standard_normal(tau * steps_per_unit + 1)
    x = list(history)
    total = (length + 500) * steps_per_unit
    for _ in range(total):
        delayed = x[-tau * steps_per_unit - 1]
        x.append(x[-1] + 0.1 * (0.2 * delayed / (1.0 + delayed**10) - 0.1 * x[-1]))
    series = np.array(x[tau * steps_per_unit + 1 :])[::steps_per_unit]
    return np.asarray(series[500 : 500 + length])


def ridge_readout(features: np.ndarray, target: np.ndarray, penalty: float) -> np.ndarray:
    gram = features.T @ features + penalty * np.eye(features.shape[1])
    return np.asarray(np.linalg.solve(gram, features.T @ target))


def nrmse(pred: np.ndarray, truth: np.ndarray) -> float:
    return float(np.sqrt(np.mean((pred - truth) ** 2)) / np.std(truth))


def echo_state_features(
    inputs: np.ndarray, size: int, *, seed: int, radius: float = 0.9
) -> np.ndarray:
    rng = np.random.default_rng(seed)
    w = rng.standard_normal((size, size))
    w *= radius / float(np.max(np.abs(np.linalg.eigvals(w))))
    w_in = rng.uniform(-1, 1, size)
    state = np.zeros(size)
    features = np.zeros((len(inputs), size + 1))
    for t, u in enumerate(inputs):
        state = np.tanh(w @ state + w_in * (u - 0.5))
        features[t, :-1] = state
        features[t, -1] = 1.0
    return features


def autoregressive_features(series: np.ndarray, lags: int) -> np.ndarray:
    out = np.zeros((len(series), lags + 1))
    for lag in range(lags):
        out[lag:, lag] = series[: len(series) - lag]
    out[:, -1] = 1.0
    return out
