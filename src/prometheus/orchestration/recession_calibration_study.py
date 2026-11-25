"""Can the recession classifier's probabilities be repaired by out-of-fold recalibration? (PR-217)

Finding 14 left one sharp fact about the classifier that ranks recessions well: on the long macro
history the logistic regression has a ROC-AUC of 0.86 but a Brier score of 0.095, worse than the
constant base rate's 0.079. It orders months correctly and states its probabilities too
confidently. That is a calibration problem, and it has a standard repair that does not need more
data: fit a two-parameter map on the model's own logit, `p = sigmoid(a * logit + b)`, to
out-of-sample predictions. Two questions, written down BEFORE any number below was computed:

  R-A  Does the recalibrated logistic regression have a LOWER test Brier score than the same
       model uncalibrated?
  R-B  Does it have a LOWER test Brier score than the constant base rate?

Decision rule: the paired difference of per-month squared errors (seed-averaged, 6-month
moving-block bootstrap, 95% interval) is SUPPORTED if the interval lies below zero, CONTRADICTED if
above, INCONCLUSIVE if it contains zero. Whatever comes out is reported.

How the map is fitted without touching the validation or test months. The model is first trained
as in Finding 14 (early-stopped on the validation split, which fixes its number of epochs). Then,
WITHIN the training months only, it is retrained on an expanding window and used to predict the next
block of `BLOCK_YEARS` years, never seeing a month whose label period overlaps the block (a
training row's target month must precede the block's first decision month). The stacked
out-of-fold logits and labels fit `a` and `b` by minimising the Brier score, with `a >= 0` so
the map can shrink or stretch the model's ordering but never reverse it. The test months are used
once, to score.

Power. The test window has 175 months, 14 of them positive, from two recession episodes. A
Brier difference here is a statement about those two episodes. The study reports it anyway,
with the interval, and says so.
"""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

import numpy as np
import torch
from scipy import optimize

from prometheus.experiments.block_bootstrap import moving_block_bootstrap
from prometheus.orchestration.recessionnet_extended_study import (
    HORIZON,
    TEST_SPLIT,
    VALIDATION_SPLIT,
    WINDOW,
    FeatureSet,
    build_feature_sets,
)
from prometheus.quantum.models import LogisticRegressionClassifier
from prometheus.recessionnet.dataset import (
    RecessionDataset,
    build_recession_dataset,
    chronological_split,
)
from prometheus.recessionnet.evaluation import roc_auc
from prometheus.recessionnet.labels import NBER_RECESSIONS
from prometheus.recessionnet.training import (
    train_classifier,
    train_classifier_with_early_stopping,
)

FEATURE_SET = "macro_5_long"
FIRST_BLOCK_START = date(1985, 1, 1)
BLOCK_YEARS = 3
MIN_TRAIN_POSITIVES = 3
BLOCK_MONTHS = HORIZON


@dataclass(frozen=True)
class PlattMap:
    """`p = sigmoid(a * logit + b)`."""

    a: float
    b: float

    def apply(self, logits: np.ndarray) -> np.ndarray:
        return np.asarray(1.0 / (1.0 + np.exp(-(self.a * logits + self.b))), dtype=np.float64)


def fit_platt(logits: np.ndarray, labels: np.ndarray) -> PlattMap:
    """The Brier-minimising `(a, b)` with `a >= 0`. Needs both classes present."""
    if logits.shape != labels.shape or logits.ndim != 1:
        raise ValueError("logits and labels must be 1-D and the same length")
    if labels.min() == labels.max():
        raise ValueError("recalibration needs both classes among the out-of-fold labels")

    def brier(theta: np.ndarray) -> float:
        p = 1.0 / (1.0 + np.exp(-(theta[0] * logits + theta[1])))
        return float(np.mean((p - labels) ** 2))

    best = min(
        (
            optimize.minimize(brier, x0, method="L-BFGS-B", bounds=[(0.0, 5.0), (-12.0, 12.0)])
            for x0 in (np.array([1.0, 0.0]), np.array([0.2, -2.0]), np.array([0.05, -2.5]))
        ),
        key=lambda r: float(r.fun),
    )
    return PlattMap(float(best.x[0]), float(best.x[1]))


def block_starts(decision_months: Sequence[date], first: date, years: int) -> list[date]:
    """Calendar starts of the expanding-window blocks, from `first` to the last decision month."""
    starts = []
    year = first.year
    while date(year, 1, 1) <= decision_months[-1]:
        starts.append(date(year, 1, 1))
        year += years
    return starts


def out_of_fold_logits(
    train: RecessionDataset, *, epochs: int, seed: int
) -> tuple[np.ndarray, np.ndarray]:
    """Logits and labels of the training months, each predicted by a model that had not seen its
    block and whose training labels all describe months BEFORE the block began."""
    starts = block_starts(train.decision_months, FIRST_BLOCK_START, BLOCK_YEARS)
    logits: list[np.ndarray] = []
    labels: list[np.ndarray] = []
    for k, start in enumerate(starts):
        end = starts[k + 1] if k + 1 < len(starts) else date(9999, 1, 1)
        in_block = np.array([start <= d < end for d in train.decision_months])
        usable = np.array([t < start for t in train.target_months])
        if not in_block.any() or usable.sum() == 0:
            continue
        if train.labels[usable].sum() < MIN_TRAIN_POSITIVES:
            continue
        trained = train_classifier(
            lambda: LogisticRegressionClassifier(train.features.shape[1]),
            train.features[usable],
            train.labels[usable],
            seed=seed,
            n_epochs=epochs,
        )
        trained.model.eval()
        with torch.no_grad():
            z = trained.model(torch.tensor(train.features[in_block], dtype=torch.float32))
        logits.append(z.numpy().astype(np.float64))
        labels.append(train.labels[in_block])
    if not logits:
        raise ValueError("no out-of-fold block had enough positive training months")
    return np.concatenate(logits), np.concatenate(labels)


def _dataset(feature_set: FeatureSet) -> RecessionDataset:
    return build_recession_dataset(
        feature_set.observations,
        feature_set.series_ids,
        NBER_RECESSIONS,
        window=WINDOW,
        horizon=HORIZON,
    )


def run_seed(
    feature_set: FeatureSet, seed: int, *, max_epochs: int, patience: int
) -> dict[str, Any]:
    dataset = _dataset(feature_set)
    train_full, test = chronological_split(dataset, TEST_SPLIT)
    train_proper, validation = chronological_split(train_full, VALIDATION_SPLIT)
    stopped = train_classifier_with_early_stopping(
        lambda: LogisticRegressionClassifier(train_proper.features.shape[1]),
        train_proper.features,
        train_proper.labels,
        validation.features,
        validation.labels,
        seed=seed,
        max_epochs=max_epochs,
        patience=patience,
    )
    stopped.model.eval()
    with torch.no_grad():
        test_logits = (
            stopped.model(torch.tensor(test.features, dtype=torch.float32))
            .numpy()
            .astype(np.float64)
        )
    oof_z, oof_y = out_of_fold_logits(train_proper, epochs=stopped.selected_epoch + 1, seed=seed)
    platt = fit_platt(oof_z, oof_y)
    raw = 1.0 / (1.0 + np.exp(-test_logits))
    calibrated = platt.apply(test_logits)
    base_rate = float(np.clip(train_proper.labels.mean(), 1e-6, 1 - 1e-6))
    return {
        "labels": test.labels,
        "raw": raw,
        "calibrated": calibrated,
        "base_rate": np.full(len(test.labels), base_rate),
        "platt": (platt.a, platt.b),
        "selected_epoch": stopped.selected_epoch,
        "n_out_of_fold": int(len(oof_y)),
        "n_out_of_fold_positive": int(oof_y.sum()),
    }


def verdict(ci_low: float, ci_high: float) -> str:
    if ci_low > 0.0 and ci_high > 0.0:
        return "CONTRADICTED"
    if ci_low < 0.0 and ci_high < 0.0:
        return "SUPPORTED"
    return "INCONCLUSIVE"


def run_study(
    *,
    seeds: Sequence[int] = (0, 1, 2, 3, 4),
    max_epochs: int = 500,
    patience: int = 20,
    block_resamples: int = 2000,
    feature_sets: dict[str, FeatureSet] | None = None,
) -> dict[str, Any]:
    feature_set = (build_feature_sets() if feature_sets is None else feature_sets)[FEATURE_SET]
    runs = [run_seed(feature_set, s, max_epochs=max_epochs, patience=patience) for s in seeds]
    labels = runs[0]["labels"]
    mean = {k: np.mean([r[k] for r in runs], axis=0) for k in ("raw", "calibrated", "base_rate")}
    squared = {k: (v - labels) ** 2 for k, v in mean.items()}
    rng = np.random.default_rng(0)

    def paired(first: str, second: str) -> dict[str, Any]:
        boot = moving_block_bootstrap(
            np.mean,
            squared[first] - squared[second],
            BLOCK_MONTHS,
            rng,
            n_resamples=block_resamples,
        )
        return {
            "brier_difference_first_minus_second": boot.point_estimate,
            "ci_low": boot.ci_low,
            "ci_high": boot.ci_high,
            "preregistered_verdict": verdict(boot.ci_low, boot.ci_high),
        }

    return {
        "config": {
            "feature_set": FEATURE_SET,
            "seeds": list(seeds),
            "max_epochs": max_epochs,
            "patience": patience,
            "first_out_of_fold_block": FIRST_BLOCK_START.isoformat(),
            "block_years": BLOCK_YEARS,
            "n_test": int(len(labels)),
            "n_test_positive": int(labels.sum()),
        },
        "test_brier": {k: float(np.mean(v)) for k, v in squared.items()},
        "test_roc_auc": {
            k: roc_auc(mean[k], labels) for k in ("raw", "calibrated") if len(set(labels)) == 2
        },
        "per_seed": [
            {
                "platt_a": r["platt"][0],
                "platt_b": r["platt"][1],
                "selected_epoch": r["selected_epoch"],
                "n_out_of_fold": r["n_out_of_fold"],
                "n_out_of_fold_positive": r["n_out_of_fold_positive"],
                "brier_raw": float(np.mean((r["raw"] - labels) ** 2)),
                "brier_calibrated": float(np.mean((r["calibrated"] - labels) ** 2)),
            }
            for r in runs
        ],
        "comparisons": {
            "R-A_calibrated_vs_raw": paired("calibrated", "raw"),
            "R-B_calibrated_vs_base_rate": paired("calibrated", "base_rate"),
        },
        "caveats": [
            "175 test months, 14 positive, from two recession episodes: a Brier difference is a "
            "statement about those two episodes, and the test window was already seen in "
            "Finding 14.",
            "The calibration map is fitted on out-of-fold predictions inside the training "
            "months; its few positive months come from the 1969-1991 recessions.",
            "Publication lags are fixed assumptions and GDP / seasonally adjusted CPI are "
            "latest-revised values (Finding 13).",
        ],
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument("--seeds", type=int, default=5)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    if args.seeds < 1:
        parser.error("--seeds must be a positive integer")
    report = run_study(seeds=list(range(args.seeds)))
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2))
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
