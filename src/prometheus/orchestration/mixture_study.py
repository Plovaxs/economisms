"""Empirical macro/market-mixture tail risk with paired nested uncertainty.

Reuse the matched rate-feature experiment's training and shared evaluation
banks, retaining terminal losses to estimate a distinct, predeclared risk
functional. A model's macro/market outcomes are pooled before CVaR; fitted
models are never pooled into an ensemble. The finite empirical macro-bank
mixture is not a calibrated unconditional population distribution.
"""

from __future__ import annotations

import argparse
import json
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass, fields
from pathlib import Path
from typing import Any

import numpy as np

from prometheus.core.seeds import SeedHierarchy
from prometheus.evidence.export import build_evidence_bundle, export_evidence_bundle
from prometheus.evidence.model_card import ModelCard
from prometheus.evidence.repository_status import current_repository_gate_report
from prometheus.experiments.crossed_bootstrap import bonferroni_confidence
from prometheus.experiments.manifest import RunManifest, compute_result_hash, new_run_id, now_iso
from prometheus.experiments.mixture_bootstrap import nested_mixture_cvar_bootstrap
from prometheus.orchestration.monetary_study import array_hash
from prometheus.orchestration.rate_study import (
    CONTRASTS,
    PRIMARY_CONTRAST,
    RateStudyConfig,
    run_rate_study,
)
from prometheus.orchestration.study_run import TrainingSeed

ENDPOINT = "mean_retraining_empirical_macro_mixture_cvar_difference"
ARMS = ("delta", "rate_blind", "rate_aware")
LIMITATIONS = (
    "Empirical equal-weight macro-bank mixture, not calibrated unconditional population tail risk.",
    "CVaR pools macro/market outcomes within a fitted policy; it never pools trained policies.",
    "Few macro/training levels make percentile coverage unreliable; no exact guarantee.",
    "Nested resampling uses macro banks and inner markets; finite-cluster calibration is absent.",
    "Single-axis intervals are conditional diagnostics, not additive variance components.",
    "Nominal Bonferroni allocation covers only new mixture scenario/contrast pairs.",
    "Original conditional-risk intervals remain auxiliary and have a separate comparison family.",
    "Matched rate-feature training is synthetic and uncalibrated; no optimal-policy claim.",
    "No empirical macro probabilities, historical data, independent review or deployment approval.",
)


@dataclass(frozen=True, slots=True)
class MixtureStudyConfig(RateStudyConfig):
    n_nested_resamples: int = 1_000

    def __post_init__(self) -> None:
        RateStudyConfig.__post_init__(self)
        if type(self.n_nested_resamples) is not int or self.n_nested_resamples < 1:
            raise ValueError("n_nested_resamples must be a positive integer")

    def rate_config(self) -> RateStudyConfig:
        return RateStudyConfig(
            **{item.name: getattr(self, item.name) for item in fields(RateStudyConfig)}
        )

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> MixtureStudyConfig:
        if set(payload) != {item.name for item in fields(cls)}:
            raise ValueError("mixture study requires exactly the complete configuration")
        base = RateStudyConfig.from_dict(
            {item.name: payload[item.name] for item in fields(RateStudyConfig)}
        )
        return cls(
            **{item.name: getattr(base, item.name) for item in fields(RateStudyConfig)},
            n_nested_resamples=payload["n_nested_resamples"],
        )


@dataclass(frozen=True, slots=True)
class MixtureStudyResult:
    valid: bool
    verdict: str | None
    manifest: RunManifest
    evidence_bundle: dict[str, Any]


def run_mixture_study(config: MixtureStudyConfig) -> MixtureStudyResult:
    samples: dict[tuple[str, int, int, str], np.ndarray] = {}

    def collect(
        scenario: str, training: TrainingSeed, test_seed: int, arm: str, losses: np.ndarray
    ) -> None:
        key = scenario, training.policy_seed, test_seed, arm
        if key in samples:
            raise ValueError("duplicate terminal-loss cell")
        samples[key] = losses

    rate_run = run_rate_study(config.rate_config(), loss_observer=collect)
    source = rate_run.evidence_bundle["rate_study"]
    rows, banks = sorted(config.training_seeds), sorted(config.test_seeds)
    confidence = bonferroni_confidence(
        config.bootstrap_confidence, len(config.scenarios) * len(CONTRASTS)
    )
    summaries = []
    mixture_cards: dict[tuple[int, str], dict[str, float]] = {}
    if rate_run.valid:
        expected = len(config.scenarios) * len(rows) * len(banks) * len(ARMS)
        if len(samples) != expected:
            raise ValueError("terminal-loss collection is incomplete")
        for scenario in source["scenarios"]:
            name = scenario["scenario"]["name"]
            cubes = {
                arm: np.stack(
                    [
                        np.stack([samples[name, row.policy_seed, bank, arm] for bank in banks])
                        for row in rows
                    ]
                )
                for arm in ARMS
            }
            # Cross-check the detached losses against the original cell fingerprints.
            for cell in scenario["cells"]:
                for arm in ARMS:
                    key = name, cell["training_seed"]["policy_seed"], cell["test_seed"], arm
                    if array_hash(samples[key]) != cell[arm]["terminal_loss_sha256"]:
                        raise ValueError("terminal-loss fingerprint differs from conditional cell")
            comparisons = {}
            for contrast, comparator in (
                (PRIMARY_CONTRAST, "rate_blind"),
                ("delta_minus_rate_aware", "delta"),
            ):
                uncertainty = nested_mixture_cvar_bootstrap(
                    cubes[comparator],
                    cubes["rate_aware"],
                    SeedHierarchy(config.seed).stream("macro-mixture-nested-bootstrap"),
                    cvar_alpha=config.hedge.cvar_alpha,
                    n_resamples=config.n_nested_resamples,
                    confidence=confidence,
                )
                ci = uncertainty.nested
                verdict = (
                    "rate_aware_better"
                    if ci.ci_low > config.economic_margin
                    else "comparator_better"
                    if ci.ci_high < -config.economic_margin
                    else "inconclusive"
                )
                comparisons[contrast] = {"uncertainty": asdict(uncertainty), "verdict": verdict}
                if name == config.primary_scenario:
                    for index, row in enumerate(rows):
                        comparator_cvar = uncertainty.point.comparator_cvars[index]
                        mixture_cards[row.policy_seed, comparator] = {
                            "primary_empirical_macro_mixture_cvar": comparator_cvar
                        }
                        mixture_cards[row.policy_seed, "rate_aware"] = {
                            "primary_empirical_macro_mixture_cvar": uncertainty.point.policy_cvars[
                                index
                            ]
                        }
            summaries.append(
                {
                    "scenario": scenario["scenario"],
                    "loss_cube_axes": ["training_seed", "macro_bank", "conditional_market_path"],
                    "loss_cube_shape": list(cubes["delta"].shape),
                    "losses": {arm: cube.tolist() for arm, cube in cubes.items()},
                    "losses_sha256": {arm: array_hash(cube) for arm, cube in cubes.items()},
                    "contrasts": comparisons,
                }
            )
    overall = None if not rate_run.valid else "inconclusive"
    for direction in ("rate_aware_better", "comparator_better"):
        if rate_run.valid and all(
            s["contrasts"][PRIMARY_CONTRAST]["verdict"] == direction for s in summaries
        ):
            overall = direction
    config_payload = dict(source["config"])
    config_payload["n_nested_resamples"] = config.n_nested_resamples
    payload = {
        "schema_version": 1,
        "accounting_convention": "opening-rate-finance-v1",
        "model_convention": "empirical-macro-mixture-cvar-v1",
        "config": config_payload,
        "valid": rate_run.valid,
        "invalid_reasons": source["invalid_reasons"],
        "primary_endpoint": ENDPOINT,
        "primary_contrast": PRIMARY_CONTRAST,
        "comparison_family": "mixture endpoint: all declared scenario/contrast pairs",
        "scenario_contrast_confidence": confidence,
        "decision_rule": (
            "All primary-contrast nested intervals must exceed the economic margin "
            "in the same direction; otherwise inconclusive."
        ),
        "bank_weighting": "equal probability per macro bank and equal conditional path weights",
        "resampling": "training rows x macro banks x paired markets within each bank occurrence",
        "conditional_result_hash": rate_run.manifest.result_hash,
        "conditional_study": source,
        "scenarios": summaries,
        "verdict": overall,
        "array_encoding": "row-major float64 little-endian",
        "limitations": LIMITATIONS,
    }
    manifest = RunManifest(
        new_run_id("pmth-mixture-study"),
        now_iso(),
        config.seed,
        config_payload,
        compute_result_hash(payload),
    )
    cards = []
    for fitted, original in zip(
        source["training"], rate_run.evidence_bundle["model_cards"], strict=True
    ):
        values = dict(original)
        values["primary_metrics"] = (
            dict(original["primary_metrics"])
            | mixture_cards[fitted["seed"]["policy_seed"], fitted["arm"]]
        )
        values["metric_uncertainty_note"] = (
            "One fitted model's empirical macro-mixture CVaR; nested study intervals "
            "resample shared rows/banks/markets. Original conditional metrics are auxiliary."
        )
        values["failure_modes"] = tuple(values["failure_modes"]) + LIMITATIONS
        cards.append(ModelCard(**values))
    bundle = build_evidence_bundle(manifest, cards, current_repository_gate_report())
    bundle["mixture_study"] = payload
    return MixtureStudyResult(rate_run.valid, overall, manifest, bundle)


def main(argv: Sequence[str] | None = None) -> int:
    from prometheus.orchestration.replay import read_evidence_bundle

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--recipe", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        config = (
            MixtureStudyConfig()
            if args.recipe is None
            else MixtureStudyConfig.from_dict(read_evidence_bundle(args.recipe))
        )
        run = run_mixture_study(config)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        export_evidence_bundle(run.evidence_bundle, args.output)
    except (ValueError, TypeError, OSError, ArithmeticError) as exc:
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
