"""Five asset-allocation rules over (equity, bond, real assets, cash).

Each rule sees only the asset returns up to the previous month and returns non-negative weights
that sum to one. With fewer than `MIN_HISTORY` months of history every rule falls back to equal
weights.
"""

from __future__ import annotations

from collections.abc import Callable

import numpy as np

MIN_HISTORY = 12
WINDOW = 36
TARGET_VOLATILITY = 0.10
SHRINKAGE = 0.30
RULES: tuple[str, ...] = (
    "equal_weight",
    "sixty_forty",
    "risk_parity",
    "min_variance",
    "vol_target",
)
EQUAL = np.full(4, 0.25)


def _normalise(weights: np.ndarray) -> np.ndarray:
    clipped = np.clip(weights, 0.0, None)
    total = float(clipped.sum())
    return EQUAL.copy() if total <= 0.0 else np.asarray(clipped / total, dtype=np.float64)


def equal_weight(history: np.ndarray) -> np.ndarray:
    return EQUAL.copy()


def sixty_forty(history: np.ndarray) -> np.ndarray:
    return np.array([0.6, 0.4, 0.0, 0.0])


def risk_parity(history: np.ndarray) -> np.ndarray:
    if history.shape[0] < MIN_HISTORY:
        return EQUAL.copy()
    vol = history[-WINDOW:, :3].std(axis=0, ddof=1)
    inverse = 1.0 / np.maximum(vol, 1e-6)
    return _normalise(np.append(inverse, 0.0))


def min_variance(history: np.ndarray) -> np.ndarray:
    """Long-only minimum variance over the three risky assets, covariance shrunk to its diagonal."""
    if history.shape[0] < MIN_HISTORY:
        return EQUAL.copy()
    sample = np.cov(history[-WINDOW:, :3], rowvar=False)
    shrunk = (1.0 - SHRINKAGE) * sample + SHRINKAGE * np.diag(np.diag(sample))
    solved = np.linalg.solve(shrunk + 1e-12 * np.eye(3), np.ones(3))
    return _normalise(np.append(solved, 0.0))


def vol_target(history: np.ndarray) -> np.ndarray:
    """A 60/40 portfolio scaled to a 10% volatility target, the rest in cash, no leverage."""
    if history.shape[0] < MIN_HISTORY:
        return EQUAL.copy()
    mix = 0.6 * history[-WINDOW:, 0] + 0.4 * history[-WINDOW:, 1]
    predicted = float(mix.std(ddof=1) * np.sqrt(12.0))
    share = 1.0 if predicted <= 0.0 else min(1.0, TARGET_VOLATILITY / predicted)
    return np.array([0.6 * share, 0.4 * share, 0.0, 1.0 - share])


RULE_FUNCTIONS: dict[str, Callable[[np.ndarray], np.ndarray]] = {
    "equal_weight": equal_weight,
    "sixty_forty": sixty_forty,
    "risk_parity": risk_parity,
    "min_variance": min_variance,
    "vol_target": vol_target,
}


def weights_for(rule: str, history: np.ndarray) -> np.ndarray:
    try:
        function = RULE_FUNCTIONS[rule]
    except KeyError as exc:
        raise ValueError(f"unknown rule {rule!r}; choose from {RULES}") from exc
    return function(history)
