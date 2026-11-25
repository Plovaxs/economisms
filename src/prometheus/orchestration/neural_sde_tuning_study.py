"""Can the neural SDE's training recipe be tuned, without reading any shock window? (PR-219)

E4 (H2) trains a neural SDE with learning rate 0.01, a 16-unit network, `patience` 20 and at most
300 epochs. The protocol forbade tuning `patience` because COVID's own window had decided it. This
study tunes the recipe on purpose, but ONLY on transitions decided before the earliest shock (the
2001 recession starts 2001-03-31), so no event window selects anything. Two questions, written down
BEFORE any number below was computed:

  N-A  On the CHECK months, does the selected recipe have a lower Gaussian log score (mean negative
       log-likelihood, lower is better) than the current recipe?
  N-B  On the same months, does the selected recipe have a lower log score than a constant-parameter
       GBM fitted on the same training part?

Decision rule: the paired difference of per-month scores, averaged over seeds, with a 6-month
moving-block bootstrap (95% interval) across months. SUPPORTED if the interval lies below zero,
CONTRADICTED if above, INCONCLUSIVE if it contains zero. Whatever comes out is reported.

Data. The transitions decided before 2001-03-31 are cut chronologically into FIT (the first 60%,
split 80/20 into training and early stopping as E4 does), SELECTION (the next 20%) and CHECK (the
last 20%). Recipes are ranked by the mean selection score over the selection seeds; the CHECK months
selected nothing, and the check uses fresh seeds. About forty months per part: this is a small
sample, the interval says so, and nothing here is a test of the shock question itself.

What was tuned: learning rate 0.003, 0.01 or 0.03; hidden size 16, 32 or 64; at most 300 or 1000
epochs; patience 20 or 50. Thirty-six recipes, the current one first.
"""

from __future__ import annotations

import argparse
import itertools
import json
import os
from collections.abc import Sequence
from concurrent.futures import ProcessPoolExecutor
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import numpy as np

from prometheus.confirmatory.e4_shocks import EVENTS, _examples
from prometheus.experiments.block_bootstrap import moving_block_bootstrap
from prometheus.neural_sde.benchmark import predict_candidate
from prometheus.neural_sde.dataset import TransitionExample, chronological_split, fit_scaler
from prometheus.neural_sde.scoring import gaussian_log_score
from prometheus.neural_sde.training import train_neural_sde
from prometheus.orchestration.neural_sde_run import DEFAULT_CSV_PATH

SELECTION_SEEDS = tuple(range(100, 110))
CHECK_SEEDS = tuple(range(200, 216))
RESERVED = range(20_000, 20_010)
LEARNING_RATES = (0.003, 0.01, 0.03)
HIDDEN_SIZES = (16, 32, 64)
MAX_EPOCHS = (300, 1000)
PATIENCES = (20, 50)
BLOCK_MONTHS = 6
FIT_SHARE = 0.6
SELECTION_SHARE = 0.2


@dataclass(frozen=True)
class Recipe:
    learning_rate: float
    hidden_size: int
    max_epochs: int
    patience: int

    @property
    def name(self) -> str:
        return f"lr{self.learning_rate:g}/h{self.hidden_size}/ep{self.max_epochs}/p{self.patience}"


DEFAULT = Recipe(0.01, 16, 300, 20)


def recipe_grid() -> list[Recipe]:
    """Thirty-six recipes, the current one first; ties go to the earlier one."""
    grid = [
        Recipe(*r) for r in itertools.product(LEARNING_RATES, HIDDEN_SIZES, MAX_EPOCHS, PATIENCES)
    ]
    grid.remove(DEFAULT)
    return [DEFAULT, *grid]


@dataclass(frozen=True)
class Parts:
    train: list[TransitionExample]
    early_stopping: list[TransitionExample]
    selection: list[TransitionExample]
    check: list[TransitionExample]


def split_before_the_first_shock(examples: list[TransitionExample]) -> Parts:
    """Fit / selection / check, all decided strictly before the earliest event's first month."""
    first_event = min(e.start for e in EVENTS)
    before = [e for e in examples if e.decision_time < first_event]
    n = len(before)
    n_fit = int(n * FIT_SHARE)
    n_selection = int(n * SELECTION_SHARE)
    fit = before[:n_fit]
    train, early = chronological_split(fit, train_fraction=0.8)
    return Parts(train, early, before[n_fit : n_fit + n_selection], before[n_fit + n_selection :])


def refuse_reserved(seeds: Sequence[int]) -> None:
    for seed in seeds:
        if seed in RESERVED:
            raise ValueError(f"seed {seed} is reserved for the frozen E4 run")


def monthly_scores(
    parts: Parts, recipe: Recipe, seed: int, target: list[TransitionExample]
) -> tuple[np.ndarray, np.ndarray]:
    """Per-transition log score of the neural SDE and of the constant GBM on `target`."""
    refuse_reserved([seed])
    state_scaler = fit_scaler(np.array([e.state for e in parts.train]))
    regime_scaler = fit_scaler(np.array([e.regime for e in parts.train]))
    trained = train_neural_sde(
        parts.train,
        parts.early_stopping,
        state_scaler,
        regime_scaler,
        seed=seed,
        max_epochs=recipe.max_epochs,
        patience=recipe.patience,
        learning_rate=recipe.learning_rate,
        hidden_size=recipe.hidden_size,
    )
    observed = np.array([e.next_state for e in target])
    neural_mu, neural_sigma = predict_candidate(
        "neural_sde",
        target,
        parts.train,
        neural_model=trained.model,
        state_scaler=trained.state_scaler,
        regime_scaler=trained.regime_scaler,
    )
    gbm_mu, gbm_sigma = predict_candidate("gbm_constant", target, parts.train)
    neural = np.array(
        [
            gaussian_log_score(neural_mu[i : i + 1], neural_sigma[i : i + 1], observed[i : i + 1])
            for i in range(len(target))
        ]
    )
    gbm = np.array(
        [
            gaussian_log_score(gbm_mu[i : i + 1], gbm_sigma[i : i + 1], observed[i : i + 1])
            for i in range(len(target))
        ]
    )
    return neural, gbm


_PARTS: Parts | None = None


def _parts(csv_path: Path) -> Parts:
    global _PARTS
    if _PARTS is None:
        _PARTS = split_before_the_first_shock(_examples(csv_path))
    return _PARTS


def _init_worker() -> None:
    import torch

    torch.set_num_threads(1)


def _job(job: tuple[str, int, Recipe, str]) -> tuple[str, int, Recipe, np.ndarray, np.ndarray]:
    part, seed, recipe, csv = job
    parts = _parts(Path(csv))
    target = parts.selection if part == "selection" else parts.check
    neural, gbm = monthly_scores(parts, recipe, seed, target)
    return part, seed, recipe, neural, gbm


def run_jobs(
    jobs: Sequence[tuple[str, int, Recipe, str]], workers: int
) -> dict[tuple[str, int, Recipe], tuple[np.ndarray, np.ndarray]]:
    if workers <= 1:
        out = list(map(_job, jobs))
    else:
        with ProcessPoolExecutor(max_workers=workers, initializer=_init_worker) as pool:
            out = list(pool.map(_job, jobs, chunksize=1))
    return {(p, s, r): (n, g) for p, s, r, n, g in out}


def select(means: dict[Recipe, float], grid: Sequence[Recipe]) -> Recipe:
    """The lowest mean selection log score; `min` keeps the first of equals (the current recipe)."""
    return min(grid, key=lambda r: means[r])


def verdict_below_zero(low: float, high: float) -> str:
    if high < 0.0:
        return "SUPPORTED"
    if low > 0.0:
        return "CONTRADICTED"
    return "INCONCLUSIVE"


def _paired(difference: np.ndarray, rng: np.random.Generator, resamples: int) -> dict[str, Any]:
    boot = moving_block_bootstrap(np.mean, difference, BLOCK_MONTHS, rng, n_resamples=resamples)
    return {
        "score_difference_first_minus_second": boot.point_estimate,
        "ci_low": boot.ci_low,
        "ci_high": boot.ci_high,
        "preregistered_verdict": verdict_below_zero(boot.ci_low, boot.ci_high),
    }


def run_study(
    csv_path: Path = DEFAULT_CSV_PATH,
    *,
    selection_seeds: Sequence[int] = SELECTION_SEEDS,
    check_seeds: Sequence[int] = CHECK_SEEDS,
    grid: Sequence[Recipe] | None = None,
    workers: int = 1,
    block_resamples: int = 2000,
) -> dict[str, Any]:
    grid = recipe_grid() if grid is None else list(grid)
    refuse_reserved([*selection_seeds, *check_seeds])
    if set(selection_seeds) & set(check_seeds):
        raise ValueError("selection and check seeds must be disjoint")
    csv = str(csv_path)
    parts = _parts(csv_path)

    selection = run_jobs([("selection", s, r, csv) for r in grid for s in selection_seeds], workers)
    means = {
        r: float(np.mean([selection[("selection", s, r)][0].mean() for s in selection_seeds]))
        for r in grid
    }
    chosen = select(means, grid)
    ranked = sorted(grid, key=lambda r: means[r])

    check = run_jobs(
        [("check", s, r, csv) for r in dict.fromkeys([DEFAULT, chosen]) for s in check_seeds],
        workers,
    )

    def averaged(recipe: Recipe, which: int) -> np.ndarray:
        return np.mean([check[("check", s, recipe)][which] for s in check_seeds], axis=0)

    neural_default, neural_chosen = averaged(DEFAULT, 0), averaged(chosen, 0)
    gbm = averaged(chosen, 1)
    rng = np.random.default_rng(0)
    return {
        "config": {
            "selected": asdict(chosen),
            "selected_name": chosen.name,
            "default": asdict(DEFAULT),
            "grid_size": len(grid),
            "selection_seeds": list(selection_seeds),
            "check_seeds": list(check_seeds),
            "n_train": len(parts.train),
            "n_early_stopping": len(parts.early_stopping),
            "n_selection": len(parts.selection),
            "n_check": len(parts.check),
            "last_decision_time_used": max(
                e.decision_time for p in (parts.selection, parts.check) for e in p
            ).isoformat(),
            "selection_rule": "lowest mean log score on the selection months; ties go to the "
            "earlier recipe, the current one first",
        },
        "selection_margin_over_runner_up": means[ranked[1]] - means[ranked[0]]
        if len(ranked) > 1
        else None,
        "grid": [{"recipe": r.name, "mean_selection_log_score": means[r]} for r in ranked],
        "check_log_score": {
            "default": float(neural_default.mean()),
            "selected": float(neural_chosen.mean()),
            "gbm_constant": float(gbm.mean()),
        },
        "comparisons": {
            "N-A_selected_vs_default": _paired(
                neural_chosen - neural_default, rng, block_resamples
            ),
            "N-B_selected_vs_constant_gbm": _paired(neural_chosen - gbm, rng, block_resamples),
        },
        "caveats": [
            "About forty months per part: the check interval is wide, and a recipe that is better "
            "here may not be better in a shock.",
            "Thirty-six recipes were compared on the selection months; the check months, which "
            "selected nothing, and fresh seeds carry the claim.",
            "No shock window was read by this study; the selected recipe is then run once on "
            "E4's exploratory seeds as an estimation-only report, never as a selection.",
            "Per-month scores are averaged over seeds before the bootstrap, so the interval is "
            "about the months, not about training noise.",
        ],
    }


def shock_report(
    seeds: Sequence[int] = tuple(range(10)), csv_path: Path = DEFAULT_CSV_PATH
) -> dict[str, Any]:
    """AFTER the recipe was chosen: absolute log scores of the current and the selected recipe, and
    of the constant GBM, in each event window (E4's exploratory seeds 0-9). Estimation only; the
    event windows were already read by earlier work, and nothing here selects a recipe."""
    from prometheus.confirmatory.e4_shocks import (
        FROZEN_RECIPE,
        LEGACY_RECIPE,
        split_for_event,
    )
    from prometheus.neural_sde.ood import evaluate_ood_without_retuning

    examples = _examples(csv_path)
    out: dict[str, Any] = {
        "label": "estimation only; post hoc; the recipe was chosen before any event window "
        "was scored",
        "seeds": list(seeds),
        "events": {},
    }
    for event in EVENTS:
        before, window = split_for_event(examples, event)
        train, validation = chronological_split(before, train_fraction=0.8)
        state_scaler = fit_scaler(np.array([e.state for e in train]))
        regime_scaler = fit_scaler(np.array([e.regime for e in train]))
        rows: dict[str, list[tuple[float, float, float, float]]] = {"legacy": [], "selected": []}
        for name, recipe in (("legacy", LEGACY_RECIPE), ("selected", FROZEN_RECIPE)):
            for seed in seeds:
                trained = train_neural_sde(
                    train,
                    validation,
                    state_scaler,
                    regime_scaler,
                    seed=seed,
                    max_epochs=recipe.max_epochs,
                    patience=recipe.patience,
                    learning_rate=recipe.learning_rate,
                    hidden_size=recipe.hidden_size,
                )
                r = evaluate_ood_without_retuning(trained, validation, window, train)
                rows[name].append(
                    (
                        r.neural_in_distribution_log_score,
                        r.neural_covid_log_score,
                        r.baseline_in_distribution_log_score,
                        r.baseline_covid_log_score,
                    )
                )
        event_entry: dict[str, Any] = {"n_event_transitions": len(window)}
        for name, values in rows.items():
            m = np.median(np.array(values), axis=0)
            event_entry[name] = {
                "neural_in_distribution_median": float(m[0]),
                "neural_event_median": float(m[1]),
                "gbm_in_distribution": float(m[2]),
                "gbm_event": float(m[3]),
                "seeds_where_neural_event_score_beats_gbm": int(sum(v[1] < v[3] for v in values)),
            }
        out["events"][event.name] = event_entry
    return out


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument("--workers", type=int, default=min(16, os.cpu_count() or 1))
    parser.add_argument("--output", type=Path)
    parser.add_argument(
        "--shock-report",
        action="store_true",
        help="after selection: absolute event-window scores of both recipes (estimation only)",
    )
    args = parser.parse_args(argv)
    if args.workers < 1:
        parser.error("--workers must be a positive integer")
    report = shock_report() if args.shock_report else run_study(workers=args.workers)
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2))
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
