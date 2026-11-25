"""Can the deep-hedging policy's training recipe be tuned past the current default? (PR-218)

Finding 8 and the exploratory E1 numbers say the REINFORCE policy does not beat the static delta /
no-trade-band baseline: held-out CVaR ratios of 1.00-1.20 on eight old seeds, none below 1. The
recipe that produced them (learning rate 0.01, 400 epochs, a 16-unit network, initial exploration
`log std = 0`) was never tuned. This study tunes it on purpose, BEFORE the confirmatory freeze, and
asks two questions written down BEFORE any number below was computed:

  H-A  On fresh validation seeds, does the selected recipe have a higher held-out
       `theta = -mean(log(CVaR95 policy / CVaR95 static))` than the current default recipe,
       paired by seed?
  H-B  On the same seeds, is the selected recipe's `theta` above zero, i.e. does it beat the
       static baseline?

Decision rule: a 95% t interval over the seeds (the endpoint's own interval, `t_interval`) of the
paired difference (H-A) or of `theta` (H-B). SUPPORTED if the interval lies above zero,
CONTRADICTED if below, INCONCLUSIVE if it contains zero. Whatever comes out is reported.

What was tuned, and what was not. Every combination of

  * ``learning_rate``     0.003, 0.01 or 0.03;
  * ``n_epochs``          400, 1000 or 2000;
  * ``hidden_size``       16 or 64;
  * ``initial_log_std``   0.0 or -1.0 (how much the policy explores at the start);

is trained on each of the SELECTION seeds and ranked by the mean `theta` on 20,000 held-out paths
per seed. The reward objective stays "cvar", and the BASELINE is never touched: its band width, the
Black-Scholes delta and the cost model are the protocol's. Tuning the baseline would be tuning the
opponent.

Seeds. Selection seeds 1000-1007; validation seeds 3000-3015; both are used by no earlier run, and
neither overlaps the seeds reserved for the confirmatory protocol (10000-10049 for E1, 20000-20009
for E4), which this module refuses to touch. Thirty-six recipes compared on eight seeds means the
winner is partly luck; the margin over the runner-up is reported, and the validation seeds, which
selected nothing, are the only claim.

Round 2 (PR-218, decided after round 1 was read). Round 1's winner sat on the grid's corner (the
smallest learning rate and the longest budget), so its optimum may lie outside the grid. Round 2
extends the grid in that direction ONLY: learning rate 0.001, 0.002 or 0.003 x 2000 or 4000 epochs x
hidden 16 or 64, initial log std 0, on the same selection seeds and 16 NEW validation seeds
(4000-4015). H-A and H-B are asked again of round 2's winner, and one more:

  H-C  Is round 2's winner better than round 1's winner on the new validation seeds?

Round 1's result is not hidden by this: it is committed as it came out.
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

from prometheus.confirmatory.e1_hedging import (
    N_EVAL_PATHS,
    evaluation_paths,
    policy_hedge_loss,
    static_hedge_loss,
    tail_cvar,
)
from prometheus.confirmatory.intervals import t_interval
from prometheus.hedging.baseline import apply_no_trade_band, black_scholes_delta_hedge_ratios
from prometheus.hedging.rl_agent import train_reinforce_hedge_policy
from prometheus.hedging.simulate import simulate_self_financing_hedge
from prometheus.orchestration.rl_hedge_run import RlHedgeRunConfig
from prometheus.stochastica.gbm import simulate_gbm_paths

SELECTION_SEEDS = tuple(range(1000, 1008))
VALIDATION_SEEDS = tuple(range(3000, 3016))
RESERVED = (range(10000, 10050), range(20000, 20010))
LEARNING_RATES = (0.003, 0.01, 0.03)
EPOCHS = (400, 1000, 2000)
HIDDEN_SIZES = (16, 64)
INITIAL_LOG_STDS = (0.0, -1.0)
CONFIDENCE = 0.95


@dataclass(frozen=True)
class Recipe:
    learning_rate: float
    n_epochs: int
    hidden_size: int
    initial_log_std: float

    @property
    def name(self) -> str:
        return (
            f"lr{self.learning_rate:g}/ep{self.n_epochs}/h{self.hidden_size}"
            f"/std{self.initial_log_std:g}"
        )


DEFAULT = Recipe(0.01, 400, 16, 0.0)


ROUND1_WINNER = Recipe(0.003, 2000, 16, 0.0)
ROUND2_VALIDATION_SEEDS = tuple(range(4000, 4016))


def round2_grid() -> list[Recipe]:
    """Twelve recipes extending round 1 toward smaller steps and longer training."""
    return [
        Recipe(lr, ep, h, 0.0)
        for lr, ep, h in itertools.product((0.003, 0.002, 0.001), (2000, 4000), HIDDEN_SIZES)
    ]


def recipe_grid() -> list[Recipe]:
    """Thirty-six recipes, the current default first; ties go to the earlier one."""
    grid = [
        Recipe(lr, ep, h, s)
        for lr, ep, h, s in itertools.product(
            LEARNING_RATES, EPOCHS, HIDDEN_SIZES, INITIAL_LOG_STDS
        )
    ]
    grid.remove(DEFAULT)
    return [DEFAULT, *grid]


def refuse_reserved(seeds: Sequence[int]) -> None:
    for seed in seeds:
        if any(seed in block for block in RESERVED):
            raise ValueError(f"seed {seed} is reserved for the confirmatory protocol")


def evaluate_recipe(
    seed: int, recipe: Recipe, *, n_paths: int | None = None, n_eval_paths: int = N_EVAL_PATHS
) -> float:
    """`theta = -log(CVaR policy / CVaR static)` on held-out paths, for one seed and one recipe.

    The training paths, the static baseline and the held-out evaluation are exactly E1's
    (`confirmatory.e1_hedging`); only the policy's recipe differs."""
    refuse_reserved([seed])
    config = RlHedgeRunConfig(
        seed=seed, n_epochs=recipe.n_epochs, learning_rate=recipe.learning_rate
    )
    if n_paths is not None:
        config = RlHedgeRunConfig(
            seed=seed,
            n_epochs=recipe.n_epochs,
            learning_rate=recipe.learning_rate,
            n_paths=n_paths,
        )
    rng = np.random.default_rng(seed)
    paths = simulate_gbm_paths(
        s0=config.s0,
        mu=config.mu,
        sigma=config.sigma,
        maturity=config.maturity,
        n_steps=config.n_steps,
        n_paths=config.n_paths,
        rng=rng,
    )
    dt = config.maturity / config.n_steps
    delta = black_scholes_delta_hedge_ratios(
        paths,
        dt,
        config.strike,
        config.maturity,
        config.risk_free_rate,
        config.sigma,
        config.option_type,
    )
    static_sim = simulate_self_financing_hedge(
        paths,
        dt,
        config.strike,
        config.option_type,
        config.risk_free_rate,
        config.cost_rate,
        config.initial_premium,
        apply_no_trade_band(delta, band_width=config.band_width),
    )
    baseline = tail_cvar(static_sim.terminal_loss, config.cvar_alpha)
    trained = train_reinforce_hedge_policy(
        paths,
        dt,
        config.strike,
        config.option_type,
        config.risk_free_rate,
        config.cost_rate,
        config.initial_premium,
        static_baseline_cvar=baseline,
        seed=seed,
        n_epochs=recipe.n_epochs,
        cvar_alpha=config.cvar_alpha,
        learning_rate=recipe.learning_rate,
        reward_objective=config.reward_objective,
        hidden_size=recipe.hidden_size,
        initial_log_std=recipe.initial_log_std,
    )
    held_out = evaluation_paths(config, n_eval_paths)
    static = tail_cvar(static_hedge_loss(config, held_out), config.cvar_alpha)
    policy = tail_cvar(policy_hedge_loss(config, trained.policy, held_out), config.cvar_alpha)
    return float(-np.log(policy / static))


def _worker(job: tuple[int, Recipe, int]) -> tuple[int, Recipe, float]:
    seed, recipe, n_eval_paths = job
    return seed, recipe, evaluate_recipe(seed, recipe, n_eval_paths=n_eval_paths)


def _init_worker() -> None:
    import torch

    torch.set_num_threads(1)


def run_jobs(
    jobs: Sequence[tuple[int, Recipe, int]], workers: int
) -> dict[tuple[int, Recipe], float]:
    if workers <= 1:
        return {(s, r): t for s, r, t in map(_worker, jobs)}
    with ProcessPoolExecutor(max_workers=workers, initializer=_init_worker) as pool:
        return {(s, r): t for s, r, t in pool.map(_worker, jobs, chunksize=1)}


def select(means: dict[Recipe, float], grid: Sequence[Recipe]) -> Recipe:
    """The highest mean selection theta; `max` keeps the first of equals, i.e. the default."""
    return max(grid, key=lambda r: means[r])


def verdict_above_zero(low: float, high: float) -> str:
    if low > 0.0:
        return "SUPPORTED"
    if high < 0.0:
        return "CONTRADICTED"
    return "INCONCLUSIVE"


def run_study(
    *,
    selection_seeds: Sequence[int] = SELECTION_SEEDS,
    validation_seeds: Sequence[int] = VALIDATION_SEEDS,
    grid: Sequence[Recipe] | None = None,
    workers: int = 1,
    n_eval_paths: int = N_EVAL_PATHS,
    prior_winner: Recipe | None = None,
) -> dict[str, Any]:
    grid = recipe_grid() if grid is None else list(grid)
    refuse_reserved([*selection_seeds, *validation_seeds])
    if set(selection_seeds) & set(validation_seeds):
        raise ValueError("selection and validation seeds must be disjoint")

    grid_results = run_jobs([(s, r, n_eval_paths) for r in grid for s in selection_seeds], workers)
    means = {r: float(np.mean([grid_results[(s, r)] for s in selection_seeds])) for r in grid}
    chosen = select(means, grid)
    ranked = sorted(grid, key=lambda r: means[r], reverse=True)

    # The selected recipe was trained on the selection seeds; the validation seeds are new for both
    # recipes, so neither is advantaged.
    compared = [DEFAULT, chosen] + ([prior_winner] if prior_winner is not None else [])
    validation = run_jobs(
        [(s, r, n_eval_paths) for r in dict.fromkeys(compared) for s in validation_seeds], workers
    )
    theta_default = np.array([validation[(s, DEFAULT)] for s in validation_seeds])
    theta_chosen = np.array([validation[(s, chosen)] for s in validation_seeds])
    difference = t_interval(theta_chosen - theta_default, CONFIDENCE)
    absolute = t_interval(theta_chosen, CONFIDENCE)
    baseline_interval = t_interval(theta_default, CONFIDENCE)
    hypotheses: dict[str, Any] = {
        "H-A_selected_beats_default": {
            "verdict": verdict_above_zero(difference.low, difference.high),
            "difference_mean": float(np.mean(theta_chosen - theta_default)),
        },
        "H-B_selected_beats_static_baseline": {
            "verdict": verdict_above_zero(absolute.low, absolute.high),
            "theta_mean": float(np.mean(theta_chosen)),
        },
    }
    extra: dict[str, Any] = {}
    if prior_winner is not None:
        theta_prior = np.array([validation[(s, prior_winner)] for s in validation_seeds])
        versus_prior = t_interval(theta_chosen - theta_prior, CONFIDENCE)
        hypotheses["H-C_selected_beats_round1_winner"] = {
            "verdict": verdict_above_zero(versus_prior.low, versus_prior.high),
            "difference_mean": float(np.mean(theta_chosen - theta_prior)),
        }
        extra = {
            "round1_winner": prior_winner.name,
            "theta_round1_winner": theta_prior.tolist(),
            "round1_winner_theta_interval": t_interval(theta_prior, CONFIDENCE).as_dict(),
            "difference_vs_round1_winner_interval": versus_prior.as_dict(),
        }
    return {
        "config": {
            "selected": asdict(chosen),
            "selected_name": chosen.name,
            "default": asdict(DEFAULT),
            "grid_size": len(grid),
            "selection_seeds": list(selection_seeds),
            "validation_seeds": list(validation_seeds),
            "n_eval_paths": n_eval_paths,
            "selection_rule": "highest mean held-out theta on the selection seeds; ties go to "
            "the earlier recipe, the default first",
        },
        "selection_margin_over_runner_up": means[ranked[0]] - means[ranked[1]]
        if len(ranked) > 1
        else None,
        "grid": [
            {
                "recipe": r.name,
                "mean_theta": means[r],
                "per_seed_theta": [grid_results[(s, r)] for s in selection_seeds],
            }
            for r in ranked
        ],
        "validation": {
            "theta_default": theta_default.tolist(),
            "theta_selected": theta_chosen.tolist(),
            "default_theta_interval": baseline_interval.as_dict(),
            "selected_theta_interval": absolute.as_dict(),
            "paired_difference_interval": difference.as_dict(),
            **extra,
        },
        "hypotheses": hypotheses,
        "caveats": [
            "Thirty-six recipes were compared on eight selection seeds; the winner is partly luck, "
            "which is why the claim rests on sixteen separate validation seeds.",
            "One option (a European call), one geometric Brownian motion, one cost rate: a "
            "statement about this simulator, not about hedging in general.",
            "Training ran single-threaded in worker processes; the confirmatory runner uses the "
            "default thread count, so the last digits can differ between the two.",
            "The recipe changes the confirmatory protocol's recipe hash if it is adopted; the "
            "freeze record is still empty.",
        ],
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument("--workers", type=int, default=min(16, os.cpu_count() or 1))
    parser.add_argument("--round", type=int, choices=(1, 2), default=1)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    if args.workers < 1:
        parser.error("--workers must be a positive integer")
    if args.round == 1:
        report = run_study(workers=args.workers)
    else:
        report = run_study(
            validation_seeds=ROUND2_VALIDATION_SEEDS,
            grid=round2_grid(),
            workers=args.workers,
            prior_winner=ROUND1_WINNER,
        )
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2))
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
