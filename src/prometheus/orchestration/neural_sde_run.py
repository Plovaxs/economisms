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
from collections.abc import Sequence
from dataclasses import asdict
from pathlib import Path
from typing import Any

import numpy as np
import torch

from prometheus.data_ingestion.kaggle_macro import load_kaggle_us_macro_observations
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
