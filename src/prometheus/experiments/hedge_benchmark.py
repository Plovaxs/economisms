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

import hashlib
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from typing import Any

import numpy as np

from prometheus.core.seeds import SeedHierarchy
from prometheus.evidence.repository_status import policy_content_hash
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
    delta_mean_loss: float
    policy_mean_loss: float
    delta_mean_cost: float
    policy_mean_cost: float
    delta_mean_turnover: float
    policy_mean_turnover: float
    path_hash: str | None = None

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        if self.path_hash is None:
            del payload["path_hash"]
        return payload


@dataclass(frozen=True, slots=True)
class HedgeBenchmarkReport:
    manifest: RunManifest
    primary_endpoint: str
    cvar_alpha: float
    per_seed_results: tuple[SeedResult, ...]
    limitations: tuple[str, ...]

    def result_payload(self) -> dict[str, Any]:
        return _result_payload(
            self.manifest.config, self.per_seed_results, self.cvar_alpha, self.limitations
        )

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


def _result_payload(
    config: Mapping[str, Any],
    results: tuple[SeedResult, ...],
    cvar_alpha: float,
    limitations: tuple[str, ...] = LIMITATIONS,
) -> dict[str, Any]:
    return {
        "schema_version": 2,
        "primary_endpoint": PRIMARY_ENDPOINT,
        "config": dict(config),
        "cvar_alpha": cvar_alpha,
        "per_seed": [result.to_dict() for result in results],
        "limitations": limitations,
    }


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
    *,
    simulation_volatility: float | None = None,
) -> HedgeBenchmarkReport:
    if not test_seeds:
        raise ValueError("test_seeds must be non-empty")
    if len(set(test_seeds)) != len(test_seeds):
        raise ValueError("test_seeds must be unique")
    if any(type(seed) is not int or seed < 0 for seed in test_seeds):
        raise ValueError("test_seeds must be non-negative integers")

    path_volatility = volatility if simulation_volatility is None else simulation_volatility
    if not np.isfinite(path_volatility) or path_volatility <= 0:
        raise ValueError("simulation volatility must be finite and positive")
    limitations = LIMITATIONS
    if simulation_volatility is not None:
        limitations = (
            "One fixed synthetic GBM scenario; training distribution is caller-specified.",
            "Delta uses declared pricing volatility, which can differ from realized volatility.",
            "Premium and hedge financing conventions are identical across both policies.",
            "Per-path paired percentile intervals condition on this one fitted policy/scenario.",
        )
    dt = maturity / n_steps
    drift = risk_free_rate if mu is None else mu

    def cvar_metric(losses: np.ndarray) -> float:
        return historical_expected_shortfall(losses, cvar_alpha)

    per_seed_results: list[SeedResult] = []
    for test_seed in test_seeds:
        streams = SeedHierarchy(test_seed)
        path_rng = streams.stream("held-out-paths")
        test_paths = simulate_gbm_paths(
            spot, drift, path_volatility, maturity, n_steps, n_paths_per_seed, path_rng
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

        bootstrap_rng = streams.stream("paired-bootstrap")
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
                delta_mean_loss=float(delta_result.terminal_loss.mean()),
                policy_mean_loss=float(policy_result.terminal_loss.mean()),
                delta_mean_cost=float(delta_result.total_cost.mean()),
                policy_mean_cost=float(policy_result.total_cost.mean()),
                delta_mean_turnover=float(delta_result.total_turnover.mean()),
                policy_mean_turnover=float(policy_result.total_turnover.mean()),
                path_hash=(
                    hashlib.sha256(test_paths.astype("<f8", copy=False).tobytes()).hexdigest()
                    if simulation_volatility is not None
                    else None
                ),
            )
        )

    config = {
        "accounting_convention": "trade-then-accrue-v1",
        "policy_content_hash": policy_content_hash(training_result.policy),
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
    results = tuple(per_seed_results)
    if simulation_volatility is not None:
        config["simulation_volatility"] = simulation_volatility
    manifest = RunManifest(
        run_id=new_run_id(),
        created_at=now_iso(),
        seed=test_seeds[0],
        config=config,
        result_hash=compute_result_hash(_result_payload(config, results, cvar_alpha, limitations)),
    )

    return HedgeBenchmarkReport(
        manifest=manifest,
        primary_endpoint=PRIMARY_ENDPOINT,
        cvar_alpha=cvar_alpha,
        per_seed_results=results,
        limitations=limitations,
    )
