"""Cross retrained hedges with shared macro/market banks and feedback scenarios.

A bank has one independent stochastic economy and many conditional market
paths. Every training replicate and scenario uses common market normals;
scenario variants also share economy noise. Cell CVaRs condition on their
bank's macro realization. The endpoint averages cell CVaR differences,
not the CVaR of a pooled unconditional macro/market distribution.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass, field, fields, replace
from fractions import Fraction
from pathlib import Path
from typing import Any

import numpy as np

from prometheus.core.calendar import BusinessDayCalendar
from prometheus.core.seeds import SeedHierarchy
from prometheus.econosim.monetary_feedback import InflationOutputRule
from prometheus.econosim.price_economy import EconomyRunConfig
from prometheus.evidence.export import build_evidence_bundle, export_evidence_bundle
from prometheus.evidence.repository_status import (
    build_deep_hedge_model_card,
    current_repository_gate_report,
    policy_content_hash,
)
from prometheus.experiments.crossed_bootstrap import bonferroni_confidence, crossed_mean_bootstrap
from prometheus.experiments.manifest import RunManifest, compute_result_hash, new_run_id, now_iso
from prometheus.hedging.comparison import DT, HedgeComparisonSettings
from prometheus.hedging.deep_hedge import generate_policy_hedge_ratios, train_deep_hedge
from prometheus.hedging.rate_paths import rate_scheduled_delta, rate_scheduled_gbm
from prometheus.hedging.simulate import HedgeSimulationResult, simulate_self_financing_hedge
from prometheus.orchestration.monetary_run import MonetaryRunConfig, run_monetary_macro_path
from prometheus.orchestration.study_run import TrainingSeed, interval_verdict
from prometheus.stochastica.gbm import simulate_gbm_paths
from prometheus.titan.risk_metrics import historical_expected_shortfall
from prometheus.volterra.black_scholes import black_scholes_price
from prometheus.volterra.instruments import EuropeanOption
from prometheus.volterra.market import MarketSnapshot

ENDPOINT = "mean_bank_conditional_cvar_difference_delta_minus_policy"
LIMITATIONS = (
    "Synthetic one-firm economy and classical single-asset GBM; no empirical identification.",
    "Each bank has one macro path; its CVaR is conditional on that realization, not unconditional.",
    "The endpoint averages conditional cell CVaRs; losses are not pooled across banks/models.",
    "Few training/bank seed levels make percentile coverage unreliable; no exact guarantee.",
    "Crossed resampling retains training rows/shared macro-market columns, not independent cells.",
    "Bonferroni allocates nominal tail error across scenarios, not calibrated marginal coverage.",
    "MLP trains once per replicate on constant-rate GBM and receives no rate/macro features.",
    "Delta uses only current rates and fixed pricing volatility; marks assume flat future rates.",
    "Economic and hedge books remain separate; macro has no feedback from asset/hedge wealth.",
    "Scenario comparisons diagnose sensitivity and do not identify optimal monetary policy.",
    "No scientific/independent review or deployment approval is provided.",
)


@dataclass(frozen=True, slots=True)
class FeedbackScenario:
    name: str
    productivity_shock_factor: float = 0.5
    publication_lag_months: int = 1
    payroll_rate_sensitivity: float = 2.0
    volatility_multiplier: float = 1.0
    cost_multiplier: float = 1.0

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or not self.name.strip():
            raise ValueError("scenario name must be nonempty")
        if type(self.publication_lag_months) is not int or self.publication_lag_months < 1:
            raise ValueError("publication lag must be a positive integer")
        for name in (
            "productivity_shock_factor",
            "payroll_rate_sensitivity",
            "volatility_multiplier",
            "cost_multiplier",
        ):
            value = getattr(self, name)
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(value)
            ):
                raise ValueError("scenario parameters must be finite numbers")
            if value < 0 or (name == "volatility_multiplier" and value == 0):
                raise ValueError("scenario parameters must be nonnegative; volatility positive")


@dataclass(frozen=True, slots=True)
class MonetaryStudyConfig:
    seed: int = 0
    training_seeds: tuple[TrainingSeed, ...] = (
        TrainingSeed(0, 1),
        TrainingSeed(7, 2),
        TrainingSeed(13, 3),
    )
    test_seeds: tuple[int, ...] = (100, 200, 300)
    scenarios: tuple[FeedbackScenario, ...] = (
        FeedbackScenario("baseline"),
        FeedbackScenario("delayed_publication", publication_lag_months=2),
        FeedbackScenario("no_payroll_channel", payroll_rate_sensitivity=0.0),
        FeedbackScenario("severe_supply_shock", productivity_shock_factor=0.3),
    )
    primary_scenario: str = "baseline"
    economy: EconomyRunConfig = field(
        default_factory=lambda: EconomyRunConfig(productivity_noise_std=0.03)
    )
    policy: InflationOutputRule = field(default_factory=InflationOutputRule)
    hedge: HedgeComparisonSettings = field(default_factory=HedgeComparisonSettings)
    initial_rate: float = 0.03
    inflation_window_months: int = 12
    potential_output: float = 180.0
    n_eval_paths: int = 512
    n_bootstrap_resamples: int = 1_000
    bootstrap_confidence: float = 0.95
    economic_margin: float = 0.0

    def macro_config(self, test_seed: int, scenario: FeedbackScenario) -> MonetaryRunConfig:
        economy_seed = int(
            SeedHierarchy(test_seed).stream("macro-study-economy-seed").integers(0, 2**32)
        )
        return MonetaryRunConfig(
            seed=test_seed,
            economy=replace(
                self.economy,
                seed=economy_seed,
                productivity_shock_multiplier=Fraction(str(scenario.productivity_shock_factor)),
            ),
            policy=self.policy,
            hedge=self.hedge,
            initial_rate=self.initial_rate,
            publication_lag_months=scenario.publication_lag_months,
            payroll_rate_sensitivity=scenario.payroll_rate_sensitivity,
            inflation_window_months=self.inflation_window_months,
            potential_output=self.potential_output,
        )

    def __post_init__(self) -> None:
        for name in ("seed", "n_eval_paths", "n_bootstrap_resamples"):
            if type(getattr(self, name)) is not int or getattr(self, name) < (
                0 if name == "seed" else 1
            ):
                raise ValueError(f"invalid {name}")
        if (
            not isinstance(self.economy, EconomyRunConfig)
            or not isinstance(self.policy, InflationOutputRule)
            or not isinstance(self.hedge, HedgeComparisonSettings)
        ):
            raise ValueError("economy, policy and hedge require typed settings")
        if (
            not isinstance(self.training_seeds, tuple)
            or len(self.training_seeds) < 2
            or any(not isinstance(seed, TrainingSeed) for seed in self.training_seeds)
        ):
            raise ValueError("at least two TrainingSeed replicates are required")
        for key in ("policy_seed", "path_seed"):
            if len({getattr(seed, key) for seed in self.training_seeds}) != len(
                self.training_seeds
            ):
                raise ValueError("training policy and path seeds must each be unique")
        if (
            not isinstance(self.test_seeds, tuple)
            or len(self.test_seeds) < 2
            or any(type(seed) is not int or seed < 0 for seed in self.test_seeds)
            or len(set(self.test_seeds)) != len(self.test_seeds)
        ):
            raise ValueError("at least two unique nonnegative test seeds are required")
        if (
            not isinstance(self.scenarios, tuple)
            or not self.scenarios
            or any(not isinstance(scenario, FeedbackScenario) for scenario in self.scenarios)
        ):
            raise ValueError("scenarios must be a nonempty FeedbackScenario tuple")
        if len({s.name for s in self.scenarios}) != len(self.scenarios):
            raise ValueError("scenario names must be unique")
        if self.primary_scenario not in {s.name for s in self.scenarios}:
            raise ValueError("primary_scenario must be declared")
        if (
            isinstance(self.economic_margin, bool)
            or not isinstance(self.economic_margin, (int, float))
            or not math.isfinite(self.economic_margin)
            or self.economic_margin < 0
        ):
            raise ValueError("economic_margin must be finite and nonnegative")
        bonferroni_confidence(self.bootstrap_confidence, len(self.scenarios))
        for scenario in self.scenarios:
            self.macro_config(self.test_seeds[0], scenario)
            replace(
                self.hedge,
                volatility=self.hedge.volatility * scenario.volatility_multiplier,
                cost_rate=self.hedge.cost_rate * scenario.cost_multiplier,
            )

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> MonetaryStudyConfig:
        if set(payload) != {item.name for item in fields(cls)}:
            raise ValueError("monetary study requires the complete configuration")
        values = dict(payload)
        try:
            for key, model in (("policy", InflationOutputRule), ("hedge", HedgeComparisonSettings)):
                if set(values[key]) != {item.name for item in fields(model)}:
                    raise ValueError(f"complete {key} configuration is required")
                values[key] = model(**values[key])
            values["economy"] = EconomyRunConfig.from_dict(values["economy"])
            for key, entry_model in (
                ("training_seeds", TrainingSeed),
                ("scenarios", FeedbackScenario),
            ):
                if any(set(item) != {f.name for f in fields(entry_model)} for item in values[key]):
                    raise ValueError(f"complete {key} configuration is required")
                values[key] = tuple(entry_model(**item) for item in values[key])
            values["test_seeds"] = tuple(values["test_seeds"])
            return cls(**values)
        except (TypeError, AttributeError) as exc:
            raise ValueError(f"invalid monetary study recipe: {exc}") from exc


def array_hash(values: np.ndarray) -> str:
    return hashlib.sha256(values.astype("<f8", copy=False).tobytes()).hexdigest()


def hedge_metrics(result: HedgeSimulationResult, alpha: float) -> dict[str, Any]:
    if any(
        not np.all(np.isfinite(values))
        for values in (result.terminal_loss, result.total_cost, result.total_turnover)
    ):
        raise ValueError("non-finite hedge results invalidate the study")
    return {
        "cvar": historical_expected_shortfall(result.terminal_loss, alpha),
        "mean_loss": float(np.mean(result.terminal_loss)),
        "mean_cost": float(np.mean(result.total_cost)),
        "mean_turnover": float(np.mean(result.total_turnover)),
        "terminal_loss_sha256": array_hash(result.terminal_loss),
    }


@dataclass(frozen=True, slots=True)
class MonetaryStudyResult:
    valid: bool
    verdict: str | None
    manifest: RunManifest
    evidence_bundle: dict[str, Any]


def build_feedback_banks(
    config: MonetaryStudyConfig,
) -> tuple[
    dict[tuple[str, int], tuple[np.ndarray, np.ndarray]],
    dict[str, list[dict[str, Any]]],
    list[str],
]:
    """Build shared evaluation banks independently of any fitted hedge policy."""
    scenarios = sorted(config.scenarios, key=lambda value: value.name)
    test_seeds = sorted(config.test_seeds)
    n_steps, h = config.economy.n_steps, config.hedge
    banks: dict[tuple[str, int], tuple[np.ndarray, np.ndarray]] = {}
    records: dict[str, list[dict[str, Any]]] = {scenario.name: [] for scenario in scenarios}
    reasons = []
    # Macro banks are independent of training and every scenario shares bank-level shocks.
    for scenario in scenarios:
        for seed in test_seeds:
            effective = config.macro_config(seed, scenario)
            macro = run_monetary_macro_path(effective)
            record = {
                "test_seed": seed,
                "economy_seed": effective.economy.seed,
                "macro": asdict(macro),
                "macro_sha256": compute_result_hash(asdict(macro)),
            }
            records[scenario.name].append(record)
            if not macro.valid:
                reasons.append(f"{scenario.name}/bank {seed}: {'; '.join(macro.invalid_reasons)}")
                continue
            rates = np.array(
                [config.initial_rate] + [step.policy.next_rate for step in macro.steps]
            )
            normals = (
                SeedHierarchy(seed)
                .stream("macro-study-market-normals")
                .standard_normal((config.n_eval_paths, n_steps))
            )
            paths = rate_scheduled_gbm(
                h.spot0,
                h.equity_risk_premium,
                h.volatility * scenario.volatility_multiplier,
                DT,
                rates,
                normals,
            )
            record.update(
                {
                    "decision_rates": rates.tolist(),
                    "standard_normals_sha256": array_hash(normals),
                    "market_paths_sha256": array_hash(paths),
                    "market_shape": list(paths.shape),
                }
            )
            banks[scenario.name, seed] = paths, rates
    return banks, records, reasons


def run_monetary_study(config: MonetaryStudyConfig) -> MonetaryStudyResult:
    scenarios = sorted(config.scenarios, key=lambda value: value.name)
    test_seeds = sorted(config.test_seeds)
    training_seeds = sorted(config.training_seeds)
    n_steps = config.economy.n_steps
    maturity = n_steps * DT
    h = config.hedge
    premium = float(
        black_scholes_price(
            MarketSnapshot(
                BusinessDayCalendar().next_business_day(config.economy.start_date),
                h.spot0,
                config.initial_rate,
                h.volatility,
            ),
            EuropeanOption(h.strike, maturity, h.option_type),
        )
    )
    banks, records, reasons = build_feedback_banks(config)
    cells: dict[str, list[dict[str, Any]]] = {scenario.name: [] for scenario in scenarios}
    trained = []
    cards = []
    # Any invalid macro bank invalidates the complete experiment: no seed/scenario filtering.
    if not reasons:
        for training_seed in training_seeds:
            paths = simulate_gbm_paths(
                h.spot0,
                config.initial_rate + h.equity_risk_premium,
                h.volatility,
                maturity,
                n_steps,
                h.n_train_paths,
                SeedHierarchy(training_seed.path_seed).stream("macro-study-training-paths"),
            )
            training = train_deep_hedge(
                paths,
                DT,
                h.strike,
                maturity,
                h.option_type,
                config.initial_rate,
                h.cost_rate,
                premium,
                cvar_alpha=h.cvar_alpha,
                turnover_penalty=h.turnover_penalty,
                n_epochs=h.n_train_epochs,
                batch_size=h.batch_size,
                learning_rate=h.learning_rate,
                seed=training_seed.policy_seed,
            )
            trained.append(
                {
                    "seed": asdict(training_seed),
                    "training_data_sha256": array_hash(paths),
                    "policy_content_hash": policy_content_hash(training.policy),
                    "objective_history": training.objective_history,
                }
            )
            for scenario in scenarios:
                for seed in test_seeds:
                    test_paths, rates = banks[scenario.name, seed]
                    delta = rate_scheduled_delta(
                        test_paths, DT, h.strike, h.volatility, h.option_type, rates
                    )
                    mlp = generate_policy_hedge_ratios(
                        training.policy, test_paths, DT, h.strike, maturity
                    )
                    results = []
                    for targets in (delta, mlp):
                        result = simulate_self_financing_hedge(
                            test_paths,
                            DT,
                            h.strike,
                            h.option_type,
                            config.initial_rate,
                            h.cost_rate * scenario.cost_multiplier,
                            premium,
                            targets,
                            funding_rates=rates[:-1],
                        )
                        results.append(hedge_metrics(result, h.cvar_alpha))
                    cells[scenario.name].append(
                        {
                            "training_seed": asdict(training_seed),
                            "test_seed": seed,
                            "market_paths_sha256": array_hash(test_paths),
                            "delta": results[0],
                            "policy": results[1],
                            "difference": results[0]["cvar"] - results[1]["cvar"],
                        }
                    )
            primary_cells = [
                c
                for c in cells[config.primary_scenario]
                if c["training_seed"] == asdict(training_seed)
            ]
            card = build_deep_hedge_model_card(
                training.policy,
                h.n_train_paths,
                training_seed.path_seed,
                float(np.mean([c["policy"]["cvar"] for c in primary_cells])),
                float(np.mean([c["policy"]["mean_loss"] for c in primary_cells])),
                h.cvar_alpha,
            )
            cards.append(
                replace(
                    card,
                    model_id=f"{card.model_id}-seed-{training_seed.policy_seed}",
                    primary_metrics={
                        "primary_mean_bank_conditional_cvar": float(
                            np.mean([c["policy"]["cvar"] for c in primary_cells])
                        ),
                        "primary_mean_bank_loss": float(
                            np.mean([c["policy"]["mean_loss"] for c in primary_cells])
                        ),
                    },
                    training_data_summary=card.training_data_summary
                    + f" Policy seed={training_seed.policy_seed}; "
                    "named training stream=macro-study-training-paths.",
                    metric_uncertainty_note=(
                        "Bank-averaged conditional CVaR for one retraining; exploratory crossed "
                        "intervals are study-level diagnostics."
                    ),
                    failure_modes=LIMITATIONS,
                )
            )
    confidence = bonferroni_confidence(config.bootstrap_confidence, len(scenarios))
    summaries = []
    for scenario in scenarios:
        uncertainty = None
        verdict = None
        differences = None
        if not reasons:
            matrix = np.array([c["difference"] for c in cells[scenario.name]]).reshape(
                len(training_seeds), len(test_seeds)
            )
            uncertainty = asdict(
                crossed_mean_bootstrap(
                    matrix,
                    SeedHierarchy(config.seed).stream("macro-study-crossed-bootstrap"),
                    n_resamples=config.n_bootstrap_resamples,
                    confidence=confidence,
                )
            )
            ci = uncertainty["crossed"]
            verdict = interval_verdict(ci["ci_low"], ci["ci_high"], config.economic_margin)
            differences = matrix.tolist()
        summaries.append(
            {
                "scenario": asdict(scenario),
                "banks": records[scenario.name],
                "cells": cells[scenario.name],
                "differences": differences,
                "uncertainty": uncertainty,
                "verdict": verdict,
            }
        )
    overall = None if reasons else "inconclusive"
    for direction in ("policy_better", "delta_better"):
        if not reasons and all(s["verdict"] == direction for s in summaries):
            overall = direction
    config_payload = asdict(config)
    config_payload.update(
        {
            "training_seeds": [asdict(seed) for seed in training_seeds],
            "test_seeds": test_seeds,
            "scenarios": [asdict(s) for s in scenarios],
        }
    )
    payload = {
        "schema_version": 1,
        "accounting_convention": "opening-rate-finance-v1",
        "model_convention": "crossed-published-feedback-study-v1",
        "config": config_payload,
        "valid": not reasons,
        "invalid_reasons": reasons,
        "primary_endpoint": ENDPOINT,
        "decision_rule": (
            "All declared scenario crossed-bootstrap intervals must exceed the economic "
            "margin in the same direction; otherwise inconclusive. "
            "Invalid banks suppress inference."
        ),
        "resampling_method": "pigeonhole percentile bootstrap of training rows and shared banks",
        "method_reference": "https://arxiv.org/abs/0712.1111",
        "initial_premium": premium,
        "training": trained,
        "scenario_interval_confidence": confidence,
        "scenarios": summaries,
        "verdict": overall,
        "array_encoding": "row-major float64 little-endian",
        "limitations": LIMITATIONS,
    }
    manifest = RunManifest(
        new_run_id("pmth-monetary-study"),
        now_iso(),
        config.seed,
        config_payload,
        compute_result_hash(payload),
    )
    bundle = build_evidence_bundle(manifest, cards, current_repository_gate_report())
    bundle["monetary_study"] = payload
    return MonetaryStudyResult(not reasons, overall, manifest, bundle)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--recipe", type=Path, help="Complete MonetaryStudyConfig JSON")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    from prometheus.orchestration.replay import read_evidence_bundle

    try:
        config = (
            MonetaryStudyConfig()
            if args.recipe is None
            else MonetaryStudyConfig.from_dict(read_evidence_bundle(args.recipe))
        )
        result = run_monetary_study(config)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        export_evidence_bundle(result.evidence_bundle, args.output)
    except (ValueError, TypeError, OSError) as exc:
        parser.error(str(exc))
    print(
        json.dumps(
            {
                "valid": result.valid,
                "verdict": result.verdict,
                "result_hash": result.manifest.result_hash,
                "evidence_path": str(args.output),
            },
            indent=2,
        )
    )
    return 0 if result.valid else 1


if __name__ == "__main__":
    raise SystemExit(main())
