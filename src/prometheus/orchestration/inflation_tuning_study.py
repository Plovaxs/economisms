"""Can the learned inflation nowcast be tuned past the base-effect rule? (PR-216)

Finding 18 found that a ridge regression on the last twelve monthly growth rates beat the best
base-effect rule by only about 6% and that the learned variants cannot be told apart on the
validation decade. This study tunes the learned model on purpose, on the validation decade only,
and asks two questions written down BEFORE any number below was computed:

  I-A  Does the selected tuned model have a LOWER test mean absolute YoY error than Finding 18's
       learned model (`ridge_own@1962`: 12 lags, squared error, fit 1962-1989)?
  I-B  Does it have a LOWER error than the base-effect rule `base_mean12`?

Decision rule: a paired mean-absolute-error difference (12-month moving-block bootstrap, 95%
interval) is SUPPORTED if the interval lies below zero, CONTRADICTED if above, INCONCLUSIVE if it
contains zero. Whatever comes out is reported.

What was tuned. Every combination of

  * ``lags``      6, 12 or 24 past monthly growth rates;
  * ``target``    ``raw`` (predict MoM) or ``residual`` (predict MoM minus its 12-month mean, so the
                  ridge penalty shrinks toward the base-effect rule instead of toward zero);
  * ``loss``      ``l2`` (squared error, as before) or ``l1`` (absolute error, by iteratively
                  reweighted ridge): the score is a MEAN ABSOLUTE error, and the squared-error fit
                  is dominated by the 1970s;
  * ``start``     fit window beginning 1962 or 1980;

and, for each, the ridge penalty (seven values) are ranked by the mean absolute YoY error on the
VALIDATION decade 1990-1999. Twenty-four configurations are compared on 120 months, so the winner
is partly luck: the validation margin over the runner-up is reported, and the test comparison is
the only claim. The test window (2000-01 .. 2023-01) was already seen in Finding 18; nothing here
is selected on it, but this is a model-selection study, not an untouched confirmation.

Every feature at target month t uses growth rates up to month t-1 only (a leak test checks it).
"""

from __future__ import annotations

import argparse
import itertools
import json
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path
from typing import Any

import numpy as np

from prometheus.experiments.block_bootstrap import moving_block_bootstrap
from prometheus.orchestration.inflationcast_long_study import (
    BLOCK_MONTHS,
    CPI_PATH,
    MACRO_PATH,
    RIDGE_PENALTIES,
    TRAIN_END,
    VALIDATION_END,
    NowcastData,
    Ridge,
    base_effect_forecast,
    build_nowcast_data,
    feature_matrix,
    fit_ridge,
    verdict,
    yoy_from_mom,
)

LAGS = (6, 12, 24)
TARGETS = ("raw", "residual")
LOSSES = ("l2", "l1")
STARTS = {"1962": date(1962, 1, 31), "1980": date(1980, 1, 31)}
L1_ITERATIONS = 30
L1_FLOOR = 1e-3


@dataclass(frozen=True)
class Config:
    lags: int
    target: str
    loss: str
    start: str

    @property
    def name(self) -> str:
        return f"lags{self.lags}/{self.target}/{self.loss}/{self.start}"


def config_grid() -> list[Config]:
    """Twenty-four configurations; ties go to the earlier one (fewer lags, raw, l2, 1962)."""
    return [Config(*c) for c in itertools.product(LAGS, TARGETS, LOSSES, STARTS)]


def lag_matrix(data: NowcastData, lags: int) -> np.ndarray:
    """Column k holds MoM_{t-lags+k}: the `lags` growth rates BEFORE target month t. Rows whose
    history starts before the series does are NaN."""
    history = np.asarray(data.mom_history, dtype=np.float64)  # column k = MoM_{t-12+k}
    if lags <= history.shape[1]:
        return history[:, -lags:].copy()
    out = np.full((len(data.months), lags), np.nan)
    out[:, lags - history.shape[1] :] = history
    for k in range(lags - history.shape[1]):
        shift = lags - k  # column k = MoM_{t-shift}, a row `shift` places earlier
        out[shift:, k] = data.mom[:-shift]
    return out


def fit_l1_ridge(x: np.ndarray, y: np.ndarray, penalty: float) -> Any:
    """Ridge with an absolute-error loss: iteratively reweighted least squares."""
    weights = np.ones(len(y))
    model = fit_ridge(x, y, penalty)
    for _ in range(L1_ITERATIONS):
        residual = np.abs(y - model.predict(x))
        weights = 1.0 / np.maximum(residual, L1_FLOOR)
        model = _fit_weighted(x, y, penalty, weights)
    return model


def _fit_weighted(x: np.ndarray, y: np.ndarray, penalty: float, weights: np.ndarray) -> Any:
    w = weights / weights.sum()
    mean = (w[:, None] * x).sum(axis=0)
    scale = x.std(axis=0) + 1e-12
    z = (x - mean) / scale
    intercept = float((w * y).sum())
    gram = z.T @ (weights[:, None] * z) + penalty * weights.mean() * np.eye(z.shape[1])
    coefficients = np.linalg.solve(gram, z.T @ (weights * (y - intercept)))
    return Ridge(mean, scale, coefficients, intercept)


def fit_configuration(
    data: NowcastData, config: Config, rows: np.ndarray, penalty: float
) -> tuple[Any, np.ndarray]:
    """Fit on `rows`; returns the model and the matrix of lags it was built from."""
    x = lag_matrix(data, config.lags)
    base = base_effect_forecast(data, "base_mean12")
    y = data.mom - base if config.target == "residual" else data.mom
    fitter = fit_l1_ridge if config.loss == "l1" else fit_ridge
    return fitter(x[rows], y[rows], penalty), x


def predict_mom(data: NowcastData, config: Config, model: Any, x: np.ndarray) -> np.ndarray:
    prediction = np.asarray(model.predict(x), dtype=np.float64)
    if config.target == "residual":
        prediction = prediction + base_effect_forecast(data, "base_mean12")
    return prediction


def mae_on(data: NowcastData, mom: np.ndarray, rows: np.ndarray) -> float:
    return float(np.mean(np.abs(yoy_from_mom(data, mom)[rows] - data.yoy[rows])))


@dataclass(frozen=True)
class Candidate:
    config: Config
    penalty: float
    validation_mae: float
    model: Any
    x: np.ndarray


def tune(
    data: NowcastData, config: Config, train_rows: np.ndarray, validation_rows: np.ndarray
) -> Candidate:
    x = lag_matrix(data, config.lags)
    start = data.mask(STARTS[config.start], None)
    ok = ~np.isnan(x).any(axis=1)
    fit_rows = train_rows & start & ok
    val_rows = validation_rows & ok
    best: Candidate | None = None
    for penalty in RIDGE_PENALTIES:
        model, _ = fit_configuration(data, config, fit_rows, penalty)
        mom = np.full(len(data.months), np.nan)
        mom[val_rows] = predict_mom(data, config, model, x)[val_rows]
        error = mae_on(data, mom, val_rows)
        if best is None or error < best.validation_mae:
            best = Candidate(config, penalty, error, model, x)
    if best is None:  # pragma: no cover - RIDGE_PENALTIES is non-empty
        raise RuntimeError("no penalty was tried")
    return best


def select(candidates: Sequence[Candidate]) -> Candidate:
    """The lowest validation MAE; `min` keeps the first of equals, i.e. the simplest."""
    return min(candidates, key=lambda c: c.validation_mae)


def _paired(
    first: np.ndarray, second: np.ndarray, rng: np.random.Generator, resamples: int
) -> dict[str, Any]:
    difference = np.abs(first) - np.abs(second)
    boot = moving_block_bootstrap(np.mean, difference, BLOCK_MONTHS, rng, n_resamples=resamples)
    return {
        "mae_difference_first_minus_second": boot.point_estimate,
        "ci_low": boot.ci_low,
        "ci_high": boot.ci_high,
        "preregistered_verdict": verdict(boot.ci_low, boot.ci_high),
    }


def run_study(
    cpi_path: Path = CPI_PATH,
    macro_path: Path = MACRO_PATH,
    *,
    block_resamples: int = 2000,
    grid: Sequence[Config] | None = None,
) -> dict[str, Any]:
    data = build_nowcast_data(cpi_path, macro_path)
    grid = config_grid() if grid is None else list(grid)
    train_rows = data.mask(None, TRAIN_END)
    validation_rows = data.mask(TRAIN_END, VALIDATION_END) & ~train_rows
    complete = ~np.isnan(feature_matrix(data, "all")).any(axis=1)
    test_rows = ~(train_rows | validation_rows) & complete

    candidates = [tune(data, c, train_rows, validation_rows) for c in grid]
    chosen = select(candidates)
    reference = tune(data, Config(12, "raw", "l2", "1962"), train_rows, validation_rows)

    def test_forecast(candidate: Candidate) -> np.ndarray:
        mom = np.full(len(data.months), np.nan)
        mom[test_rows] = predict_mom(data, candidate.config, candidate.model, candidate.x)[
            test_rows
        ]
        return yoy_from_mom(data, mom)

    forecasts = {
        "persistence_yoy": data.previous_yoy,
        "base_mean12": yoy_from_mom(data, base_effect_forecast(data, "base_mean12")),
        "finding18_ridge_own@1962": test_forecast(reference),
        "tuned": test_forecast(chosen),
    }
    errors = {name: (f - data.yoy)[test_rows] for name, f in forecasts.items()}
    rng = np.random.default_rng(0)
    comparisons = {
        "I-A_tuned_vs_finding18_ridge": _paired(
            errors["tuned"], errors["finding18_ridge_own@1962"], rng, block_resamples
        ),
        "I-B_tuned_vs_base_mean12": _paired(
            errors["tuned"], errors["base_mean12"], rng, block_resamples
        ),
    }
    ranked = sorted(candidates, key=lambda c: c.validation_mae)
    return {
        "config": {
            "selected": asdict(chosen.config),
            "selected_penalty": chosen.penalty,
            "grid_size": len(grid),
            "n_test_months": int(test_rows.sum()),
            "selection_rule": "lowest mean absolute YoY error on 1990-1999; ties go to the "
            "earlier (simpler) configuration",
        },
        "validation_margin_over_runner_up": ranked[1].validation_mae - ranked[0].validation_mae
        if len(ranked) > 1
        else None,
        "grid": [
            {"config": c.config.name, "penalty": c.penalty, "validation_mae": c.validation_mae}
            for c in ranked
        ],
        "test_mae": {name: float(np.mean(np.abs(e))) for name, e in errors.items()},
        "comparisons": comparisons,
        "caveats": [
            "The test window was already seen in Finding 18: nothing here is selected on it, but "
            "this is a model-selection study, not an untouched confirmation.",
            "Twenty-four configurations were compared on 120 validation months; the winner's "
            "margin over the runner-up is reported so a near-tie is visible.",
            "One country and one price index; 277 serially dependent errors (12-month blocks).",
            "CPI levels are today's seasonally adjusted series, not the real-time vintage.",
        ],
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    report = run_study()
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2))
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
