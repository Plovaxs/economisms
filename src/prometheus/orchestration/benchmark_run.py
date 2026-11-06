"""Train, evaluate and export a fully specified synthetic hedge benchmark.

The endpoint and seed-wise decision rule are fixed in code. Test seeds are
distinct from the training path seed; no seed is dropped based on results.
This is one training run, not evidence across independent retrainings.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass, fields, replace
from datetime import date
from pathlib import Path
from typing import Any, Literal

import numpy as np

from prometheus.evidence.export import build_evidence_bundle, export_evidence_bundle
from prometheus.evidence.repository_status import (
    build_deep_hedge_model_card,
    current_repository_gate_report,
    policy_content_hash,
)
from prometheus.experiments.hedge_benchmark import HedgeBenchmarkReport, run_hedge_benchmark
from prometheus.experiments.manifest import RunManifest, compute_result_hash, new_run_id, now_iso
from prometheus.hedging.deep_hedge import train_deep_hedge
from prometheus.stochastica.gbm import simulate_gbm_paths
from prometheus.volterra.black_scholes import black_scholes_price
from prometheus.volterra.instruments import EuropeanOption, OptionType
from prometheus.volterra.market import MarketSnapshot

DECISION_RULE = "All per-seed confidence intervals exclude zero in the same direction"
Verdict = Literal["policy_better", "delta_better", "inconclusive"]


@dataclass(frozen=True, slots=True)
class BenchmarkRunConfig:
    seed: int = 0
    train_path_seed: int = 1
    test_seeds: tuple[int, ...] = (100, 200, 300)
    n_steps: int = 20
    n_train_paths: int = 2_000
    n_train_epochs: int = 80
    batch_size: int = 256
    learning_rate: float = 0.01
    turnover_penalty: float = 0.001
    n_eval_paths: int = 2_000
    n_bootstrap_resamples: int = 1_000
    bootstrap_confidence: float = 0.95
    cvar_alpha: float = 0.9
    spot: float = 100.0
    strike: float = 100.0
    maturity: float = 1.0
    option_type: OptionType = "call"
    risk_free_rate: float = 0.05
    mu: float = 0.08
    volatility: float = 0.2
    cost_rate: float = 0.005
    initial_premium: float | None = None

    def __post_init__(self) -> None:
        for name in (
            "seed",
            "train_path_seed",
            "n_steps",
            "n_train_paths",
            "n_train_epochs",
            "batch_size",
            "n_eval_paths",
            "n_bootstrap_resamples",
        ):
            value = getattr(self, name)
            minimum = 0 if name in ("seed", "train_path_seed") else 1
            if type(value) is not int or value < minimum:
                raise ValueError(f"{name} must be an integer >= {minimum}")
        if not isinstance(self.test_seeds, tuple) or not self.test_seeds:
            raise ValueError("test_seeds must be a non-empty tuple")
        if any(type(seed) is not int or seed < 0 for seed in self.test_seeds):
            raise ValueError("test_seeds must contain non-negative integers")
        if len(set(self.test_seeds)) != len(self.test_seeds):
            raise ValueError("test_seeds must be unique")
        if self.train_path_seed in self.test_seeds:
            raise ValueError("test_seeds must not include train_path_seed")
        if self.batch_size > self.n_train_paths:
            raise ValueError("batch_size must not exceed n_train_paths")
        for name in (
            "learning_rate",
            "turnover_penalty",
            "bootstrap_confidence",
            "cvar_alpha",
            "spot",
            "strike",
            "maturity",
            "risk_free_rate",
            "mu",
            "volatility",
            "cost_rate",
            "initial_premium",
        ):
            value = getattr(self, name)
            if name == "initial_premium" and value is None:
                continue
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ValueError(f"{name} must be a finite number")
            if not math.isfinite(value):
                raise ValueError(f"{name} must be finite")
        for name in ("learning_rate", "spot", "strike", "maturity", "volatility"):
            if getattr(self, name) <= 0:
                raise ValueError(f"{name} must be positive")
        for name in ("turnover_penalty", "cost_rate"):
            if getattr(self, name) < 0:
                raise ValueError(f"{name} must be non-negative")
        if self.initial_premium is not None and self.initial_premium < 0:
            raise ValueError("initial_premium must be non-negative")
        if not 0 < self.cvar_alpha < 1 or not 0 < self.bootstrap_confidence < 1:
            raise ValueError("cvar_alpha and bootstrap_confidence must be in (0, 1)")
        if self.option_type not in ("call", "put"):
            raise ValueError("option_type must be call or put")

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> BenchmarkRunConfig:
        if set(payload) != {item.name for item in fields(cls)}:
            raise ValueError("benchmark replay requires exactly the complete configuration fields")
        values = dict(payload)
        if isinstance(values["test_seeds"], (list, tuple)):
            values["test_seeds"] = tuple(values["test_seeds"])
        try:
            return cls(**values)
        except TypeError as exc:
            raise ValueError(f"invalid benchmark replay configuration: {exc}") from exc


@dataclass(frozen=True, slots=True)
class BenchmarkRunResult:
    report: HedgeBenchmarkReport
    verdict: Verdict
    manifest: RunManifest
    evidence_bundle: dict[str, Any]


def run_benchmark(config: BenchmarkRunConfig) -> BenchmarkRunResult:
    premium = config.initial_premium
    if premium is None:
        premium = float(
            black_scholes_price(
                MarketSnapshot(
                    date(2026, 1, 2), config.spot, config.risk_free_rate, config.volatility
                ),
                EuropeanOption(config.strike, config.maturity, config.option_type),
            )
        )
    train_paths = simulate_gbm_paths(
        config.spot,
        config.mu,
        config.volatility,
        config.maturity,
        config.n_steps,
        config.n_train_paths,
        np.random.default_rng(config.train_path_seed),
    )
    training = train_deep_hedge(
        train_paths,
        config.maturity / config.n_steps,
        config.strike,
        config.maturity,
        config.option_type,
        config.risk_free_rate,
        config.cost_rate,
        premium,
        cvar_alpha=config.cvar_alpha,
        turnover_penalty=config.turnover_penalty,
        n_epochs=config.n_train_epochs,
        batch_size=config.batch_size,
        learning_rate=config.learning_rate,
        seed=config.seed,
    )
    report = run_hedge_benchmark(
        training,
        config.strike,
        config.maturity,
        config.option_type,
        config.risk_free_rate,
        config.volatility,
        config.cost_rate,
        premium,
        config.n_steps,
        config.n_eval_paths,
        list(config.test_seeds),
        cvar_alpha=config.cvar_alpha,
        n_bootstrap_resamples=config.n_bootstrap_resamples,
        bootstrap_confidence=config.bootstrap_confidence,
        spot=config.spot,
        mu=config.mu,
    )
    verdict: Verdict = "inconclusive"
    if report.all_seeds_exclude_zero_same_direction():
        verdict = "policy_better" if report.mean_point_estimate() > 0 else "delta_better"
    config_payload = asdict(config)
    config_payload["initial_premium"] = premium
    limitations = report.limitations + (
        "Only one training seed; confidence intervals condition on that trained policy.",
        "Seed-wise percentile intervals are not a multiple-testing-adjusted pooled estimate.",
        "Test paths/bootstrap use independent named RNG streams per evaluation seed.",
    )
    payload = {
        "schema_version": 1,
        "accounting_convention": "trade-then-accrue-v1",
        "config": config_payload,
        "policy_content_hash": policy_content_hash(training.policy),
        "training_data": {
            "sha256": hashlib.sha256(train_paths.astype("<f8", copy=False).tobytes()).hexdigest(),
            "encoding": "row-major float64 little-endian",
            "shape": list(train_paths.shape),
        },
        "training_objective_history": training.objective_history,
        "evaluation": report.result_payload(),
        "verdict": verdict,
        "decision_rule": DECISION_RULE,
        "limitations": limitations,
    }
    manifest = RunManifest(
        new_run_id("pmth-benchmark"),
        now_iso(),
        config.seed,
        config_payload,
        compute_result_hash(payload),
    )
    mean_cvar = float(np.mean([item.policy_cvar for item in report.per_seed_results]))
    mean_loss = float(np.mean([item.policy_mean_loss for item in report.per_seed_results]))
    card = build_deep_hedge_model_card(
        training.policy,
        config.n_train_paths,
        config.train_path_seed,
        mean_cvar,
        mean_loss,
        config.cvar_alpha,
    )
    card = replace(
        card,
        primary_metrics={
            f"mean_seed_cvar_{config.cvar_alpha:g}": mean_cvar,
            "mean_seed_terminal_loss": mean_loss,
        },
        training_data_summary=card.training_data_summary + f" Policy seed={config.seed}.",
        metric_uncertainty_note=(
            "Metrics are unweighted means of per-seed estimates, not pooled CVaR. "
            "The evaluation section reports paired percentile intervals per seed. "
            "Only one policy was trained; these intervals do not cover retraining variability."
        ),
        failure_modes=card.failure_modes + limitations,
    )
    bundle = build_evidence_bundle(manifest, [card], current_repository_gate_report())
    bundle["benchmark"] = payload
    return BenchmarkRunResult(report, verdict, manifest, bundle)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--train-path-seed", type=int, default=1)
    parser.add_argument("--test-seeds", type=int, nargs="+", default=[100, 200, 300])
    parser.add_argument("--train-paths", type=int, default=2_000)
    parser.add_argument("--train-epochs", type=int, default=80)
    parser.add_argument("--batch-size", type=int, default=256)
    parser.add_argument("--eval-paths", type=int, default=2_000)
    parser.add_argument("--bootstrap-resamples", type=int, default=1_000)
    parser.add_argument("--steps", type=int, default=20)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    try:
        config = BenchmarkRunConfig(
            seed=args.seed,
            train_path_seed=args.train_path_seed,
            test_seeds=tuple(args.test_seeds),
            n_train_paths=args.train_paths,
            n_train_epochs=args.train_epochs,
            batch_size=args.batch_size,
            n_eval_paths=args.eval_paths,
            n_bootstrap_resamples=args.bootstrap_resamples,
            n_steps=args.steps,
        )
    except ValueError as exc:
        parser.error(str(exc))
    result = run_benchmark(config)
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        export_evidence_bundle(result.evidence_bundle, args.output)
    print(
        json.dumps(
            {
                "verdict": result.verdict,
                "primary_endpoint": result.report.primary_endpoint,
                "mean_seed_difference": result.report.mean_point_estimate(),
                "result_hash": result.manifest.result_hash,
                "evidence_path": str(args.output) if args.output else None,
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
