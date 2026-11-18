"""FP-13: VOLTERRA-GEN, a conditional economic scenario generator.

The blueprint's own wording gives real latitude here: "Add a small
conditional diffusion or conditional normalizing-flow model for joint
macro-market scenarios... a conditional probabilistic generator is an
acceptable working alternative to full diffusion if its evaluation is
stronger." This module builds that acceptable alternative: a small
torch MLP mapping a real joint macro-market state (GDP growth,
unemployment-claims growth, the Fed funds rate, M2 growth, and the
NASDAQ's own trailing return -- all five from the same committed real
Kaggle snapshot `recessionnet`/`inflationcast` already use,
`data_cache/kaggle_us_macro_monthly.csv`) at month t to a CALIBRATED
Gaussian forecast `(mean, log_var)` of the NASDAQ's realized return at
month t+1 -- a genuine conditional probabilistic generator, trained by
Gaussian NLL on real historical (state, realized-next-return) pairs,
not a closed-form classical model.

This is purely additive alongside every existing `volterra/` pricer
(Black-Scholes, Heston, Merton, barrier, Asian, American) -- none of
them are modified. It reuses `inflationcast.models.gaussian_nll` and
`inflationcast.evaluation.gaussian_interval_coverage_test` UNCHANGED
rather than reimplementing either.

Every sampled scenario is wrapped in `GeneratedScenario`, which cannot
be constructed except as an explicitly synthetic, explicitly labeled
object (`is_synthetic` has no default and is validated to be exactly
`True`; `source` is validated to equal `"volterra_gen"`) -- the
blueprint's Tier-C "explicit synthetic-data labels" requirement, and a
different, clearly distinguishable type from any of this project's
real-market-data-derived dataclasses.

"Diagnosed" (the other half of FP-13's acceptance wording, "generated
scenarios are labeled AND diagnosed") is satisfied by two REAL,
numbers-not-claims checks on the held-out test period, reported
honestly either way:

1. `gaussian_interval_coverage_test` on the model's own test-period
   (mean, log_var) forecasts -- does its claimed uncertainty actually
   cover the realized outcomes at the nominal rate? A miscalibration
   finding here is a valid, reportable outcome, the same standard
   `InflationGRU`'s own badly-miscalibrated real result was held to.
2. A direct NLL comparison against an UNCONDITIONAL classical Gaussian
   baseline (GBM's own constant-drift/constant-volatility assumption,
   fit once from the train-period targets alone) on the same held-out
   test period -- whichever wins is reported as-is.
"""

from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import numpy as np
import torch
from torch import nn

from prometheus.data_ingestion.kaggle_macro import (
    KAGGLE_SERIES_IDS,
    load_kaggle_us_macro_observations,
)
from prometheus.econosim.pit import MacroObservation, PointInTimeStore, require_eligible
from prometheus.inflationcast.evaluation import CalibrationResult, gaussian_interval_coverage_test
from prometheus.inflationcast.models import gaussian_nll

NASDAQ_SERIES_ID = "KAGGLE_NASDAQ_YOY"
CONDITIONING_SERIES_IDS: tuple[str, ...] = KAGGLE_SERIES_IDS
"""(GDP_YOY, CLAIMS_YOY, FEDFUNDS, M2_YOY, NASDAQ_YOY) at month t -- the
real joint "macro-market state" the generator conditions on. NASDAQ_YOY
is included in the conditioning set (as month t's OWN realized value,
not month t+1's) because the blueprint's own framing is "joint
macro-market scenarios," not macro-only; this is the market's own
trailing momentum signal, a standard real predictor, not look-ahead --
the target is strictly the NEXT month's value."""


class SyntheticLabelError(ValueError):
    """Raised when a `GeneratedScenario` is constructed without (or
    with a falsified) synthetic-data label."""


@dataclass(frozen=True, slots=True)
class GeneratedScenario:
    """A single sampled synthetic scenario. `is_synthetic` has no
    default -- every call site must say so explicitly -- and is
    validated to be exactly `True`: this type exists only to produce
    labeled synthetic output, never real-data-passing-as-real."""

    conditioning_month: date
    conditioning_features: tuple[float, ...]
    generated_next_month_return: float
    is_synthetic: bool
    model_version: str = "volterra-gen-mlp-v1"
    source: str = "volterra_gen"

    def __post_init__(self) -> None:
        if self.is_synthetic is not True:
            raise SyntheticLabelError(
                "GeneratedScenario must be explicitly labeled is_synthetic=True; "
                f"got {self.is_synthetic!r}"
            )
        if self.source != "volterra_gen":
            raise SyntheticLabelError(
                f"GeneratedScenario.source must be 'volterra_gen', got {self.source!r}"
            )
        if len(self.conditioning_features) != len(CONDITIONING_SERIES_IDS):
            raise ValueError(
                f"conditioning_features must have {len(CONDITIONING_SERIES_IDS)} entries, "
                f"got {len(self.conditioning_features)}"
            )


@dataclass(frozen=True, slots=True)
class VolterraGenExample:
    decision_month: date
    features: np.ndarray
    """Shape (5,): the real joint macro-market state at `decision_month`."""
    target: float
    """The REAL, realized NASDAQ_YOY one month after `decision_month` --
    the training label, never a model input."""

    def __post_init__(self) -> None:
        if self.features.shape != (len(CONDITIONING_SERIES_IDS),):
            raise ValueError(f"features must have shape ({len(CONDITIONING_SERIES_IDS)},)")


def _month_end(year: int, month: int) -> date:
    return date(year, month, calendar.monthrange(year, month)[1])


def _add_month(year: int, month: int) -> tuple[int, int]:
    return (year + 1, 1) if month == 12 else (year, month + 1)


def load_observations_into_store(path: Path) -> tuple[PointInTimeStore, list[date]]:
    """Loads the real committed Kaggle snapshot into a `PointInTimeStore`
    and returns the sorted, de-duplicated list of real calendar months it
    covers -- the same `econosim.pit` discipline every other forecasting
    task in this repository uses, even though (as `kaggle_macro`'s own
    docstring already discloses) these particular series carry no extra
    publication lag (`published_at == observation_at`), so no masking
    behavior is actually exercised here, only the leakage-safe access
    pattern itself."""
    observations: list[MacroObservation] = load_kaggle_us_macro_observations(path)
    store = PointInTimeStore()
    for obs in observations:
        store.record(obs)
    months = sorted({obs.observation_at for obs in observations})
    return store, months


def build_volterra_gen_dataset(
    store: PointInTimeStore, months: list[date]
) -> tuple[VolterraGenExample, ...]:
    """One example per consecutive real (month t, month t+1) pair with
    both sides present in `months`. `decision_month` is month t's own
    last day; conditioning features are required eligible as of that
    date (fails loudly via `require_eligible`/`FutureDataError` if not);
    the label is month t+1's real, realized NASDAQ_YOY, never read back
    into `features`."""
    month_set = set(months)
    examples: list[VolterraGenExample] = []
    for decision_month in sorted(month_set):
        next_year, next_month = _add_month(decision_month.year, decision_month.month)
        next_month_date = _month_end(next_year, next_month)
        if next_month_date not in month_set:
            continue
        values = [
            require_eligible(store, series_id, decision_month, decision_month).value
            for series_id in CONDITIONING_SERIES_IDS
        ]
        target_obs = require_eligible(store, NASDAQ_SERIES_ID, next_month_date, next_month_date)
        examples.append(
            VolterraGenExample(
                decision_month=decision_month,
                features=np.array(values, dtype=np.float64),
                target=target_obs.value,
            )
        )
    return tuple(examples)


_ExampleSplit = tuple[
    tuple[VolterraGenExample, ...], tuple[VolterraGenExample, ...], tuple[VolterraGenExample, ...]
]


def chronological_split(
    examples: tuple[VolterraGenExample, ...], validation_start: date, test_start: date
) -> _ExampleSplit:
    """Strict chronological train / validation / test split (train <
    validation_start <= validation < test_start <= test). Fails loudly
    if any split would be empty."""
    if not validation_start < test_start:
        raise ValueError("validation_start must be strictly before test_start")
    train = tuple(e for e in examples if e.decision_month < validation_start)
    validation = tuple(e for e in examples if validation_start <= e.decision_month < test_start)
    test = tuple(e for e in examples if e.decision_month >= test_start)
    if not train or not validation or not test:
        raise ValueError("split dates must leave all three of train/validation/test non-empty")
    return train, validation, test


class ConditionalScenarioGenerator(nn.Module):
    """A small conditional probabilistic generator: a 2-layer MLP over
    the real joint macro-market state, producing (mean, log_var) of the
    next month's NASDAQ_YOY -- the "acceptable working alternative" to a
    full conditional diffusion/normalizing-flow model the blueprint's
    own final-project wording explicitly permits."""

    def __init__(
        self, n_features: int = len(CONDITIONING_SERIES_IDS), hidden_size: int = 16
    ) -> None:
        super().__init__()
        self.net = nn.Sequential(
            nn.Linear(n_features, hidden_size),
            nn.Tanh(),
            nn.Linear(hidden_size, hidden_size),
            nn.Tanh(),
            nn.Linear(hidden_size, 2),
        )

    def forward(self, x: torch.Tensor) -> tuple[torch.Tensor, torch.Tensor]:
        out = self.net(x)
        mean: torch.Tensor = out[:, 0]
        log_var: torch.Tensor = out[:, 1]
        return mean, log_var

    def count_parameters(self) -> int:
        return sum(p.numel() for p in self.parameters() if p.requires_grad)


@dataclass(frozen=True, slots=True)
class EpochLogEntry:
    epoch: int
    train_nll: float
    validation_nll: float


@dataclass(frozen=True, slots=True)
class TrainedScenarioGenerator:
    model: ConditionalScenarioGenerator
    epoch_log: tuple[EpochLogEntry, ...]
    best_epoch: int


def _features_array(examples: tuple[VolterraGenExample, ...]) -> np.ndarray:
    return np.stack([e.features for e in examples])


def _targets_array(examples: tuple[VolterraGenExample, ...]) -> np.ndarray:
    return np.array([e.target for e in examples], dtype=np.float64)


def train_scenario_generator(
    train: tuple[VolterraGenExample, ...],
    validation: tuple[VolterraGenExample, ...],
    *,
    seed: int = 0,
    max_epochs: int = 400,
    patience: int = 30,
    learning_rate: float = 0.01,
) -> TrainedScenarioGenerator:
    """Trains `ConditionalScenarioGenerator` by Gaussian NLL
    (`inflationcast.models.gaussian_nll`, reused unchanged) with
    early stopping selected on `validation` alone, never `test`."""
    torch.manual_seed(seed)
    model = ConditionalScenarioGenerator()
    optimizer = torch.optim.Adam(model.parameters(), lr=learning_rate)

    train_x = torch.tensor(_features_array(train), dtype=torch.float32)
    train_y = torch.tensor(_targets_array(train), dtype=torch.float32)
    val_x = torch.tensor(_features_array(validation), dtype=torch.float32)
    val_y = torch.tensor(_targets_array(validation), dtype=torch.float32)

    best_state: dict[str, torch.Tensor] | None = None
    best_val_nll = float("inf")
    best_epoch = 0
    epochs_without_improvement = 0
    log: list[EpochLogEntry] = []

    for epoch in range(1, max_epochs + 1):
        model.train()
        optimizer.zero_grad()
        mean, log_var = model(train_x)
        train_nll = gaussian_nll(mean, log_var, train_y)
        train_nll.backward()  # type: ignore[no-untyped-call]
        optimizer.step()

        model.eval()
        with torch.no_grad():
            val_mean, val_log_var = model(val_x)
            val_nll = float(gaussian_nll(val_mean, val_log_var, val_y).item())

        log.append(
            EpochLogEntry(
                epoch=epoch, train_nll=float(train_nll.item()), validation_nll=val_nll
            )
        )

        if val_nll < best_val_nll:
            best_val_nll = val_nll
            best_epoch = epoch
            best_state = {k: v.clone() for k, v in model.state_dict().items()}
            epochs_without_improvement = 0
        else:
            epochs_without_improvement += 1
            if epochs_without_improvement >= patience:
                break

    assert best_state is not None  # noqa: S101
    model.load_state_dict(best_state)
    return TrainedScenarioGenerator(model=model, epoch_log=tuple(log), best_epoch=best_epoch)


def predict(
    model: ConditionalScenarioGenerator, examples: tuple[VolterraGenExample, ...]
) -> tuple[np.ndarray, np.ndarray]:
    """Returns (mean, log_var) arrays over `examples`, in order."""
    model.eval()
    x = torch.tensor(_features_array(examples), dtype=torch.float32)
    with torch.no_grad():
        mean, log_var = model(x)
    return mean.numpy(), log_var.numpy()


def sample_scenarios(
    model: ConditionalScenarioGenerator,
    examples: tuple[VolterraGenExample, ...],
    *,
    n_samples_per_example: int,
    seed: int,
) -> tuple[GeneratedScenario, ...]:
    """Draws `n_samples_per_example` synthetic next-month-return samples
    per held-out example from the model's own predicted N(mean,
    exp(log_var)), each wrapped as an explicitly-labeled
    `GeneratedScenario`."""
    if n_samples_per_example < 1:
        raise ValueError("n_samples_per_example must be a positive integer")
    mean, log_var = predict(model, examples)
    sigma = np.exp(0.5 * log_var)
    rng = np.random.default_rng(seed)
    scenarios: list[GeneratedScenario] = []
    for i, example in enumerate(examples):
        draws = rng.normal(loc=mean[i], scale=sigma[i], size=n_samples_per_example)
        for draw in draws:
            scenarios.append(
                GeneratedScenario(
                    conditioning_month=example.decision_month,
                    conditioning_features=tuple(float(v) for v in example.features),
                    generated_next_month_return=float(draw),
                    is_synthetic=True,
                )
            )
    return tuple(scenarios)


@dataclass(frozen=True, slots=True)
class ClassicalBaselineResult:
    """The classical, macro-blind alternative: GBM's own constant-drift,
    constant-volatility assumption, fit ONCE from the train-period
    targets alone (never validation/test), then applied uniformly to
    every held-out observation -- the honest "no conditioning at all"
    comparison point for the conditional generator above."""

    mu: float
    sigma: float
    test_nll: float


def fit_classical_baseline(
    train: tuple[VolterraGenExample, ...], test: tuple[VolterraGenExample, ...]
) -> ClassicalBaselineResult:
    train_targets = _targets_array(train)
    mu = float(np.mean(train_targets))
    sigma = float(np.std(train_targets, ddof=1))
    if sigma <= 0:
        raise ValueError(
            "train targets have zero variance; cannot fit a classical Gaussian baseline"
        )
    test_targets = _targets_array(test)
    mean_t = torch.full((len(test_targets),), mu, dtype=torch.float32)
    log_var_t = torch.full((len(test_targets),), float(np.log(sigma**2)), dtype=torch.float32)
    target_t = torch.tensor(test_targets, dtype=torch.float32)
    test_nll = float(gaussian_nll(mean_t, log_var_t, target_t).item())
    return ClassicalBaselineResult(mu=mu, sigma=sigma, test_nll=test_nll)


@dataclass(frozen=True, slots=True)
class VolterraGenReport:
    seed: int
    n_train: int
    n_validation: int
    n_test: int
    model_test_nll: float
    classical_baseline: ClassicalBaselineResult
    calibration: CalibrationResult
    verdict: str
    """'generator_beats_classical_baseline', 'classical_baseline_beats_generator',
    or 'inconclusive' -- a direct test_nll comparison, reported honestly
    either way, exactly like every other matched-baseline comparison in
    this repository."""


def _verdict(model_test_nll: float, baseline_test_nll: float) -> str:
    if model_test_nll < baseline_test_nll:
        return "generator_beats_classical_baseline"
    if model_test_nll > baseline_test_nll:
        return "classical_baseline_beats_generator"
    return "inconclusive"


def run_volterra_gen(
    data_path: Path,
    *,
    seed: int = 0,
    validation_start: date = date(2015, 1, 1),
    test_start: date = date(2020, 1, 1),
    max_epochs: int = 400,
    patience: int = 30,
    nominal_coverage: float = 0.90,
) -> VolterraGenReport:
    """End-to-end: load the real Kaggle snapshot, build the point-in-time
    dataset, chronologically split it, train the conditional generator
    (validation-selected early stopping), evaluate it on the held-out
    test period against the classical baseline (NLL) AND a calibration
    diagnostic -- the real "labeled and diagnosed" FP-13 acceptance."""
    store, months = load_observations_into_store(data_path)
    examples = build_volterra_gen_dataset(store, months)
    train, validation, test = chronological_split(examples, validation_start, test_start)

    trained = train_scenario_generator(
        train, validation, seed=seed, max_epochs=max_epochs, patience=patience
    )
    test_mean, test_log_var = predict(trained.model, test)
    test_targets = _targets_array(test)
    model_test_nll = float(
        gaussian_nll(
            torch.tensor(test_mean, dtype=torch.float32),
            torch.tensor(test_log_var, dtype=torch.float32),
            torch.tensor(test_targets, dtype=torch.float32),
        ).item()
    )
    baseline = fit_classical_baseline(train, test)
    calibration = gaussian_interval_coverage_test(
        test_mean, test_log_var, test_targets, coverage=nominal_coverage
    )

    return VolterraGenReport(
        seed=seed,
        n_train=len(train),
        n_validation=len(validation),
        n_test=len(test),
        model_test_nll=model_test_nll,
        classical_baseline=baseline,
        calibration=calibration,
        verdict=_verdict(model_test_nll, baseline.test_nll),
    )
