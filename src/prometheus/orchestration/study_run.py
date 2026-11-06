"""Cross independently retrained hedges with held-out path banks and stress scenarios.

Each model trains once on the declared training distribution. Every fitted
model sees the same test paths in each scenario. Premium, strike, maturity,
financing rate and delta's assumed volatility remain fixed; stress changes
realized drift/volatility or execution cost for both hedges. No oracle
volatility/cost feature is supplied to the learned policy.

The study averages cell-level CVaR differences; it never pools all losses
or selects the best training seed. An exploratory pigeonhole bootstrap
resamples training rows and test-bank columns separately. Scenario tail
error is allocated by Bonferroni; nominal coverage is not a finite-sample
guarantee for percentile bootstrap intervals with small seed counts.
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

from prometheus.core.seeds import SeedHierarchy
from prometheus.evidence.export import build_evidence_bundle, export_evidence_bundle
from prometheus.evidence.repository_status import (
    build_deep_hedge_model_card,
    current_repository_gate_report,
    policy_content_hash,
)
from prometheus.experiments.crossed_bootstrap import (
    CrossedBootstrapResult,
    bonferroni_confidence,
    crossed_mean_bootstrap,
)
from prometheus.experiments.hedge_benchmark import PRIMARY_ENDPOINT, SeedResult, run_hedge_benchmark
from prometheus.experiments.manifest import RunManifest, compute_result_hash, new_run_id, now_iso
from prometheus.hedging.deep_hedge import train_deep_hedge
from prometheus.orchestration.benchmark_run import BenchmarkRunConfig
from prometheus.stochastica.gbm import simulate_gbm_paths
from prometheus.volterra.black_scholes import black_scholes_price
from prometheus.volterra.instruments import EuropeanOption, OptionType
from prometheus.volterra.market import MarketSnapshot

STUDY_ENDPOINT = "mean_cell_cvar_difference_delta_minus_policy"
STUDY_DECISION_RULE = (
    "All declared scenarios' crossed-bootstrap intervals must exceed the predeclared "
    "economic margin in the same direction; nominal Bonferroni tail allocation across scenarios"
)
StudyVerdict = Literal["policy_better", "delta_better", "inconclusive"]
LIMITATIONS = (
    "Synthetic single-asset GBM stress grid; no historical data, Heston/jumps or macro factorial.",
    "Retraining replicates vary policy initialization and training data together, not separately.",
    "Few independent seed levels can give unreliable percentile coverage; no exact guarantee.",
    "Crossed resampling treats seed levels as independent draws and retains shared test banks.",
    "Single-axis intervals/seed dispersions are conditional diagnostics, not variance components.",
    "The endpoint averages cell CVaRs; it is not the CVaR of a pooled or ensemble portfolio.",
    "Bonferroni allocates nominal tail error; it does not calibrate bootstrap marginal coverage.",
    "Premium and delta pricing volatility stay at training assumptions under all stress scenarios.",
)


@dataclass(frozen=True, slots=True, order=True)
class TrainingSeed:
    policy_seed: int
    path_seed: int

    def __post_init__(self) -> None:
        if any(type(seed) is not int or seed < 0 for seed in (self.policy_seed, self.path_seed)):
            raise ValueError("training seeds must be non-negative integers")


@dataclass(frozen=True, slots=True)
class MarketScenario:
    name: str
    mu: float
    volatility: float
    cost_rate: float

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or not self.name.strip():
            raise ValueError("scenario name must be non-empty")
        for value in (self.mu, self.volatility, self.cost_rate):
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(value)
            ):
                raise ValueError("scenario parameters must be finite numbers")
        if self.volatility <= 0 or self.cost_rate < 0:
            raise ValueError("scenario volatility must be positive and cost_rate non-negative")


@dataclass(frozen=True, slots=True)
class StudyRunConfig:
    seed: int = 0
    training_seeds: tuple[TrainingSeed, ...] = (
        TrainingSeed(0, 1),
        TrainingSeed(7, 2),
        TrainingSeed(13, 3),
    )
    test_seeds: tuple[int, ...] = (100, 200, 300)
    scenarios: tuple[MarketScenario, ...] = (
        MarketScenario("baseline", 0.08, 0.2, 0.005),
        MarketScenario("high_volatility", 0.08, 0.35, 0.005),
        MarketScenario("higher_costs", 0.08, 0.2, 0.01),
    )
    primary_scenario: str = "baseline"
    economic_margin: float = 0.0
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

    def training_config(self, seed: TrainingSeed) -> BenchmarkRunConfig:
        values = {
            item.name: getattr(self, item.name)
            for item in fields(BenchmarkRunConfig)
            if item.name not in ("seed", "train_path_seed")
        }
        return BenchmarkRunConfig(seed=seed.policy_seed, train_path_seed=seed.path_seed, **values)

    def __post_init__(self) -> None:
        if type(self.seed) is not int or self.seed < 0:
            raise ValueError("study seed must be a non-negative integer")
        if not isinstance(self.training_seeds, tuple) or len(self.training_seeds) < 2:
            raise ValueError("study requires at least two independent training seeds")
        if any(not isinstance(seed, TrainingSeed) for seed in self.training_seeds):
            raise ValueError("training_seeds must contain TrainingSeed objects")
        if len({seed.policy_seed for seed in self.training_seeds}) != len(self.training_seeds):
            raise ValueError("policy seeds must be unique across retrainings")
        if len({seed.path_seed for seed in self.training_seeds}) != len(self.training_seeds):
            raise ValueError("training path seeds must be unique across retrainings")
        if not isinstance(self.test_seeds, tuple) or len(self.test_seeds) < 2:
            raise ValueError("study requires at least two independent test banks")
        if not isinstance(self.scenarios, tuple) or not self.scenarios:
            raise ValueError("study requires a non-empty scenario tuple")
        if any(not isinstance(scenario, MarketScenario) for scenario in self.scenarios):
            raise ValueError("scenarios must contain MarketScenario objects")
        if len({scenario.name for scenario in self.scenarios}) != len(self.scenarios):
            raise ValueError("scenario names must be unique")
        if self.primary_scenario not in {scenario.name for scenario in self.scenarios}:
            raise ValueError("primary_scenario must name a declared scenario")
        if (
            isinstance(self.economic_margin, bool)
            or not isinstance(self.economic_margin, (int, float))
            or not math.isfinite(self.economic_margin)
            or self.economic_margin < 0
        ):
            raise ValueError("economic_margin must be finite and non-negative")
        for seed in self.training_seeds:
            self.training_config(seed)  # Reuse the complete benchmark recipe validation.
        bonferroni_confidence(self.bootstrap_confidence, len(self.scenarios))

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> StudyRunConfig:
        if set(payload) != {item.name for item in fields(cls)}:
            raise ValueError("study replay requires exactly the complete configuration fields")
        values = dict(payload)
        try:
            values["training_seeds"] = tuple(
                TrainingSeed(**seed) for seed in values["training_seeds"]
            )
            values["scenarios"] = tuple(
                MarketScenario(**scenario) for scenario in values["scenarios"]
            )
            values["test_seeds"] = tuple(values["test_seeds"])
            return cls(**values)
        except (TypeError, AttributeError) as exc:
            raise ValueError(f"invalid study replay configuration: {exc}") from exc


@dataclass(frozen=True, slots=True)
class StudyCell:
    training: TrainingSeed
    evaluation: SeedResult


@dataclass(frozen=True, slots=True)
class ScenarioStudyResult:
    scenario: MarketScenario
    distribution_shift: bool
    cells: tuple[StudyCell, ...]
    differences: tuple[tuple[float, ...], ...]
    uncertainty: CrossedBootstrapResult
    verdict: StudyVerdict


@dataclass(frozen=True, slots=True)
class StudyRunResult:
    scenarios: tuple[ScenarioStudyResult, ...]
    verdict: StudyVerdict
    manifest: RunManifest
    evidence_bundle: dict[str, Any]


def interval_verdict(low: float, high: float, margin: float) -> StudyVerdict:
    if low > margin:
        return "policy_better"
    if high < -margin:
        return "delta_better"
    return "inconclusive"


def run_study(config: StudyRunConfig) -> StudyRunResult:
    training_seeds = sorted(config.training_seeds)
    test_seeds = sorted(config.test_seeds)
    scenarios = sorted(config.scenarios, key=lambda scenario: scenario.name)
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
    cells: dict[str, list[StudyCell]] = {scenario.name: [] for scenario in scenarios}
    trained = []
    cards = []
    for training_seed in training_seeds:
        recipe = config.training_config(training_seed)
        paths = simulate_gbm_paths(
            config.spot,
            config.mu,
            config.volatility,
            config.maturity,
            config.n_steps,
            config.n_train_paths,
            np.random.default_rng(training_seed.path_seed),
        )
        training = train_deep_hedge(
            paths,
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
            seed=training_seed.policy_seed,
        )
        recipe_payload = asdict(recipe)
        recipe_payload["initial_premium"] = premium
        recipe_payload["test_seeds"] = test_seeds
        trained.append(
            {
                "seed": asdict(training_seed),
                "recipe": recipe_payload,
                "policy_content_hash": policy_content_hash(training.policy),
                "training_data_sha256": hashlib.sha256(
                    paths.astype("<f8", copy=False).tobytes()
                ).hexdigest(),
                "training_data_encoding": "row-major float64 little-endian",
                "training_objective_history": training.objective_history,
            }
        )
        for scenario in scenarios:
            report = run_hedge_benchmark(
                training,
                config.strike,
                config.maturity,
                config.option_type,
                config.risk_free_rate,
                config.volatility,
                scenario.cost_rate,
                premium,
                config.n_steps,
                config.n_eval_paths,
                test_seeds,
                cvar_alpha=config.cvar_alpha,
                n_bootstrap_resamples=config.n_bootstrap_resamples,
                bootstrap_confidence=config.bootstrap_confidence,
                spot=config.spot,
                mu=scenario.mu,
                simulation_volatility=scenario.volatility,
            )
            cells[scenario.name].extend(
                StudyCell(training_seed, row) for row in report.per_seed_results
            )
            if scenario.name == config.primary_scenario:
                mean_cvar = float(np.mean([row.policy_cvar for row in report.per_seed_results]))
                mean_loss = float(
                    np.mean([row.policy_mean_loss for row in report.per_seed_results])
                )
                card = build_deep_hedge_model_card(
                    training.policy,
                    config.n_train_paths,
                    training_seed.path_seed,
                    mean_cvar,
                    mean_loss,
                    config.cvar_alpha,
                )
                cards.append(
                    replace(
                        card,
                        model_id=f"{card.model_id}-seed-{training_seed.policy_seed}",
                        primary_metrics={
                            f"primary_mean_bank_cvar_{config.cvar_alpha:g}": mean_cvar,
                            "primary_mean_bank_loss": mean_loss,
                        },
                        metric_uncertainty_note=(
                            "Primary-scenario bank-averaged metrics for this one retraining. "
                            "Study intervals resample training replicates and shared test banks; "
                            "they are exploratory and do not establish exact coverage."
                        ),
                        training_data_summary=card.training_data_summary
                        + f" Policy seed={training_seed.policy_seed}.",
                        failure_modes=LIMITATIONS,
                    )
                )

    confidence = bonferroni_confidence(config.bootstrap_confidence, len(scenarios))
    summaries = []
    for scenario in scenarios:
        scenario_cells = tuple(cells[scenario.name])
        differences = np.array(
            [cell.evaluation.delta_cvar - cell.evaluation.policy_cvar for cell in scenario_cells]
        ).reshape(len(training_seeds), len(test_seeds))
        # Reinitialize the same bootstrap stream for each canonically ordered matrix,
        # retaining common row/column resamples across stress scenarios.
        uncertainty = crossed_mean_bootstrap(
            differences,
            SeedHierarchy(config.seed).stream("study-bootstrap"),
            n_resamples=config.n_bootstrap_resamples,
            confidence=confidence,
        )
        interval = uncertainty.crossed
        summaries.append(
            ScenarioStudyResult(
                scenario=scenario,
                distribution_shift=(scenario.mu, scenario.volatility, scenario.cost_rate)
                != (config.mu, config.volatility, config.cost_rate),
                cells=scenario_cells,
                differences=tuple(tuple(float(value) for value in row) for row in differences),
                uncertainty=uncertainty,
                verdict=interval_verdict(interval.ci_low, interval.ci_high, config.economic_margin),
            )
        )
    verdict: StudyVerdict = "inconclusive"
    if all(summary.verdict == "policy_better" for summary in summaries):
        verdict = "policy_better"
    elif all(summary.verdict == "delta_better" for summary in summaries):
        verdict = "delta_better"
    config_payload = asdict(config)
    config_payload.update(
        {
            "training_seeds": [asdict(seed) for seed in training_seeds],
            "test_seeds": test_seeds,
            "scenarios": [asdict(scenario) for scenario in scenarios],
            "initial_premium": premium,
        }
    )
    payload = {
        "schema_version": 1,
        "accounting_convention": "trade-then-accrue-v1",
        "config": config_payload,
        "primary_endpoint": STUDY_ENDPOINT,
        "cell_endpoint": PRIMARY_ENDPOINT,
        "decision_rule": STUDY_DECISION_RULE,
        "resampling_method": "pigeonhole percentile bootstrap of mean cell differences",
        "method_reference": "https://arxiv.org/abs/0712.1111",
        "scenario_interval_confidence": confidence,
        "training": trained,
        "scenarios": [asdict(summary) for summary in summaries],
        "verdict": verdict,
        "limitations": LIMITATIONS,
    }
    manifest = RunManifest(
        new_run_id("pmth-study"),
        now_iso(),
        config.seed,
        config_payload,
        compute_result_hash(payload),
    )
    bundle = build_evidence_bundle(manifest, cards, current_repository_gate_report())
    bundle["study"] = payload
    return StudyRunResult(tuple(summaries), verdict, manifest, bundle)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--policy-seeds", type=int, nargs="+", default=[0, 7, 13])
    parser.add_argument("--train-path-seeds", type=int, nargs="+", default=[1, 2, 3])
    parser.add_argument("--test-seeds", type=int, nargs="+", default=[100, 200, 300])
    parser.add_argument("--train-paths", type=int, default=2_000)
    parser.add_argument("--train-epochs", type=int, default=80)
    parser.add_argument("--batch-size", type=int, default=256)
    parser.add_argument("--eval-paths", type=int, default=2_000)
    parser.add_argument("--bootstrap-resamples", type=int, default=1_000)
    parser.add_argument("--steps", type=int, default=20)
    parser.add_argument("--economic-margin", type=float, default=0.0)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    try:
        if len(args.policy_seeds) != len(args.train_path_seeds):
            raise ValueError("policy and training-path seed lists must have the same length")
        config = StudyRunConfig(
            seed=args.seed,
            training_seeds=tuple(
                TrainingSeed(policy, path)
                for policy, path in zip(args.policy_seeds, args.train_path_seeds, strict=True)
            ),
            test_seeds=tuple(args.test_seeds),
            n_train_paths=args.train_paths,
            n_train_epochs=args.train_epochs,
            batch_size=args.batch_size,
            n_eval_paths=args.eval_paths,
            n_bootstrap_resamples=args.bootstrap_resamples,
            n_steps=args.steps,
            economic_margin=args.economic_margin,
        )
    except ValueError as exc:
        parser.error(str(exc))
    result = run_study(config)
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        export_evidence_bundle(result.evidence_bundle, args.output)
    print(
        json.dumps(
            {
                "verdict": result.verdict,
                "training_runs": len(config.training_seeds),
                "test_banks": len(config.test_seeds),
                "scenarios": len(config.scenarios),
                "result_hash": result.manifest.result_hash,
                "evidence_path": str(args.output) if args.output else None,
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
