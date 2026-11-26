"""A learned early-warning score: a ridge-penalised logistic regression on the monitor's indicators.

The hand-made composite in `monitor` averages four z-scores with equal weights. This fits the
weights (and adds the extension indicators when the world has them) on training worlds and is
scored on worlds it has never seen, with the same label: a crisis begins within `HORIZON` months,
measured only on months that are not already in a crisis.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from prometheus.worldsim import monitor
from prometheus.worldsim.config import CRISIS
from prometheus.worldsim.world import WorldPath

FEATURES: tuple[str, ...] = (
    "equity_volatility",
    "weakest_bank_capital",
    "output_gap",
    "credit_growth_12m",
    "composite",
    "firm_leverage",
    "public_debt",
    "sovereign_spread",
    "fx_change_6m",
)


def sample_matrix(path: WorldPath) -> tuple[np.ndarray, np.ndarray]:
    """(features, label) for each non-crisis month with a defined composite and a full horizon."""
    indicators = monitor.indicators(path)
    fx_change = np.zeros(path.n_months)
    fx_change[6:] = path.fx_level[6:] - path.fx_level[:-6]
    columns = np.column_stack(
        [
            indicators.volatility,
            indicators.min_capital_ratio,
            path.output_gap,
            indicators.credit_growth,
            indicators.composite,
            path.firm_leverage,
            path.debt_ratio,
            path.sovereign_spread,
            fx_change,
        ]
    )
    rows: list[np.ndarray] = []
    labels: list[bool] = []
    for t in range(monitor.BURN_IN, path.n_months - monitor.HORIZON):
        if path.regime[t] == CRISIS or np.isnan(indicators.composite[t]):
            continue
        rows.append(columns[t])
        labels.append(bool(np.any(path.regime[t + 1 : t + 1 + monitor.HORIZON] == CRISIS)))
    if not rows:
        return np.empty((0, len(FEATURES))), np.empty(0, dtype=bool)
    return np.vstack(rows), np.array(labels, dtype=bool)


def _sigmoid(z: np.ndarray) -> np.ndarray:
    return np.asarray(1.0 / (1.0 + np.exp(-np.clip(z, -30.0, 30.0))), dtype=np.float64)


@dataclass(frozen=True, slots=True)
class LogisticWarning:
    mean: np.ndarray
    scale: np.ndarray
    weights: np.ndarray
    bias: float

    def score(self, features: np.ndarray) -> np.ndarray:
        z = (features - self.mean) / self.scale
        return _sigmoid(z @ self.weights + self.bias)


def fit_logistic(
    features: np.ndarray, labels: np.ndarray, *, l2: float = 1.0, iterations: int = 30
) -> LogisticWarning:
    """Newton / IRLS for the L2-penalised logistic regression (the bias is not penalised)."""
    if features.shape[0] != labels.size or features.shape[0] < 10:
        raise ValueError("need matching features and labels, at least 10 samples")
    if labels.all() or not labels.any():
        raise ValueError("both classes must be present")
    mean = features.mean(axis=0)
    scale = np.where(features.std(axis=0) > 1e-12, features.std(axis=0), 1.0)
    z = (features - mean) / scale
    design = np.column_stack([z, np.ones(z.shape[0])])
    target = labels.astype(np.float64)
    beta = np.zeros(design.shape[1])
    penalty = l2 * np.eye(design.shape[1])
    penalty[-1, -1] = 0.0
    for _ in range(iterations):
        p = _sigmoid(design @ beta)
        gradient = design.T @ (p - target) + penalty @ beta
        hessian = (
            design.T @ (design * (p * (1.0 - p))[:, None]) + penalty + 1e-9 * np.eye(beta.size)
        )
        step = np.linalg.solve(hessian, gradient)
        beta = beta - step
        if float(np.max(np.abs(step))) < 1e-8:
            break
    return LogisticWarning(mean=mean, scale=scale, weights=beta[:-1], bias=float(beta[-1]))
