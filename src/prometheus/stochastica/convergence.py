"""Numerical convergence diagnostics for stochastic integrators (SDE-05:
"numerical time-step refinement experiments... path distribution
stability as dt decreases is reported"; VAL-03: "Define strong/weak
convergence checks for stochastic integrators").

GBM (`stochastica.gbm`) and the jump-diffusion simulator
(`stochastica.jump_diffusion`) both draw from EXACT transition laws (no
Euler discretization at all), so there is no discretization bias to
study for either -- this module targets `stochastica.heston`'s log-
Euler/full-truncation scheme, the one simulator in this repository that
actually has genuine, non-zero discretization bias as a function of step
size.

Weak convergence order. For a scheme with weak order p, the bias of a
smooth payoff's expectation shrinks like Bias(dt) = C * dt^p + o(dt^p) as
dt -> 0 (Kloeden & Platen, 1992). `estimate_weak_convergence_order` fits
this via ordinary least squares on log|bias| against log(dt) -- the
standard practical estimator, verified here against two synthetic cases
with an EXACTLY known order (pure dt^1 and pure dt^2 decay, recovering
1.0 and 2.0 to high precision) before being applied to the real Heston
result.

`heston_weak_convergence_study` computes Monte Carlo bias (against the
closed-form `heston_option_price` reference) at several step counts,
batching paths (never materializing one huge `(n_paths, n_steps+1)`
array) -- a memory-unsafe first draft of this exact calculation drove
system memory from 4GB to 26GB/31GB (swap nearly exhausted) before being
caught and fixed, during this module's own pre-implementation
verification; the batching here is not a stylistic preference, it is a
direct response to that near-miss.

Strong convergence order (audit item M-01, Heston half). Weak order is about the AVERAGE payoff;
strong order is about the PATH: E|X_T(dt) - X_T| = C dt^q. Heston has no closed-form path, so
`heston_strong_convergence_study` uses the standard device: draw ONE fine Brownian path per
sample, run the scheme on it at the finest grid (the reference) and again on every coarser grid
driven by the SUMS of the same fine increments, and measure each coarse terminal state against the
reference. The reference carries its own discretization error, so the fitted order is biased
slightly low if the reference is not much finer than the finest tested grid (here: require 8x).
What is measured, not assumed: for the full-truncation scheme the order is about 1/2 when the
Feller condition holds (2 kappa theta / xi^2 >= 1) and falls well below it when it is violated,
which is the regime of calibrated equity Heston parameters.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from prometheus.stochastica.heston import HestonParams, heston_step, simulate_heston_paths
from prometheus.volterra.heston_pricer import heston_call_price


def estimate_weak_convergence_order(dts: list[float], biases: list[float]) -> float:
    """log-log OLS slope of |bias| against dt. Requires at least 2 points
    and every bias strictly nonzero (log(0) is undefined; a zero bias
    would also make the whole comparison meaningless rather than
    unusually good)."""
    if len(dts) < 2:
        raise ValueError("at least 2 (dt, bias) points are required")
    if len(dts) != len(biases):
        raise ValueError("dts and biases must have the same length")
    if any(b == 0.0 for b in biases):
        raise ValueError("every bias must be nonzero to take its logarithm")
    log_dt = np.log(np.asarray(dts, dtype=float))
    log_abs_bias = np.log(np.abs(np.asarray(biases, dtype=float)))
    slope, _intercept = np.polyfit(log_dt, log_abs_bias, 1)
    return float(slope)


@dataclass(frozen=True, slots=True)
class ConvergencePoint:
    n_steps: int
    dt: float
    mc_price: float
    mc_standard_error: float
    bias: float


@dataclass(frozen=True, slots=True)
class WeakConvergenceStudy:
    reference_price: float
    points: list[ConvergencePoint]
    """Sorted by increasing n_steps (decreasing dt)."""
    fitted_order: float

    def bias_decreases_monotonically(self) -> bool:
        """True if |bias| strictly decreases as dt shrinks -- a cheap,
        noise-robust sanity check independent of the fitted order."""
        magnitudes = [abs(p.bias) for p in self.points]
        return all(a > b for a, b in zip(magnitudes, magnitudes[1:], strict=False))


def heston_weak_convergence_study(
    s0: float,
    strike: float,
    maturity: float,
    risk_free_rate: float,
    dividend_yield: float,
    params: HestonParams,
    step_counts: list[int],
    n_paths_per_batch: int,
    n_batches: int,
    rng: np.random.Generator,
) -> WeakConvergenceStudy:
    if len(step_counts) < 2:
        raise ValueError("at least 2 step counts are required to fit a convergence order")
    if sorted(step_counts) != list(step_counts) or len(set(step_counts)) != len(step_counts):
        raise ValueError("step_counts must be strictly increasing with no duplicates")
    if n_paths_per_batch < 1 or n_batches < 1:
        raise ValueError("n_paths_per_batch and n_batches must each be a positive integer")

    reference_price = heston_call_price(
        s0, strike, maturity, risk_free_rate, dividend_yield, params
    )
    discount = math.exp(-risk_free_rate * maturity)

    points: list[ConvergencePoint] = []
    for n_steps in step_counts:
        total_sum = 0.0
        total_sumsq = 0.0
        total_n = 0
        for _ in range(n_batches):
            price_paths, _variance_paths = simulate_heston_paths(
                s0, params, maturity, n_steps, n_paths_per_batch, rng
            )
            terminal = price_paths[:, -1]
            payoff = np.maximum(terminal - strike, 0.0)
            discounted = discount * payoff
            total_sum += float(discounted.sum())
            total_sumsq += float((discounted**2).sum())
            total_n += n_paths_per_batch
            del price_paths, _variance_paths, terminal, payoff, discounted

        mc_price = total_sum / total_n
        variance = max(total_sumsq / total_n - mc_price**2, 0.0)
        mc_standard_error = math.sqrt(variance / total_n)
        dt = maturity / n_steps
        points.append(
            ConvergencePoint(
                n_steps=n_steps,
                dt=dt,
                mc_price=mc_price,
                mc_standard_error=mc_standard_error,
                bias=mc_price - reference_price,
            )
        )

    fitted_order = estimate_weak_convergence_order(
        [p.dt for p in points], [p.bias for p in points]
    )
    return WeakConvergenceStudy(
        reference_price=reference_price, points=points, fitted_order=fitted_order
    )


@dataclass(frozen=True, slots=True)
class StrongConvergencePoint:
    n_steps: int
    dt: float
    log_price_error: float
    """Mean of |log S_T(dt) - log S_T(reference)| over the sampled paths."""
    log_price_standard_error: float
    variance_error: float
    """Mean of |v_T(dt) - v_T(reference)|."""
    variance_standard_error: float


@dataclass(frozen=True, slots=True)
class StrongConvergenceStudy:
    reference_steps: int
    points: list[StrongConvergencePoint]
    """Sorted by increasing n_steps (decreasing dt)."""
    log_price_order: float
    variance_order: float
    feller_ratio: float


def heston_strong_convergence_study(
    params: HestonParams,
    maturity: float,
    step_counts: list[int],
    reference_steps: int,
    n_paths_per_batch: int,
    n_batches: int,
    rng: np.random.Generator,
) -> StrongConvergenceStudy:
    """Pathwise error of the log-Euler / full-truncation scheme against the same scheme on a finer
    grid driven by the same Brownian path; the module docstring has the method and its caveat."""
    if len(step_counts) < 2:
        raise ValueError("at least 2 step counts are required to fit a convergence order")
    if sorted(step_counts) != list(step_counts) or len(set(step_counts)) != len(step_counts):
        raise ValueError("step_counts must be strictly increasing with no duplicates")
    if step_counts[0] < 1 or maturity <= 0:
        raise ValueError("step counts must be >= 1 and maturity positive")
    if any(reference_steps % n != 0 for n in step_counts):
        raise ValueError("every step count must divide reference_steps")
    if reference_steps < 8 * step_counts[-1]:
        raise ValueError(
            "reference_steps must be at least 8x the finest tested grid, or the reference's own "
            "error biases the fitted order"
        )
    if n_paths_per_batch < 1 or n_batches < 1:
        raise ValueError("n_paths_per_batch and n_batches must each be a positive integer")

    def run(n_steps: int, dw_s: np.ndarray, dw_v: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        group = reference_steps // n_steps
        dt = maturity / n_steps
        coarse_s = dw_s.reshape(n_paths_per_batch, n_steps, group).sum(axis=2)
        coarse_v = dw_v.reshape(n_paths_per_batch, n_steps, group).sum(axis=2)
        log_s = np.zeros(n_paths_per_batch)
        v = np.full(n_paths_per_batch, params.v0)
        for t in range(n_steps):
            log_s, v = heston_step(log_s, v, params, dt, coarse_s[:, t], coarse_v[:, t])
        return log_s, v

    sums = {n: np.zeros(4) for n in step_counts}  # sum|e_S|, sum e_S^2, sum|e_v|, sum e_v^2
    sqrt_dt_ref = math.sqrt(maturity / reference_steps)
    rho_c = math.sqrt(1.0 - params.rho**2)
    for _ in range(n_batches):
        z1 = rng.standard_normal((n_paths_per_batch, reference_steps))
        z2 = rng.standard_normal((n_paths_per_batch, reference_steps))
        dw_s = z1 * sqrt_dt_ref
        dw_v = (params.rho * z1 + rho_c * z2) * sqrt_dt_ref
        ref_log_s, ref_v = run(reference_steps, dw_s, dw_v)
        for n in step_counts:
            log_s, v = run(n, dw_s, dw_v)
            e_s = np.abs(log_s - ref_log_s)
            e_v = np.abs(v - ref_v)
            sums[n] += (e_s.sum(), (e_s**2).sum(), e_v.sum(), (e_v**2).sum())
        del z1, z2, dw_s, dw_v

    total = n_paths_per_batch * n_batches
    points: list[StrongConvergencePoint] = []
    for n in step_counts:
        s_abs, s_sq, v_abs, v_sq = sums[n]
        mean_s, mean_v = s_abs / total, v_abs / total
        points.append(
            StrongConvergencePoint(
                n_steps=n,
                dt=maturity / n,
                log_price_error=mean_s,
                log_price_standard_error=math.sqrt(max(s_sq / total - mean_s**2, 0.0) / total),
                variance_error=mean_v,
                variance_standard_error=math.sqrt(max(v_sq / total - mean_v**2, 0.0) / total),
            )
        )
    dts = [p.dt for p in points]
    return StrongConvergenceStudy(
        reference_steps=reference_steps,
        points=points,
        log_price_order=estimate_weak_convergence_order(dts, [p.log_price_error for p in points]),
        variance_order=estimate_weak_convergence_order(dts, [p.variance_error for p in points]),
        feller_ratio=params.feller_ratio(),
    )
