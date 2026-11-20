"""GARCH(1,1) and GJR-GARCH(1,1) by Gaussian quasi-maximum likelihood.

    r_t = mu + e_t,   e_t = sqrt(h_t) z_t
    h_t = omega + (alpha + gamma * 1[e_{t-1} < 0]) * e_{t-1}^2 + beta * h_{t-1}

`gamma = 0` is the symmetric GARCH(1,1). `gamma > 0` is the leverage effect: a negative
return raises tomorrow's variance by more than a positive return of the same size (Glosten,
Jagannathan & Runkle 1993). For a symmetric innovation law the indicator is 1 half the time,
so the persistence is `alpha + gamma/2 + beta` and stationarity needs it below 1.

Why a second fitter beside `neural_sde.benchmark.fit_garch11`: that one caps
`alpha + beta` at 0.98 -- a disclosed limitation that understates the near-unit persistence of
equity volatility -- and evaluates its likelihood in a Python loop over every observation. The
variance recursion is a first-order linear filter driven by terms that depend only on the
OBSERVED returns, so `scipy.signal.lfilter` evaluates it in one vectorised call; a fit then
takes milliseconds, which makes a multi-start, constrained (SLSQP) search with a persistence
cap of 0.999 affordable. Fitting the symmetric model with this SAME optimiser and cap makes
"does asymmetry help?" a clean comparison, instead of one confounded by two different fitters.

Units: callers pass returns as decimals (0.01 = 1%). The optimiser works in percent internally
(`omega` is then ~1e-4 percent^2 rather than 1e-8, which keeps finite-difference gradients
well scaled) and converts back, so the stored parameters are in decimal units.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy import optimize
from scipy.signal import lfilter

DEFAULT_MAX_PERSISTENCE = 0.999
_PERCENT = 100.0
_STARTS: tuple[tuple[float, float, float], ...] = (
    (0.05, 0.05, 0.88),
    (0.02, 0.08, 0.90),
    (0.08, 0.02, 0.85),
)
"""Starting (alpha, gamma, beta) values; the best optimum over them is kept."""
_CONSTRAINT_SLACK = 1e-5
"""How far past the persistence cap an SLSQP end point may land and still be projected back."""


def _filter_variances(
    centered: np.ndarray,
    omega: float,
    alpha: float,
    gamma: float,
    beta: float,
    initial_variance: float,
) -> np.ndarray:
    """h_t for every t: h_0 = `initial_variance`, then the recursion above. h_t uses
    `centered[:t]` only (the variance for day t is known before day t's return)."""
    n = centered.size
    drive = np.empty(n)
    drive[0] = initial_variance
    squared = centered[:-1] ** 2
    drive[1:] = omega + (alpha + gamma * (centered[:-1] < 0.0)) * squared
    return np.asarray(lfilter([1.0], [1.0, -beta], drive), dtype=np.float64)


def _negative_log_likelihood(
    theta: np.ndarray, returns: np.ndarray, initial_variance: float
) -> float:
    mu, omega, alpha, gamma, beta = theta
    centered = returns - mu
    h = _filter_variances(centered, omega, alpha, gamma, beta, initial_variance)
    if not np.all(np.isfinite(h)) or np.any(h <= 0.0):
        return 1e18
    return float(0.5 * np.sum(np.log(2.0 * np.pi * h) + centered**2 / h))


@dataclass(frozen=True, slots=True)
class FittedGarchFamily:
    """Parameters in DECIMAL units, plus the variance the filter starts from.
    `negative_log_likelihood` is of the TRAINING sample, also in decimal units (the
    optimiser works in percent, which adds `n * ln(100)`; that is removed again)."""

    mu: float
    omega: float
    alpha: float
    gamma: float
    beta: float
    initial_variance: float
    negative_log_likelihood: float

    @property
    def persistence(self) -> float:
        return self.alpha + self.gamma / 2.0 + self.beta

    def conditional_variances(self, returns: np.ndarray) -> np.ndarray:
        """One-step-ahead variance h_t for every return, filtering `returns` from the
        start with this fit. Element t depends on `returns[:t]` only, so the array can
        be sliced to a test window without leaking the future."""
        centered = np.asarray(returns, dtype=np.float64) - self.mu
        return _filter_variances(
            centered, self.omega, self.alpha, self.gamma, self.beta, self.initial_variance
        )

    def negative_log_likelihood_of(self, returns: np.ndarray) -> float:
        """Gaussian negative log-likelihood of `returns` under THIS parameter set."""
        values = np.asarray(returns, dtype=np.float64)
        h = self.conditional_variances(values)
        return float(0.5 * np.sum(np.log(2.0 * np.pi * h) + (values - self.mu) ** 2 / h))

    def standardised_residuals(self, returns: np.ndarray) -> np.ndarray:
        values = np.asarray(returns, dtype=np.float64)
        return np.asarray(
            (values - self.mu) / np.sqrt(self.conditional_variances(values)), dtype=np.float64
        )


def fit_garch_family(
    train_returns: np.ndarray,
    *,
    asymmetric: bool,
    max_persistence: float = DEFAULT_MAX_PERSISTENCE,
) -> FittedGarchFamily:
    """Gaussian QMLE. `asymmetric=False` fixes `gamma = 0` (a symmetric GARCH(1,1)) and
    uses the same optimiser, starts and persistence cap, so the two are comparable."""
    if not 0.0 < max_persistence < 1.0:
        raise ValueError("max_persistence must lie strictly between 0 and 1")
    values = np.asarray(train_returns, dtype=np.float64)
    if values.ndim != 1 or values.size < 100:
        raise ValueError("need a 1-D array of at least 100 returns")
    if not np.all(np.isfinite(values)):
        raise ValueError("returns must be finite")
    percent = values * _PERCENT
    variance = float(percent.var())
    if variance <= 0.0:
        raise ValueError("returns have zero variance")

    gamma_upper = 1.0 if asymmetric else 0.0
    bounds = [
        (float(np.min(percent)), float(np.max(percent))),  # mu
        (1e-8 * variance, variance),  # omega (percent^2)
        (0.0, 1.0),  # alpha
        (0.0, gamma_upper),  # gamma
        (0.0, 1.0),  # beta
    ]
    # persistence = alpha + gamma / 2 + beta <= max_persistence, a LINEAR constraint on theta
    persistence_row = np.array([[0.0, 0.0, 1.0, 0.5, 1.0]])
    constraint = optimize.LinearConstraint(persistence_row, -np.inf, max_persistence)

    best_value = np.inf
    best_theta: np.ndarray | None = None
    for start_alpha, start_gamma, start_beta in _STARTS:
        gamma0 = start_gamma if asymmetric else 0.0
        persistence0 = min(start_alpha + gamma0 / 2.0 + start_beta, max_persistence - 0.01)
        x0 = np.array(
            [
                float(percent.mean()),
                variance * (1.0 - persistence0),
                start_alpha,
                gamma0,
                start_beta,
            ]
        )
        result = optimize.minimize(
            _negative_log_likelihood,
            x0,
            args=(percent, variance),
            method="SLSQP",
            bounds=bounds,
            constraints=constraint,
            options={"maxiter": 300, "ftol": 1e-10},
        )
        theta = np.array(result.x, dtype=np.float64)
        persistence = float(theta[2] + theta[3] / 2.0 + theta[4])
        if persistence > max_persistence + _CONSTRAINT_SLACK:
            continue  # a genuinely infeasible end point, not rounding at the boundary
        if persistence > max_persistence:
            # SLSQP stops AT the boundary, often by 1e-8: shrink the three dynamics
            # parameters proportionally so the cap holds exactly.
            theta[2:5] *= max_persistence / persistence
        value = _negative_log_likelihood(theta, percent, variance)
        if value < best_value:
            best_value, best_theta = value, theta
    if best_theta is None:  # pragma: no cover - the starts are all feasible
        raise RuntimeError("no feasible GARCH fit")
    mu, omega, alpha, gamma, beta = (float(v) for v in best_theta)
    return FittedGarchFamily(
        mu=mu / _PERCENT,
        omega=omega / _PERCENT**2,
        alpha=alpha,
        gamma=gamma,
        beta=beta,
        initial_variance=variance / _PERCENT**2,
        negative_log_likelihood=best_value - values.size * float(np.log(_PERCENT)),
    )


def simulate_gjr_garch(
    n: int,
    *,
    mu: float,
    omega: float,
    alpha: float,
    gamma: float,
    beta: float,
    seed: int,
    burn_in: int = 500,
) -> np.ndarray:
    """Draw `n` returns from the model (normal innovations) -- the known-answer source for
    the tests. The recursion is inherently sequential, so this is a plain loop."""
    rng = np.random.default_rng(seed)
    persistence = alpha + gamma / 2.0 + beta
    if persistence >= 1.0:
        raise ValueError("a stationary simulation needs persistence below 1")
    shocks = rng.standard_normal(n + burn_in)
    out = np.empty(n + burn_in)
    h = omega / (1.0 - persistence)
    previous = 0.0
    for t in range(n + burn_in):
        if t > 0:
            h = omega + (alpha + gamma * (previous < 0.0)) * previous**2 + beta * h
        previous = float(np.sqrt(h) * shocks[t])
        out[t] = mu + previous
    return np.asarray(out[burn_in:], dtype=np.float64)
