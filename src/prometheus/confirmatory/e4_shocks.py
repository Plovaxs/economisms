"""E4: does the neural SDE degrade less than a constant GBM under a shock? (H2, Finding 5)

A pre-specified analysis on RE-USED data, not a confirmatory test: every shock in the committed
macro grid (1981-12 to 2023-01) has been read by code, 2001 and 2008 as training data of the
model that Finding 5 reports, and COVID's window also decided `patience=20` (Finding 5's
follow-up). Nothing here can be "untouched"; what it adds is the audit's request to report a
shock by shock result instead of one shock.

For each pre-declared event the model is trained ONLY on transitions decided strictly before the
event (80/20 chronological split, early stopping on the validation part), a constant-parameter GBM
is fitted on the same training part, and both are scored without retuning on the event window with
`neural_sde.ood.evaluate_ood_without_retuning`. The statistic is Finding 5's: degradation =
event-window log score minus in-distribution (validation) log score, lower is better, and
`advantage = baseline degradation - neural degradation` (positive favours the neural SDE).

No inference across events: three events cannot support an interval, and the seeds only measure
training noise. Results are reported event by event and are never pooled into one score. COVID
is flagged as selection-contaminated and reported apart.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path
from typing import Any

import numpy as np

from prometheus.data_ingestion.kaggle_macro import load_kaggle_us_macro_observations
from prometheus.neural_sde.dataset import (
    TransitionExample,
    build_point_in_time_store,
    build_transition_dataset,
    chronological_split,
    fit_scaler,
)
from prometheus.neural_sde.design import DEFAULT_DESIGN_SPEC
from prometheus.neural_sde.ood import (
    COVID_OOD_WINDOW_END,
    COVID_OOD_WINDOW_START,
    evaluate_ood_without_retuning,
)
from prometheus.neural_sde.training import train_neural_sde
from prometheus.orchestration.neural_sde_run import DEFAULT_CSV_PATH

PATIENCE = 20
MAX_EPOCHS = 300
LEGACY_LEARNING_RATE = 0.01
HIDDEN_SIZE = 16


@dataclass(frozen=True, slots=True)
class NeuralSdeRecipe:
    learning_rate: float
    hidden_size: int
    max_epochs: int
    patience: int


LEGACY_RECIPE = NeuralSdeRecipe(LEGACY_LEARNING_RATE, HIDDEN_SIZE, MAX_EPOCHS, PATIENCE)
"""The recipe behind Finding 5 and the first exploratory dry run (seeds 0-9)."""
FROZEN_RECIPE = NeuralSdeRecipe(0.003, 16, 300, 50)
"""The recipe E4 freezes: chosen by `orchestration.neural_sde_tuning_study` (PR-219) on transitions
decided before 2001-03-31, so no event window selected it."""
E4_SEEDS = tuple(range(20_000, 20_010))


@dataclass(frozen=True, slots=True)
class Event:
    name: str
    start: date
    end: date
    """The window of decision times scored (inclusive month ends)."""
    contaminated: bool
    note: str


EVENTS: tuple[Event, ...] = (
    Event(
        "dotcom_2001",
        date(2001, 3, 31),
        date(2001, 11, 30),
        False,
        "NBER peak 2001-03 to trough 2001-11; was inside the training data of Finding 5's model",
    ),
    Event(
        "financial_crisis_2008",
        date(2007, 12, 31),
        date(2009, 6, 30),
        False,
        "NBER peak 2007-12 to trough 2009-06; was inside the training data of Finding 5's model",
    ),
    Event(
        "covid_2020",
        COVID_OOD_WINDOW_START,
        COVID_OOD_WINDOW_END,
        True,
        "Finding 5's own window; patience=20 was kept after seeing it (selection-contaminated)",
    ),
)


@dataclass(frozen=True, slots=True)
class EventSeedResult:
    event: str
    seed: int
    n_train: int
    n_validation: int
    n_event: int
    neural_degradation: float
    baseline_degradation: float
    advantage: float
    """`baseline_degradation - neural_degradation`: positive means the neural SDE degraded less."""


def _examples(csv_path: Path) -> list[TransitionExample]:
    observations = load_kaggle_us_macro_observations(csv_path)
    store = build_point_in_time_store(observations)
    months = sorted({o.observation_at for o in observations})
    return build_transition_dataset(store, DEFAULT_DESIGN_SPEC, months)


def split_for_event(
    examples: list[TransitionExample], event: Event
) -> tuple[list[TransitionExample], list[TransitionExample]]:
    """Everything decided strictly BEFORE the event (to train and validate on), and its window.
    Transitions decided after the window belong to neither."""
    before = [e for e in examples if e.decision_time < event.start]
    window = [e for e in examples if event.start <= e.decision_time <= event.end]
    return before, window


def run_event_seed(
    examples: list[TransitionExample],
    event: Event,
    seed: int,
    *,
    recipe: NeuralSdeRecipe = FROZEN_RECIPE,
) -> EventSeedResult:
    before, window = split_for_event(examples, event)
    train, validation = chronological_split(before, train_fraction=0.8)
    state_scaler = fit_scaler(np.array([e.state for e in train]))
    regime_scaler = fit_scaler(np.array([e.regime for e in train]))
    trained = train_neural_sde(
        train, validation, state_scaler, regime_scaler,
        seed=seed, max_epochs=recipe.max_epochs, patience=recipe.patience,
        learning_rate=recipe.learning_rate, hidden_size=recipe.hidden_size,
    )  # fmt: skip
    report = evaluate_ood_without_retuning(trained, validation, window, train)
    return EventSeedResult(
        event=event.name,
        seed=seed,
        n_train=len(train),
        n_validation=len(validation),
        n_event=len(window),
        neural_degradation=report.neural_degradation,
        baseline_degradation=report.baseline_degradation,
        advantage=report.baseline_degradation - report.neural_degradation,
    )


def summarise(results: Sequence[EventSeedResult], event: Event) -> dict[str, Any]:
    advantage = np.array([r.advantage for r in results])
    return {
        "event": event.name,
        "window": [event.start.isoformat(), event.end.isoformat()],
        "selection_contaminated": event.contaminated,
        "note": event.note,
        "n_seeds": len(results),
        "n_train": results[0].n_train,
        "n_event_transitions": results[0].n_event,
        "neural_degradation_median": float(np.median([r.neural_degradation for r in results])),
        "baseline_degradation_median": float(np.median([r.baseline_degradation for r in results])),
        "advantage_median": float(np.median(advantage)),
        "advantage_min": float(advantage.min()),
        "advantage_max": float(advantage.max()),
        "seeds_where_neural_degraded_less": int(np.sum(advantage > 0)),
        "per_seed": [asdict(r) for r in results],
    }


def run_e4(
    seeds: Sequence[int] = E4_SEEDS,
    *,
    csv_path: Path = DEFAULT_CSV_PATH,
    events: Sequence[Event] = EVENTS,
    recipe: NeuralSdeRecipe = FROZEN_RECIPE,
) -> dict[str, Any]:
    """Every event and seed, reported event by event: no pooled score, no interval across events."""
    examples = _examples(csv_path)
    return {
        "endpoint": "E4",
        "label": "re-used data; pre-specified; estimation only; never pooled across events",
        "patience": recipe.patience,
        "recipe": asdict(recipe),
        "events": [
            summarise([run_event_seed(examples, event, s, recipe=recipe) for s in seeds], event)
            for event in events
        ],
    }
