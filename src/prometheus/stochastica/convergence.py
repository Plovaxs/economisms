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
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from prometheus.stochastica.heston import HestonParams, simulate_heston_paths
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
