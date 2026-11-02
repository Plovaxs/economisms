"""A first, deliberately modest research benchmark (PR-008): compares the
Black-Scholes delta baseline against a trained MLP hedging policy across
several independent held-out seeds, with a pre-registered primary endpoint
and paired bootstrap confidence intervals.

Scope note: the blueprint's full factorial economy x market x hedge matrix
(section 10) needs an experimental arm on every axis. This benchmark only
varies the hedge dimension (delta baseline vs. MLP policy) under a single
fixed classical GBM market and no economy integration -- learned economy
agents and a neural/macro-conditioned market model do not exist yet (see
CHECKLIST_STATUS.md). It is one slice of EXP-02's matrix, not the whole
thing, and this module does not claim otherwise anywhere in its output.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from prometheus.experiments.bootstrap import BootstrapResult, paired_bootstrap_difference
from prometheus.experiments.manifest import RunManifest, compute_result_hash, new_run_id, now_iso
from prometheus.hedging.baseline import black_scholes_delta_hedge_ratios
from prometheus.hedging.deep_hedge import DeepHedgeTrainingResult, generate_policy_hedge_ratios
from prometheus.hedging.simulate import simulate_self_financing_hedge
from prometheus.stochastica.gbm import simulate_gbm_paths
from prometheus.titan.risk_metrics import historical_expected_shortfall
from prometheus.volterra.instruments import OptionType

PRIMARY_ENDPOINT = "cvar_difference_delta_minus_policy"
"""EXP-01: the primary endpoint, fixed before results are examined.
Positive values mean the trained policy has LOWER (better) CVaR than the
delta baseline; this module does not pick a different endpoint after the
fact."""

LIMITATIONS: tuple[str, ...] = (
    "Only the hedge dimension is varied (delta baseline vs. MLP policy); the "
    "economy and market dimensions of the blueprint's factorial matrix "
    "(section 10) have no experimental arm implemented yet.",
    "Evaluated under a single classical GBM market model at one fixed "
    "(strike, maturity, volatility) configuration, not a scenario grid.",
    "No distribution-shift/out-of-distribution evaluation (EXP-12): training "
    "and every test seed draw from the same GBM parameterization.",
    "The percentile bootstrap is used for confidence intervals, not a "
    "bias-corrected-and-accelerated (BCa) or block-bootstrap variant.",
)


@dataclass(frozen=True, slots=True)
class SeedResult:
    test_seed: int
    delta_cvar: float
    policy_cvar: float
    bootstrap: BootstrapResult


@dataclass(frozen=True, slots=True)
class HedgeBenchmarkReport:
    manifest: RunManifest
    primary_endpoint: str
    cvar_alpha: float
    per_seed_results: tuple[SeedResult, ...]
    limitations: tuple[str, ...]

    def mean_point_estimate(self) -> float:
        return float(np.mean([r.bootstrap.point_estimate for r in self.per_seed_results]))

    def all_seeds_exclude_zero_same_direction(self) -> bool:
        """True only if every seed's CI excludes zero AND every point
        estimate agrees in sign -- a conservative bar for "the effect is
        robust across evaluation scenarios" (section 10)."""
        if not self.per_seed_results:
            return False
        signs = {np.sign(r.bootstrap.point_estimate) for r in self.per_seed_results}
        all_exclude = all(r.bootstrap.excludes_zero() for r in self.per_seed_results)
        return bool(all_exclude and len(signs) == 1)


def run_hedge_benchmark(
    training_result: DeepHedgeTrainingResult,
    strike: float,
    maturity: float,
    option_type: OptionType,
    risk_free_rate: float,
    volatility: float,
    cost_rate: float,
    initial_premium: float,
    n_steps: int,
    n_paths_per_seed: int,
    test_seeds: list[int],
    cvar_alpha: float = 0.95,
    n_bootstrap_resamples: int = 2000,
    bootstrap_confidence: float = 0.95,
    spot: float = 100.0,
    mu: float | None = None,
) -> HedgeBenchmarkReport:
    if not test_seeds:
        raise ValueError("test_seeds must be non-empty")

    dt = maturity / n_steps
    drift = risk_free_rate if mu is None else mu

    def cvar_metric(losses: np.ndarray) -> float:
        return historical_expected_shortfall(losses, cvar_alpha)

    per_seed_results: list[SeedResult] = []
    for test_seed in test_seeds:
        path_rng = np.random.default_rng(test_seed)
        test_paths = simulate_gbm_paths(
            spot, drift, volatility, maturity, n_steps, n_paths_per_seed, path_rng
        )

        delta_ratios = black_scholes_delta_hedge_ratios(
            test_paths, dt, strike, maturity, risk_free_rate, volatility, option_type
        )
        delta_result = simulate_self_financing_hedge(
            test_paths,
            dt,
            strike,
            option_type,
            risk_free_rate,
            cost_rate,
            initial_premium,
            delta_ratios,
        )

        policy_ratios = generate_policy_hedge_ratios(
            training_result.policy, test_paths, dt, strike, maturity
        )
        policy_result = simulate_self_financing_hedge(
            test_paths,
            dt,
            strike,
            option_type,
            risk_free_rate,
            cost_rate,
            initial_premium,
            policy_ratios,
        )

        bootstrap_rng = np.random.default_rng(test_seed)
        bootstrap = paired_bootstrap_difference(
            cvar_metric,
            delta_result.terminal_loss,
            policy_result.terminal_loss,
            bootstrap_rng,
            n_resamples=n_bootstrap_resamples,
            confidence=bootstrap_confidence,
        )

        per_seed_results.append(
            SeedResult(
                test_seed=test_seed,
                delta_cvar=cvar_metric(delta_result.terminal_loss),
                policy_cvar=cvar_metric(policy_result.terminal_loss),
                bootstrap=bootstrap,
            )
        )

    config = {
        "strike": strike,
        "maturity": maturity,
        "option_type": option_type,
        "risk_free_rate": risk_free_rate,
        "volatility": volatility,
        "cost_rate": cost_rate,
        "initial_premium": initial_premium,
        "n_steps": n_steps,
        "n_paths_per_seed": n_paths_per_seed,
        "test_seeds": test_seeds,
        "cvar_alpha": cvar_alpha,
        "n_bootstrap_resamples": n_bootstrap_resamples,
        "bootstrap_confidence": bootstrap_confidence,
        "spot": spot,
        "mu": drift,
    }
    result_payload = {
        "primary_endpoint": PRIMARY_ENDPOINT,
        "config": config,
        "per_seed": [
            {
                "test_seed": r.test_seed,
                "delta_cvar": round(r.delta_cvar, 10),
                "policy_cvar": round(r.policy_cvar, 10),
                "point_estimate": round(r.bootstrap.point_estimate, 10),
                "ci_low": round(r.bootstrap.ci_low, 10),
                "ci_high": round(r.bootstrap.ci_high, 10),
            }
            for r in per_seed_results
        ],
    }
    manifest = RunManifest(
        run_id=new_run_id(),
        created_at=now_iso(),
        seed=test_seeds[0],
        config=config,
        result_hash=compute_result_hash(result_payload),
    )

    return HedgeBenchmarkReport(
        manifest=manifest,
        primary_endpoint=PRIMARY_ENDPOINT,
        cvar_alpha=cvar_alpha,
        per_seed_results=tuple(per_seed_results),
        limitations=LIMITATIONS,
    )
