"""E1: does the REINFORCE hedging policy beat the static delta / no-trade-band baseline? (H5)

The frozen pipeline is `orchestration.rl_hedge_run.run_rl_hedge` with the TUNED recipe below
(`FROZEN_LEARNING_RATE`, `FROZEN_N_EPOCHS`) and every other field at its default: one training run
per seed on that seed's 2,000 simulated GBM paths. The recipe was chosen on exploratory seeds
(`orchestration.hedging_tuning_study`, PR-218); the runner's own defaults (0.01, 400 epochs) are the
LEGACY recipe, kept so Finding 8 stays reproducible. The statistic is new,
and it differs from Finding 8's on purpose:

- Finding 8 compares the trained policy's CVaR with the baseline's on the SAME paths the policy was
  trained on, and the policy's number is the last epoch's SAMPLED (exploring) rollout. Both facts
  are disclosed there. They bias in opposite directions, so the result is not wrong, but it is not
  the cleanest comparison either. This module keeps that number (`in_sample_ratio`) so the old
  finding can be reproduced, and reports the endpoint on HELD-OUT paths instead:
- `ratio` = CVaR_95(policy) / CVaR_95(static baseline) on `N_EVAL_PATHS` fresh paths drawn from a
  generator that is independent of the training one, with the policy acting deterministically (its
  mean action, `hedge_ratios_from_policy`) and both hedges seeing the same paths.

The endpoint is `theta = -mean(log ratio)` over seeds, so a positive theta favours the policy, with
a t interval across seeds (one independent training run each) and the protocol's equivalence margin
`MARGIN = ln(1.05)`: a 5% CVaR difference is treated as no difference that matters. That margin is a
proposal the maintainer confirms at the freeze.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import asdict, dataclass, replace
from typing import Any

import numpy as np

from prometheus.confirmatory.intervals import classify_effect, t_interval
from prometheus.hedging.baseline import apply_no_trade_band, black_scholes_delta_hedge_ratios
from prometheus.hedging.rl_agent import HedgeRLPolicyNet, hedge_ratios_from_policy
from prometheus.hedging.simulate import simulate_self_financing_hedge
from prometheus.orchestration.rl_hedge_run import RlHedgeRunConfig, run_rl_hedge
from prometheus.stochastica.gbm import simulate_gbm_paths

MARGIN = math.log(1.05)
FROZEN_LEARNING_RATE = 0.003
FROZEN_N_EPOCHS = 2000
LEGACY_LEARNING_RATE = 0.01
LEGACY_N_EPOCHS = 400
"""The runner's default learning rate, which produced Finding 8 (with 400 or 800 epochs)."""
N_EVAL_PATHS = 20_000
EVAL_STREAM = 1
"""Second element of the evaluation generator's seed `[seed, EVAL_STREAM]`: training uses
`default_rng(seed)`, so the two streams are independent."""


@dataclass(frozen=True, slots=True)
class SeedResult:
    seed: int
    n_epochs: int
    static_cvar: float
    """Baseline CVaR on the held-out paths."""
    policy_cvar: float
    """Trained policy's CVaR on the same held-out paths (deterministic actions)."""
    ratio: float
    """`policy_cvar / static_cvar`; below 1 means the policy is better."""
    in_sample_ratio: float
    """Finding 8's statistic: the last epoch's sampled-policy CVaR over the baseline's, on the
    training paths."""


def tail_cvar(terminal_loss: np.ndarray, alpha: float) -> float:
    """Mean of the worst `1 - alpha` share of losses, exactly as `run_rl_hedge` computes it."""
    sorted_loss = np.sort(terminal_loss)
    tail_start = int(np.ceil(alpha * len(sorted_loss)))
    if tail_start >= len(sorted_loss):
        return float(sorted_loss[-1])
    return float(np.mean(sorted_loss[tail_start:]))


def simulate_paths(config: RlHedgeRunConfig, n_paths: int, rng: np.random.Generator) -> np.ndarray:
    return simulate_gbm_paths(
        s0=config.s0,
        mu=config.mu,
        sigma=config.sigma,
        maturity=config.maturity,
        n_steps=config.n_steps,
        n_paths=n_paths,
        rng=rng,
    )


def evaluation_paths(config: RlHedgeRunConfig, n_paths: int = N_EVAL_PATHS) -> np.ndarray:
    """Held-out paths for one seed: never the training paths, and the same for both hedges."""
    return simulate_paths(config, n_paths, np.random.default_rng([config.seed, EVAL_STREAM]))


def static_hedge_loss(config: RlHedgeRunConfig, paths: np.ndarray) -> np.ndarray:
    """Terminal loss of the static delta / no-trade-band baseline: `run_rl_hedge`'s own chain."""
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
    ratios = apply_no_trade_band(delta, band_width=config.band_width)
    simulated = simulate_self_financing_hedge(
        paths,
        dt,
        config.strike,
        config.option_type,
        config.risk_free_rate,
        config.cost_rate,
        config.initial_premium,
        ratios,
    )
    return np.asarray(simulated.terminal_loss, dtype=np.float64)


def policy_hedge_loss(
    config: RlHedgeRunConfig, policy: HedgeRLPolicyNet, paths: np.ndarray
) -> np.ndarray:
    """Terminal loss of a trained policy acting deterministically (its mean action)."""
    dt = config.maturity / config.n_steps
    ratios = hedge_ratios_from_policy(policy, paths)
    simulated = simulate_self_financing_hedge(
        paths,
        dt,
        config.strike,
        config.option_type,
        config.risk_free_rate,
        config.cost_rate,
        config.initial_premium,
        ratios,
    )
    return np.asarray(simulated.terminal_loss, dtype=np.float64)


def evaluate_seed(
    seed: int,
    *,
    n_epochs: int | None = None,
    learning_rate: float | None = None,
    n_paths: int | None = None,
    n_eval_paths: int = N_EVAL_PATHS,
) -> SeedResult:
    """Train once with the frozen (tuned) recipe, overridable only to reproduce Finding 8 (legacy
    learning rate, 400 or 800 epochs) and for fast tests, and score on held-out paths."""
    config = replace(
        RlHedgeRunConfig(seed=seed),
        n_epochs=FROZEN_N_EPOCHS if n_epochs is None else n_epochs,
        learning_rate=FROZEN_LEARNING_RATE if learning_rate is None else learning_rate,
    )
    if n_paths is not None:
        config = replace(config, n_paths=n_paths)
    run = run_rl_hedge(config)
    paths = evaluation_paths(config, n_eval_paths)
    static = tail_cvar(static_hedge_loss(config, paths), config.cvar_alpha)
    policy = tail_cvar(policy_hedge_loss(config, run.trained.policy, paths), config.cvar_alpha)
    return SeedResult(
        seed=seed,
        n_epochs=config.n_epochs,
        static_cvar=static,
        policy_cvar=policy,
        ratio=policy / static,
        in_sample_ratio=run.trained.final_cvar / run.static_baseline_cvar,
    )


def analyse(
    results: Sequence[SeedResult], *, confidence: float, margin: float = MARGIN
) -> dict[str, Any]:
    """The endpoint from per-seed results: `theta = -mean(log ratio)`, positive for the policy."""
    if len(results) < 2:
        raise ValueError("E1 needs at least two seeds to estimate a spread")
    ratios = np.array([r.ratio for r in results], dtype=np.float64)
    if not np.all(np.isfinite(ratios)) or np.any(ratios <= 0.0):
        raise ValueError(
            "a CVaR ratio is undefined or non-positive; the endpoint cannot be computed"
        )
    interval = t_interval(-np.log(ratios), confidence)
    in_sample = [r.in_sample_ratio for r in results]
    return {
        "endpoint": "E1",
        "statistic": "theta = -mean(log(CVaR95 policy / CVaR95 static)) on held-out paths; "
        "positive favours the policy",
        "n_seeds": len(results),
        "margin": margin,
        "interval": interval.as_dict(),
        "outcome": classify_effect(interval, margin),
        "median_ratio": float(np.median(ratios)),
        "n_seeds_policy_better": int(np.sum(ratios < 1.0)),
        "in_sample_ratio_min": float(min(in_sample)),
        "in_sample_ratio_max": float(max(in_sample)),
        "n_seeds_policy_better_in_sample": int(sum(r < 1.0 for r in in_sample)),
        "per_seed": [asdict(r) for r in results],
    }


def run_e1(
    seeds: Sequence[int], *, confidence: float, n_eval_paths: int = N_EVAL_PATHS
) -> dict[str, Any]:
    """Train and score every seed, then analyse. Reserved seeds are checked by the caller."""
    results = [evaluate_seed(seed, n_eval_paths=n_eval_paths) for seed in seeds]
    return analyse(results, confidence=confidence)
