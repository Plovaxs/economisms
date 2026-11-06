"""Matched current-rate feature ablation on held-out macro/market banks.

Each training row draws independent macro paths and market paths from a
separate declared training scenario. Rate-aware and rate-blind networks
have identical parameter counts, initialization and sampled minibatches.
Test scenarios/banks never determine training data or feature scaling.
"""

from __future__ import annotations

import argparse
import json
import math
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass, field, fields, replace
from pathlib import Path
from typing import Any

import numpy as np
import torch

from prometheus.core.calendar import BusinessDayCalendar
from prometheus.core.seeds import SeedHierarchy
from prometheus.evidence.export import build_evidence_bundle, export_evidence_bundle
from prometheus.evidence.model_card import ModelCard
from prometheus.evidence.repository_status import current_repository_gate_report
from prometheus.experiments.crossed_bootstrap import bonferroni_confidence, crossed_mean_bootstrap
from prometheus.experiments.manifest import RunManifest, compute_result_hash, new_run_id, now_iso
from prometheus.hedging.comparison import DT
from prometheus.hedging.rate_hedge import (
    RateHedgeTrainingResult,
    generate_rate_hedge_ratios,
    rate_policy_hash,
    train_rate_hedge,
)
from prometheus.hedging.rate_paths import rate_scheduled_delta, rate_scheduled_gbm
from prometheus.hedging.simulate import simulate_self_financing_hedge
from prometheus.orchestration.monetary_run import run_monetary_macro_path
from prometheus.orchestration.monetary_study import (
    FeedbackScenario,
    MonetaryStudyConfig,
    array_hash,
    build_feedback_banks,
    hedge_metrics,
)
from prometheus.orchestration.study_run import TrainingSeed
from prometheus.volterra.black_scholes import black_scholes_price
from prometheus.volterra.instruments import EuropeanOption
from prometheus.volterra.market import MarketSnapshot

PRIMARY_CONTRAST = "rate_blind_minus_rate_aware"
CONTRASTS = (PRIMARY_CONTRAST, "delta_minus_rate_aware")
LIMITATIONS = (
    "Synthetic one-firm macro economy and GBM; no empirical or optimal-policy claim.",
    "Current rate is the only extra feature; this is not a full macro-history encoder.",
    "Training samples a finite mixture of independently generated macro paths, not the population.",
    "Cell CVaR conditions on one held-out macro path; mean cell differences are not pooled CVaR.",
    "Crossed percentile intervals have uncalibrated small-seed coverage; no exact guarantee.",
    "Nominal Bonferroni allocation covers all scenario/contrast pairs; no marginal calibration.",
    "Matched architecture, initialization and minibatches do not prove learned-feature usefulness.",
    "Delta uses only current rates and fixed pricing volatility, assuming flat rates to expiry.",
    "Economic and hedge books remain separate and the economy has no asset-wealth feedback.",
    "No signed source identity, dependency lock, scientific review or deployment approval.",
)


@dataclass(frozen=True, slots=True)
class RateStudyConfig(MonetaryStudyConfig):
    training_scenario: FeedbackScenario = field(
        default_factory=lambda: FeedbackScenario("training_baseline")
    )
    training_macro_seeds: tuple[int, ...] = (11, 22, 33)
    rate_feature_scale: float = 0.1
    max_gradient_norm: float = 10.0

    def __post_init__(self) -> None:
        MonetaryStudyConfig.__post_init__(self)
        bonferroni_confidence(self.bootstrap_confidence, len(self.scenarios) * len(CONTRASTS))
        if not isinstance(self.training_scenario, FeedbackScenario):
            raise ValueError("training_scenario must be FeedbackScenario")
        seeds = self.training_macro_seeds
        if (
            not isinstance(seeds, tuple)
            or len(seeds) < 2
            or any(type(seed) is not int or seed < 0 for seed in seeds)
            or len(set(seeds)) != len(seeds)
        ):
            raise ValueError("training_macro_seeds require at least two unique nonnegative seeds")
        if set(seeds) & set(self.test_seeds):
            raise ValueError("training macro labels must not overlap held-out test seeds")
        if self.hedge.n_train_paths < len(seeds):
            raise ValueError("at least one training market path per macro bank is required")
        for value in (self.rate_feature_scale, self.max_gradient_norm):
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(value)
                or value <= 0
            ):
                raise ValueError("feature scale and gradient bound must be finite positive")
        if (
            self.training_scenario.volatility_multiplier != 1
            or self.training_scenario.cost_multiplier != 1
        ):
            raise ValueError(
                "training scenario market/cost multipliers must be one; use hedge settings"
            )
        self.macro_config(seeds[0], self.training_scenario)

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> RateStudyConfig:
        if set(payload) != {item.name for item in fields(cls)}:
            raise ValueError("rate study requires exactly the complete configuration")
        base = MonetaryStudyConfig.from_dict(
            {item.name: payload[item.name] for item in fields(MonetaryStudyConfig)}
        )
        try:
            scenario = payload["training_scenario"]
            if set(scenario) != {item.name for item in fields(FeedbackScenario)}:
                raise ValueError("complete training_scenario configuration is required")
            return cls(
                **{item.name: getattr(base, item.name) for item in fields(MonetaryStudyConfig)},
                training_scenario=FeedbackScenario(**scenario),
                training_macro_seeds=tuple(payload["training_macro_seeds"]),
                rate_feature_scale=payload["rate_feature_scale"],
                max_gradient_norm=payload["max_gradient_norm"],
            )
        except (TypeError, AttributeError) as exc:
            raise ValueError(f"invalid rate-study configuration: {exc}") from exc


def build_rate_training_data(
    config: RateStudyConfig,
    seed: TrainingSeed,
) -> tuple[np.ndarray | None, np.ndarray | None, dict[str, Any], list[str]]:
    h, n_steps = config.hedge, config.economy.n_steps
    bank_seeds = sorted(config.training_macro_seeds)
    quotient, remainder = divmod(h.n_train_paths, len(bank_seeds))
    record: dict[str, Any] = {"training_seed": asdict(seed), "banks": []}
    prices, rate_rows, reasons = [], [], []
    for index, label in enumerate(bank_seeds):
        n_paths = quotient + int(index < remainder)
        streams = SeedHierarchy(seed.path_seed)
        economy_seed = int(
            streams.stream(f"rate-study-training-economy/{label}").integers(0, 2**32)
        )
        cfg = config.macro_config(label, config.training_scenario)
        cfg = replace(cfg, economy=replace(cfg.economy, seed=economy_seed))
        macro = run_monetary_macro_path(cfg)
        bank = {
            "macro_label": label,
            "economy_seed": economy_seed,
            "n_paths": n_paths,
            "macro": asdict(macro),
            "macro_sha256": compute_result_hash(asdict(macro)),
        }
        record["banks"].append(bank)
        if not macro.valid:
            reasons.append(
                f"training {seed.path_seed}/macro {label}: {'; '.join(macro.invalid_reasons)}"
            )
            continue
        rates = np.array([config.initial_rate] + [step.policy.next_rate for step in macro.steps])
        normals = streams.stream(f"rate-study-training-market/{label}").standard_normal(
            (n_paths, n_steps)
        )
        paths = rate_scheduled_gbm(h.spot0, h.equity_risk_premium, h.volatility, DT, rates, normals)
        bank.update(
            {
                "decision_rates": rates.tolist(),
                "normal_sha256": array_hash(normals),
                "market_paths_sha256": array_hash(paths),
            }
        )
        prices.append(paths)
        rate_rows.append(np.broadcast_to(rates, paths.shape))
    if reasons:
        return None, None, record, reasons
    paths, rates = np.concatenate(prices), np.concatenate(rate_rows)
    record.update(
        {
            "market_paths_sha256": array_hash(paths),
            "decision_rates_sha256": array_hash(rates),
            "shape": list(paths.shape),
        }
    )
    return paths, rates, record, []


def _model_card(
    training: RateHedgeTrainingResult,
    arm: str,
    seed: TrainingSeed,
    config: RateStudyConfig,
    primary_cells: list[dict[str, Any]],
) -> ModelCard:
    from datetime import date

    policy = training.policy
    return ModelCard(
        model_id=f"rate-hedge-{arm}-seed-{seed.policy_seed}",
        model_type="4-input MLP; two hidden layers of 32; tanh scalar holding in [-1,1]",
        framework=f"PyTorch {torch.__version__}",
        version="0.1.0",
        license="MIT",
        content_hash=rate_policy_hash(policy),
        intended_use="Synthetic matched rate-feature ablation for single-asset option hedging.",
        prohibited_use="Live trading, real-money decisions or unvalidated model families.",
        input_schema_summary=(
            "float32 (log-moneyness, remaining fraction, previous holding, "
            f"(current_rate - {policy.rate_center}) / {policy.rate_scale}); "
            f"fourth feature {'active' if policy.rate_aware else 'replaced by zero'}; "
            "no future inputs."
        ),
        training_data_summary=(
            f"{config.hedge.n_train_paths} paths from independent training macro banks; "
            f"path seed {seed.path_seed}, policy seed {seed.policy_seed}; "
            f"training scenario {config.training_scenario.name}; identical data for both arms."
        ),
        primary_metrics={
            "primary_mean_bank_conditional_cvar": float(
                np.mean([c[arm]["cvar"] for c in primary_cells])
            ),
            "primary_mean_bank_loss": float(np.mean([c[arm]["mean_loss"] for c in primary_cells])),
        },
        metric_uncertainty_note=(
            "Metrics for one fitted arm; crossed study intervals compare matched rows/shared banks."
        ),
        failure_modes=LIMITATIONS,
        independent_reviewer=None,
        approval_status="NOT REVIEWED",
        created_at=date.today(),
    )


@dataclass(frozen=True, slots=True)
class RateStudyResult:
    valid: bool
    verdict: str | None
    manifest: RunManifest
    evidence_bundle: dict[str, Any]


LossObserver = Callable[[str, TrainingSeed, int, str, np.ndarray], None]


def run_rate_study(
    config: RateStudyConfig, *, loss_observer: LossObserver | None = None
) -> RateStudyResult:
    """Run the matched study, optionally exposing detached terminal-loss samples.

    Observers receive read-only copies after metrics are computed; they
    cannot mutate the simulator's arrays through this interface. This
    supports additional predeclared estimands without repeating training.
    """
    scenarios = sorted(config.scenarios, key=lambda value: value.name)
    rows, test_seeds = sorted(config.training_seeds), sorted(config.test_seeds)
    h, maturity = config.hedge, config.economy.n_steps * DT
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
    training_data = []
    inputs = []
    # Validate every training AND evaluation bank before fitting any arm.
    for seed in rows:
        paths, rates, record, failures = build_rate_training_data(config, seed)
        training_data.append(record)
        reasons.extend(failures)
        inputs.append((paths, rates))
    cells: dict[str, list[dict[str, Any]]] = {s.name: [] for s in scenarios}
    fitted: list[dict[str, Any]] = []
    cards: list[ModelCard] = []
    if not reasons:
        for seed, (paths, rates) in zip(rows, inputs, strict=True):
            assert paths is not None and rates is not None
            trained = {}
            for arm in ("rate_blind", "rate_aware"):
                model = train_rate_hedge(
                    paths,
                    rates,
                    h,
                    dt=DT,
                    initial_premium=premium,
                    rate_aware=arm == "rate_aware",
                    rate_center=config.initial_rate,
                    rate_scale=config.rate_feature_scale,
                    max_gradient_norm=config.max_gradient_norm,
                    seed=seed.policy_seed,
                )
                trained[arm] = model
                fitted.append(
                    {
                        "seed": asdict(seed),
                        "arm": arm,
                        "policy_content_hash": rate_policy_hash(model.policy),
                        "initial_parameter_hash": model.initial_parameter_hash,
                        "minibatches_sha256": model.minibatches_sha256,
                        "diagnostics": [asdict(d) for d in model.diagnostics],
                    }
                )
            if (
                trained["rate_blind"].initial_parameter_hash
                != trained["rate_aware"].initial_parameter_hash
                or trained["rate_blind"].minibatches_sha256
                != trained["rate_aware"].minibatches_sha256
            ):
                raise ValueError("matched feature ablation lost initialization/minibatch pairing")
            for scenario in scenarios:
                for test_seed in test_seeds:
                    test_paths, test_rates = banks[scenario.name, test_seed]
                    targets = {
                        "delta": rate_scheduled_delta(
                            test_paths, DT, h.strike, h.volatility, h.option_type, test_rates
                        )
                    }
                    for arm, model in trained.items():
                        targets[arm] = generate_rate_hedge_ratios(
                            model.policy, test_paths, test_rates, strike=h.strike
                        )
                    cell: dict[str, Any] = {
                        "training_seed": asdict(seed),
                        "test_seed": test_seed,
                        "market_paths_sha256": array_hash(test_paths),
                    }
                    for arm, holdings in targets.items():
                        simulated = simulate_self_financing_hedge(
                            test_paths,
                            DT,
                            h.strike,
                            h.option_type,
                            config.initial_rate,
                            h.cost_rate * scenario.cost_multiplier,
                            premium,
                            holdings,
                            funding_rates=test_rates[:-1],
                        )
                        cell[arm] = hedge_metrics(simulated, h.cvar_alpha)
                        if loss_observer is not None:
                            observed_losses = simulated.terminal_loss.copy()
                            observed_losses.setflags(write=False)
                            loss_observer(scenario.name, seed, test_seed, arm, observed_losses)
                    cell["differences"] = {
                        PRIMARY_CONTRAST: cell["rate_blind"]["cvar"] - cell["rate_aware"]["cvar"],
                        "delta_minus_rate_aware": cell["delta"]["cvar"]
                        - cell["rate_aware"]["cvar"],
                    }
                    cells[scenario.name].append(cell)
            primary = [
                cell
                for cell in cells[config.primary_scenario]
                if cell["training_seed"] == asdict(seed)
            ]
            cards.extend(
                _model_card(model, arm, seed, config, primary) for arm, model in trained.items()
            )
    confidence = bonferroni_confidence(config.bootstrap_confidence, len(scenarios) * len(CONTRASTS))
    summaries: list[dict[str, Any]] = []
    for scenario in scenarios:
        comparisons = {}
        for contrast in CONTRASTS:
            uncertainty, verdict, matrix = None, None, None
            if not reasons:
                values = np.array(
                    [cell["differences"][contrast] for cell in cells[scenario.name]]
                ).reshape(len(rows), len(test_seeds))
                matrix = values.tolist()
                uncertainty = asdict(
                    crossed_mean_bootstrap(
                        values,
                        SeedHierarchy(config.seed).stream("rate-study-crossed-bootstrap"),
                        n_resamples=config.n_bootstrap_resamples,
                        confidence=confidence,
                    )
                )
                ci = uncertainty["crossed"]
                verdict = (
                    "rate_aware_better"
                    if ci["ci_low"] > config.economic_margin
                    else "comparator_better"
                    if ci["ci_high"] < -config.economic_margin
                    else "inconclusive"
                )
            comparisons[contrast] = {
                "differences": matrix,
                "uncertainty": uncertainty,
                "verdict": verdict,
            }
        summaries.append(
            {
                "scenario": asdict(scenario),
                "banks": records[scenario.name],
                "cells": cells[scenario.name],
                "contrasts": comparisons,
            }
        )
    overall = None if reasons else "inconclusive"
    for direction in ("rate_aware_better", "comparator_better"):
        if not reasons and all(
            s["contrasts"][PRIMARY_CONTRAST]["verdict"] == direction for s in summaries
        ):
            overall = direction
    config_payload = asdict(config)
    config_payload.update(
        {
            "training_seeds": [asdict(seed) for seed in rows],
            "test_seeds": test_seeds,
            "scenarios": [asdict(s) for s in scenarios],
            "training_macro_seeds": sorted(config.training_macro_seeds),
        }
    )
    payload = {
        "schema_version": 1,
        "accounting_convention": "opening-rate-finance-v1",
        "model_convention": "causal-rate-feature-ablation-v1",
        "config": config_payload,
        "valid": not reasons,
        "invalid_reasons": reasons,
        "primary_contrast": PRIMARY_CONTRAST,
        "endpoint": "mean_bank_conditional_cvar_difference",
        "contrasts": CONTRASTS,
        "decision_rule": (
            "All scenario primary-contrast intervals must exceed the economic margin "
            "in the same direction; otherwise inconclusive."
        ),
        "scenario_contrast_confidence": confidence,
        "initial_premium": premium,
        "training_data": training_data,
        "training": fitted,
        "scenarios": summaries,
        "verdict": overall,
        "array_encoding": "row-major float64 little-endian",
        "limitations": LIMITATIONS,
    }
    manifest = RunManifest(
        new_run_id("pmth-rate-study"),
        now_iso(),
        config.seed,
        config_payload,
        compute_result_hash(payload),
    )
    bundle = build_evidence_bundle(manifest, cards, current_repository_gate_report())
    bundle["rate_study"] = payload
    return RateStudyResult(not reasons, overall, manifest, bundle)


def main(argv: Sequence[str] | None = None) -> int:
    from prometheus.orchestration.replay import read_evidence_bundle

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--recipe", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        config = (
            RateStudyConfig()
            if args.recipe is None
            else RateStudyConfig.from_dict(read_evidence_bundle(args.recipe))
        )
        run = run_rate_study(config)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        export_evidence_bundle(run.evidence_bundle, args.output)
    except (ValueError, TypeError, OSError) as exc:
        parser.error(str(exc))
    print(
        json.dumps(
            {
                "valid": run.valid,
                "verdict": run.verdict,
                "result_hash": run.manifest.result_hash,
                "evidence_path": str(args.output),
            },
            indent=2,
        )
    )
    return 0 if run.valid else 1


if __name__ == "__main__":
    raise SystemExit(main())
