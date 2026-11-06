"""Paired nested resampling of retraining-specific macro-mixture CVaRs.

Loss cubes are (training replicate, macro bank, conditional market path).
Every macro bank has equal mass and the same number of market paths.
CVaR pools macro/market outcomes WITHIN each trained policy; policy-specific
CVaR differences are then averaged. It never pools different trained policies
into a synthetic ensemble. Percentile coverage is exploratory, not exact.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from prometheus.experiments.bootstrap import BootstrapResult


def _row_cvars(losses: np.ndarray, alpha: float) -> np.ndarray:
    values = np.sort(losses.reshape(losses.shape[0], -1), axis=1)
    n = values.shape[1]
    k = min(math.ceil(alpha * n), n)
    with np.errstate(over="ignore", invalid="ignore", divide="ignore"):
        result: np.ndarray = (values[:, k:].sum(axis=1) + (k - alpha * n) * values[:, k - 1]) / (
            n * (1 - alpha)
        )
    if not np.all(np.isfinite(result)):
        raise ValueError("non-finite empirical macro-mixture CVaR")
    return result


def _validate(a: np.ndarray, b: np.ndarray, alpha: float) -> tuple[np.ndarray, np.ndarray]:
    a, b = np.asarray(a, dtype=float), np.asarray(b, dtype=float)
    if a.shape != b.shape or a.ndim != 3 or min(a.shape[:2]) < 2 or a.shape[2] < 1:
        raise ValueError("paired loss cubes require shape (>=2 retrainings, >=2 banks, >=1 paths)")
    if not np.all(np.isfinite(a)) or not np.all(np.isfinite(b)):
        raise ValueError("loss cubes must be finite")
    if not math.isfinite(alpha) or not 0 < alpha < 1:
        raise ValueError("cvar_alpha must lie in (0,1)")
    return a, b


@dataclass(frozen=True, slots=True)
class MixtureCvarPoint:
    comparator_cvars: tuple[float, ...]
    policy_cvars: tuple[float, ...]
    per_training_differences: tuple[float, ...]
    mean_difference: float
    mean_cell_cvar_difference: float


def mixture_cvar_point(
    comparator_losses: np.ndarray,
    policy_losses: np.ndarray,
    *,
    cvar_alpha: float,
) -> MixtureCvarPoint:
    a, b = _validate(comparator_losses, policy_losses, cvar_alpha)
    ac, bc = _row_cvars(a, cvar_alpha), _row_cvars(b, cvar_alpha)
    # Cell CVaRs are auxiliary diagnostics; their mean is a different estimand.
    cell_a = _row_cvars(a.reshape(-1, 1, a.shape[2]), cvar_alpha)
    cell_b = _row_cvars(b.reshape(-1, 1, b.shape[2]), cvar_alpha)
    with np.errstate(over="ignore", invalid="ignore"):
        differences = ac - bc
        mean_difference = float(differences.mean())
        cell_difference = float((cell_a - cell_b).mean())
    if not np.all(np.isfinite(differences)) or not all(
        math.isfinite(value) for value in (mean_difference, cell_difference)
    ):
        raise ValueError("non-finite CVaR differences")
    return MixtureCvarPoint(
        tuple(map(float, ac)),
        tuple(map(float, bc)),
        tuple(map(float, differences)),
        mean_difference,
        cell_difference,
    )


@dataclass(frozen=True, slots=True)
class NestedMixtureBootstrapResult:
    point: MixtureCvarPoint
    nested: BootstrapResult
    training_only: BootstrapResult
    macro_only: BootstrapResult
    market_only: BootstrapResult
    n_training_seeds: int
    n_macro_banks: int
    n_market_paths_per_bank: int


def nested_mixture_cvar_bootstrap(
    comparator_losses: np.ndarray,
    policy_losses: np.ndarray,
    rng: np.random.Generator,
    *,
    cvar_alpha: float,
    n_resamples: int = 1_000,
    confidence: float = 0.95,
) -> NestedMixtureBootstrapResult:
    """Resample training rows, macro columns and market indices within each drawn bank.

    The same row/bank/path selections apply to BOTH policies. All training
    rows share the same drawn macro banks and within-bank market samples.
    Repeated occurrences of a drawn macro bank get fresh inner resamples.
    Single-axis intervals condition on other sampled axes and are not
    additive variance components. The scheme has no calibrated finite-seed
    coverage guarantee, especially with few macro/training levels.
    """
    a, b = _validate(comparator_losses, policy_losses, cvar_alpha)
    if type(n_resamples) is not int or n_resamples < 1:
        raise ValueError("n_resamples must be a positive integer")
    if not math.isfinite(confidence) or not 0 < confidence < 1:
        raise ValueError("confidence must lie in (0,1)")
    point = mixture_cvar_point(a, b, cvar_alpha=cvar_alpha)
    n_rows, n_banks, n_paths = a.shape
    original = np.array(point.per_training_differences)
    nested, training, macro, market = (np.empty(n_resamples) for _ in range(4))
    for index in range(n_resamples):
        rows = np.asarray(rng.integers(0, n_rows, size=n_rows))
        banks = np.asarray(rng.integers(0, n_banks, size=n_banks))
        paths = np.asarray(rng.integers(0, n_paths, size=(n_banks, n_paths)))
        drawn_a = a[:, banks[:, None], paths]
        drawn_b = b[:, banks[:, None], paths]
        row_differences = _row_cvars(drawn_a, cvar_alpha) - _row_cvars(drawn_b, cvar_alpha)
        nested[index] = row_differences[rows].mean()
        training[index] = original[rows].mean()
        macro[index] = (
            _row_cvars(a[:, banks, :], cvar_alpha) - _row_cvars(b[:, banks, :], cvar_alpha)
        ).mean()
        market[index] = (
            _row_cvars(a[:, np.arange(n_banks)[:, None], paths], cvar_alpha)
            - _row_cvars(b[:, np.arange(n_banks)[:, None], paths], cvar_alpha)
        ).mean()

    def interval(draws: np.ndarray) -> BootstrapResult:
        if not np.all(np.isfinite(draws)):
            raise ValueError("non-finite resampled CVaR differences")
        tail = (1 - confidence) / 2
        lo, hi = np.quantile(draws, [tail, 1 - tail])
        return BootstrapResult(point.mean_difference, float(lo), float(hi), confidence, n_resamples)

    return NestedMixtureBootstrapResult(
        point,
        interval(nested),
        interval(training),
        interval(macro),
        interval(market),
        n_rows,
        n_banks,
        n_paths,
    )
