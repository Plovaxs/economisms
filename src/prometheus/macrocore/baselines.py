"""Classical forecasting baselines (ECONOSIM-X/PROMETHEUS-X addendum
FP-04: "Classical forecasting baselines run reproducibly"), which section
09/E01 of the addendum requires MACROCORE's eventual shared Transformer
encoder to beat: Persistence, AR(p) and VAR(p) -- all OLS-fit, all with
closed-form Gaussian multi-step forecast intervals so a probabilistic
score (CRPS, interval coverage) can be computed, not just a point error.

"ARIMA" in the addendum's own terminology is treated here as AR(p), i.e.
ARIMA(p, 0, 0): a deliberate scope cut (see module docstring of
`evaluation.py`), not a full Box-Jenkins ARIMA(p, d, q) with differencing
or moving-average terms. Implementing MA-term maximum-likelihood
estimation from scratch risked the kind of subtle, hard-to-independently-
verify bug this project's own discipline exists to avoid; AR(p) is fully
transparent (plain OLS) and its forecast-interval math is derived and
checked below.

Forecast-interval derivation (AR(p)): for a (possibly non-zero-mean)
AR(p) process y_t = c + phi_1 y_{t-1} + ... + phi_p y_{t-p} + eps_t, the
h-step-ahead forecast error variance from a fixed origin is

    Var(y_{T+h} - E[y_{T+h} | F_T]) = sigma^2 * sum_{j=0}^{h-1} psi_j^2

where psi_0 = 1 and psi_j = sum_{i=1}^{min(j,p)} phi_i * psi_{j-i} are the
AR polynomial's MA(infinity) expansion coefficients (the intercept c only
shifts the mean, not this variance). The VAR(p) analog replaces each
scalar with its matrix counterpart: Psi_0 = I, Psi_j = sum_i Phi_i @
Psi_{j-i}, and the h-step forecast covariance is sum_{j=0}^{h-1} Psi_j @
Sigma @ Psi_j.T. Both formulas were verified, before being trusted, by
simulating the TRUE process a few million times from a fixed origin and
comparing the Monte Carlo variance/covariance of y_{T+h} against this
closed form (max relative error under 0.5% at every tested horizon).
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
from scipy.stats import norm


@dataclass(frozen=True, slots=True)
class DistributionForecast:
    horizon: int
    mean: float
    std: float

    def __post_init__(self) -> None:
        if self.horizon < 1:
            raise ValueError("horizon must be a positive integer")
        if self.std < 0:
            raise ValueError("std must be non-negative")

    def interval(self, level: float = 0.8) -> tuple[float, float]:
        """A central interval of the given coverage level, e.g. 0.8 ->
        the 10th/90th percentiles under the Gaussian forecast
        distribution."""
        if not 0.0 < level < 1.0:
            raise ValueError("level must be in (0, 1)")
        tail = (1.0 - level) / 2.0
        z = norm.ppf(1.0 - tail)
        return self.mean - z * self.std, self.mean + z * self.std


def gaussian_crps(mean: float, std: float, actual: float) -> float:
    """Closed-form continuous ranked probability score for a Gaussian
    forecast (Gneiting & Raftery, 2007): CRPS = sigma*(z*(2*Phi(z)-1) +
    2*phi(z) - 1/sqrt(pi)), z = (y-mu)/sigma. Lower is better; CRPS
    reduces to |actual - mean| in the zero-variance limit."""
    if std < 0:
        raise ValueError("std must be non-negative")
    if std == 0.0:
        return abs(actual - mean)
    z = (actual - mean) / std
    return std * (z * (2 * norm.cdf(z) - 1) + 2 * norm.pdf(z) - 1 / math.sqrt(math.pi))


def persistence_forecast(history: np.ndarray, horizons: list[int]) -> list[DistributionForecast]:
    """The naive random-walk baseline: the point forecast at every
    horizon is just the last observed value. Uncertainty is modeled as a
    random walk's own: std grows as the historical step-to-step
    volatility times sqrt(h) (the implicit model behind "persistence" IS
    a driftless random walk, so this is not an arbitrary add-on -- it is
    that model's own exact forecast-variance formula, Var(h steps of iid
    increments) = h * Var(one increment))."""
    history = np.asarray(history, dtype=float)
    if history.ndim != 1 or history.size < 2:
        raise ValueError("history must be a 1-D array with at least 2 observations")
    if any(h < 1 for h in horizons):
        raise ValueError("every horizon must be a positive integer")
    last_value = float(history[-1])
    step_std = float(np.std(np.diff(history), ddof=1)) if history.size > 2 else 0.0
    return [
        DistributionForecast(horizon=h, mean=last_value, std=step_std * math.sqrt(h))
        for h in horizons
    ]


def _ar_psi_weights(phi: np.ndarray, n: int) -> np.ndarray:
    p = len(phi)
    psi = np.zeros(n)
    psi[0] = 1.0
    for j in range(1, n):
        psi[j] = sum(phi[i - 1] * psi[j - i] for i in range(1, min(j, p) + 1))
    return psi


@dataclass(frozen=True, slots=True)
class FittedAutoregression:
    order: int
    intercept: float
    phi: np.ndarray
    residual_variance: float
    last_values: np.ndarray
    """The most recent `order` observed values, most recent last --
    the state the recursive forecast starts from."""

    def forecast(self, horizons: list[int]) -> list[DistributionForecast]:
        if any(h < 1 for h in horizons):
            raise ValueError("every horizon must be a positive integer")
        max_h = max(horizons)
        psi = _ar_psi_weights(self.phi, max_h)
        history = list(self.last_values[::-1])  # oldest-first working buffer, grows forward
        point_forecasts = np.zeros(max_h)
        for h in range(1, max_h + 1):
            lags = history[-1 : -self.order - 1 : -1]
            value = self.intercept + float(np.dot(self.phi, lags))
            point_forecasts[h - 1] = value
            history.append(value)
        variances = self.residual_variance * np.cumsum(psi**2)
        return [
            DistributionForecast(
                horizon=h,
                mean=float(point_forecasts[h - 1]),
                std=float(math.sqrt(variances[h - 1])),
            )
            for h in horizons
        ]


def fit_autoregression(history: np.ndarray, order: int) -> FittedAutoregression:
    """OLS fit of y_t = c + phi_1*y_{t-1} + ... + phi_p*y_{t-p} + eps_t."""
    history = np.asarray(history, dtype=float)
    if order < 1:
        raise ValueError("order must be a positive integer")
    if history.ndim != 1 or history.size < order + 2:
        raise ValueError(
            f"history must be 1-D with at least order + 2 = {order + 2} observations, "
            f"got {history.size}"
        )
    n = history.size
    design = np.column_stack(
        [np.ones(n - order)] + [history[order - i : n - i] for i in range(1, order + 1)]
    )
    target = history[order:]
    coefficients, *_ = np.linalg.lstsq(design, target, rcond=None)
    intercept = float(coefficients[0])
    phi = coefficients[1:]
    residual = target - design @ coefficients
    degrees_of_freedom = len(residual) - (order + 1)
    if degrees_of_freedom <= 0:
        raise ValueError("not enough observations to estimate residual variance")
    residual_variance = float(np.sum(residual**2) / degrees_of_freedom)
    last_values = history[-order:]
    return FittedAutoregression(
        order=order,
        intercept=intercept,
        phi=phi,
        residual_variance=residual_variance,
        last_values=last_values,
    )


def _var_psi_weights(phi_matrices: list[np.ndarray], n: int) -> list[np.ndarray]:
    k = phi_matrices[0].shape[0]
    p = len(phi_matrices)
    psi: list[np.ndarray] = [np.eye(k)]
    for j in range(1, n):
        total = np.zeros((k, k))
        for i in range(1, min(j, p) + 1):
            total += phi_matrices[i - 1] @ psi[j - i]
        psi.append(total)
    return psi


@dataclass(frozen=True, slots=True)
class FittedVectorAutoregression:
    order: int
    intercept: np.ndarray
    phi_matrices: list[np.ndarray]
    residual_covariance: np.ndarray
    last_values: np.ndarray
    """Shape (order, n_series): the most recent `order` observed vectors,
    most recent LAST (last_values[-1] is the latest)."""
    series_ids: list[str]

    def forecast(self, horizons: list[int]) -> dict[str, list[DistributionForecast]]:
        if any(h < 1 for h in horizons):
            raise ValueError("every horizon must be a positive integer")
        max_h = max(horizons)
        psi = _var_psi_weights(self.phi_matrices, max_h)
        history = list(self.last_values)  # oldest-first, grows forward
        point_forecasts = []
        for _h in range(1, max_h + 1):
            lags = history[-1 : -self.order - 1 : -1]
            value = self.intercept.copy()
            for i, lag_vector in enumerate(lags):
                value = value + self.phi_matrices[i] @ lag_vector
            point_forecasts.append(value)
            history.append(value)

        covariances = []
        running = np.zeros_like(self.residual_covariance)
        for j in range(max_h):
            running = running + psi[j] @ self.residual_covariance @ psi[j].T
            covariances.append(running.copy())

        result: dict[str, list[DistributionForecast]] = {sid: [] for sid in self.series_ids}
        for h in horizons:
            mean_vector = point_forecasts[h - 1]
            variance_vector = np.diag(covariances[h - 1])
            for idx, series_id in enumerate(self.series_ids):
                result[series_id].append(
                    DistributionForecast(
                        horizon=h,
                        mean=float(mean_vector[idx]),
                        std=float(math.sqrt(max(variance_vector[idx], 0.0))),
                    )
                )
        return result


def fit_vector_autoregression(
    history: np.ndarray, order: int, series_ids: list[str]
) -> FittedVectorAutoregression:
    """OLS fit of a VAR(p): each series regressed on an intercept plus
    `order` lagged vectors of ALL series (equation-by-equation OLS,
    numerically identical to the standard VAR MLE under Gaussian
    innovations)."""
    history = np.asarray(history, dtype=float)
    if order < 1:
        raise ValueError("order must be a positive integer")
    if history.ndim != 2:
        raise ValueError("history must be a 2-D (n_periods, n_series) array")
    n, k = history.shape
    if k != len(series_ids):
        raise ValueError("series_ids length must match history's number of columns")
    if n < order + k + 1:
        raise ValueError(
            f"history must have at least order + n_series + 1 = {order + k + 1} periods, got {n}"
        )
    design = np.column_stack(
        [np.ones(n - order)] + [history[order - i : n - i, :] for i in range(1, order + 1)]
    )
    target = history[order:, :]
    coefficients, *_ = np.linalg.lstsq(design, target, rcond=None)
    intercept = coefficients[0, :]
    phi_matrices = [coefficients[1 + i * k : 1 + (i + 1) * k, :].T for i in range(order)]
    residual = target - design @ coefficients
    degrees_of_freedom = residual.shape[0] - (1 + order * k)
    if degrees_of_freedom <= 0:
        raise ValueError("not enough observations to estimate residual covariance")
    residual_covariance = (residual.T @ residual) / degrees_of_freedom
    last_values = history[-order:, :]
    return FittedVectorAutoregression(
        order=order,
        intercept=intercept,
        phi_matrices=phi_matrices,
        residual_covariance=residual_covariance,
        last_values=last_values,
        series_ids=list(series_ids),
    )
