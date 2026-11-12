"""End-to-end NSD demonstration: trains the neural SDE (`neural_sde`
package) on the real, already-committed
`data_cache/kaggle_us_macro_monthly.csv` snapshot (no live network call,
same reliability property as `recessionnet_kaggle_run.py`), then
produces a benchmark report (NSD-07), a multi-seed/multi-solver
sensitivity report (NSD-10), a COVID out-of-distribution report
(NSD-11), and a model card (NSD-13), printed as JSON.
"""

from __future__ import annotations

import argparse
import json
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass, fields
from pathlib import Path
from typing import Any

import numpy as np
import torch

from prometheus.data_ingestion.kaggle_macro import load_kaggle_us_macro_observations
from prometheus.evidence.contracts import CONVENTIONS
from prometheus.evidence.export import build_evidence_bundle
from prometheus.evidence.repository_status import current_repository_gate_report
from prometheus.experiments.manifest import (
    RunManifest,
    compute_result_hash,
    new_run_id,
    now_iso,
)
from prometheus.neural_sde.benchmark import benchmark_report, multi_seed_multi_solver_sensitivity
from prometheus.neural_sde.dataset import (
    build_point_in_time_store,
    build_transition_dataset,
    chronological_split,
    fit_scaler,
)
from prometheus.neural_sde.design import DEFAULT_DESIGN_SPEC, design_record_text
from prometheus.neural_sde.ood import evaluate_ood_without_retuning, split_pre_and_during_covid
from prometheus.neural_sde.registry import model_card_from_trained_model
from prometheus.neural_sde.training import train_neural_sde

DEFAULT_CSV_PATH = (
    Path(__file__).resolve().parents[3] / "data_cache" / "kaggle_us_macro_monthly.csv"
)


@dataclass(frozen=True, slots=True)
class NeuralSdeRunConfig:
    """Deliberately does not expose `csv_path` as a field -- unlike
    `qmacro`/`recessionnet_kaggle`/`inflationcast`, which each load a
    fixed, named real snapshot, this config would otherwise let a job
    submission point this subsystem's loader at an arbitrary
    filesystem path from inside a sandboxed worker subprocess.
    `run_neural_sde_job` below always uses the committed
    `DEFAULT_CSV_PATH`, the same real, already-committed Kaggle macro
    snapshot `run()`'s own CLI defaults to."""

    seed: int = 0
    max_epochs: int = 300
    patience: int = 20

    def __post_init__(self) -> None:
        if self.seed < 0:
            raise ValueError("seed must be non-negative")
        if self.max_epochs < 1:
            raise ValueError("max_epochs must be a positive integer")
        if self.patience < 1:
            raise ValueError("patience must be a positive integer")

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> NeuralSdeRunConfig:
        if set(payload) != {item.name for item in fields(cls)}:
            raise ValueError("neural_sde recipe requires exactly the complete configuration fields")
        try:
            return cls(**dict(payload))
        except TypeError as exc:
            raise ValueError(f"invalid neural_sde recipe: {exc}") from exc


@dataclass(frozen=True, slots=True)
class NeuralSdeJobResult:
    run_result: dict[str, Any]
    manifest: RunManifest
    evidence_bundle: dict[str, Any]


def run_neural_sde_job(config: NeuralSdeRunConfig) -> NeuralSdeJobResult:
    """The job-kind adapter: calls `run()` unchanged against the fixed
    committed CSV, wrapped with a `RunManifest`/evidence-bundle
    envelope. `run()`'s own dict is already fully JSON-shaped (see its
    `model_card`/`ood_report`/`sensitivity_report` keys) -- this only
    adds the `schema_version`/`accounting_convention`/`config` fields
    every registered recipe kind's payload needs."""
    run_result = run(
        csv_path=DEFAULT_CSV_PATH,
        seed=config.seed,
        max_epochs=config.max_epochs,
        patience=config.patience,
    )
    payload = dict(run_result)
    payload["schema_version"] = 1
    payload["accounting_convention"] = CONVENTIONS["neural_sde"]
    payload["config"] = asdict(config)
    manifest = RunManifest(
        new_run_id("pmth-neural-sde"),
        now_iso(),
        config.seed,
        asdict(config),
        compute_result_hash(payload),
    )
    bundle = build_evidence_bundle(manifest, [], current_repository_gate_report())
    bundle["neural_sde"] = payload
    return NeuralSdeJobResult(run_result=run_result, manifest=manifest, evidence_bundle=bundle)


def run(
    *,
    csv_path: Path,
    seed: int = 0,
    max_epochs: int = 300,
    patience: int = 20,
) -> dict[str, Any]:
    observations = load_kaggle_us_macro_observations(csv_path)
    store = build_point_in_time_store(observations)
    months = sorted({o.observation_at for o in observations})

    all_examples = build_transition_dataset(store, DEFAULT_DESIGN_SPEC, months)
    pre_covid, covid_window = split_pre_and_during_covid(all_examples)

    train_examples, validation_examples = chronological_split(pre_covid, train_fraction=0.8)

    state_scaler = fit_scaler(np.array([e.state for e in train_examples]))
    regime_scaler = fit_scaler(np.array([e.regime for e in train_examples]))

    trained = train_neural_sde(
        train_examples,
        validation_examples,
        state_scaler,
        regime_scaler,
        seed=seed,
        max_epochs=max_epochs,
        patience=patience,
    )

    report = benchmark_report(
        validation_examples, train_examples, trained.model, state_scaler, regime_scaler
    )
    ood = evaluate_ood_without_retuning(trained, validation_examples, covid_window, train_examples)

    x0 = torch.tensor([list(train_examples[-1].state)], dtype=torch.float32)
    regime_path = torch.tensor(
        [list(e.regime) for e in validation_examples[:12]], dtype=torch.float32
    )
    sensitivity = multi_seed_multi_solver_sensitivity(trained.model, x0, regime_path)

    card = model_card_from_trained_model(trained, train_examples, DEFAULT_DESIGN_SPEC)

    return {
        "design_record": design_record_text(DEFAULT_DESIGN_SPEC),
        "n_months": len(months),
        "n_train_examples": len(train_examples),
        "n_validation_examples": len(validation_examples),
        "n_covid_examples": len(covid_window),
        "selected_epoch": trained.selected_epoch,
        "best_validation_nll": trained.best_validation_nll,
        "n_parameters": trained.n_parameters,
        "benchmark_report": {
            "candidate_names": list(report.candidate_names),
            "log_score": report.log_score,
            "crps": report.crps,
        },
        "ood_report": asdict(ood),
        "sensitivity_report": asdict(sensitivity),
        "model_card": {
            **asdict(card),
            "training_range_start": card.training_range_start.isoformat(),
            "training_range_end": card.training_range_end.isoformat(),
        },
    }


def main(argv: Sequence[str] | None = None, *, csv_path: Path | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--max-epochs", type=int, default=300)
    parser.add_argument("--patience", type=int, default=20)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)

    result = run(
        csv_path=csv_path if csv_path is not None else DEFAULT_CSV_PATH,
        seed=args.seed,
        max_epochs=args.max_epochs,
        patience=args.patience,
    )
    text = json.dumps(result, indent=2, default=str)
    if args.output:
        args.output.write_text(text)
    else:
        print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
