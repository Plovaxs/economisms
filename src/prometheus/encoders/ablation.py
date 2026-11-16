"""FP-08: "Shared-vs-independent encoder ablation is complete."

Trains two conditions on the IDENTICAL real data/splits:

- shared: one `TemporalEncoder` feeding both a recession head and an
  inflation head, trained jointly on
  `L = lambda_r * L_recession + lambda_i * L_inflation`.
- independent: two separately-initialized `TemporalEncoder`s of the
  IDENTICAL architecture, each trained on its own single task alone.

`lambda_r`/`lambda_i` are set USING THE VALIDATION SPLIT ONLY, per the
blueprint's own "04 | Core mathematical specification" instruction
("Set weights on validation data only; compare against standalone
heads"): each is the reciprocal of a trivial baseline's validation
loss for that task (the training-set recession base rate's BCE, and
the training-set mean CPI target's MSE, both scored ON the validation
split) -- a principled, validation-informed normalization that puts
both loss terms on a comparable O(1) scale at baseline performance,
not an arbitrary unjustified weighting, and not tuned by peeking at
test-set performance.

Real result (`run_encoder_ablation`'s own module-level docstring entry
below is intentionally silent on the number -- see
`tests/unit/test_shared_encoder_ablation.py` and
`CHECKLIST_STATUS.md`'s FP-08 row for the actual observed comparison;
a null or negative result is a valid, reported-as-is outcome here, the
same standard this project applies everywhere else).
"""

from __future__ import annotations

import copy
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Literal

import numpy as np
import torch
from torch import nn

from prometheus.data_ingestion.kaggle_macro import (
    KAGGLE_SERIES_IDS,
    load_kaggle_us_macro_observations,
)
from prometheus.encoders.shared_dataset import (
    build_shared_encoder_dataset,
    chronological_split3,
    inflation_targets,
    recession_labels,
    stack_features,
)
from prometheus.encoders.shared_encoder import (
    InflationHead,
    RecessionHead,
    SharedEncoderModel,
    SingleTaskModel,
    TemporalEncoder,
    count_parameters,
)
from prometheus.inflationcast.data import load_cpi_observations
from prometheus.recessionnet.evaluation import roc_auc

DEFAULT_KAGGLE_CSV_PATH = (
    Path(__file__).resolve().parents[3] / "data_cache" / "kaggle_us_macro_monthly.csv"
)
DEFAULT_CPI_CSV_PATH = Path(__file__).resolve().parents[3] / "data_cache" / "us_cpi_monthly.csv"
CPI_SERIES_ID = "CPI_YOY"

Verdict = Literal["shared_better", "independent_better", "inconclusive"]
_VERDICT_TOLERANCE = 0.01
"""A relative-improvement margin below which a condition is called
`inconclusive` rather than `shared_better`/`independent_better` --
avoids reporting an arbitrarily tiny floating-point difference as a
real finding."""


@dataclass(frozen=True, slots=True)
class EncoderAblationConfig:
    seed: int = 0
    hidden_size: int = 16
    max_epochs: int = 300
    patience: int = 20
    learning_rate: float = 0.01
    window: int = 6
    horizon: int = 6
    validation_split_date: date = date(2015, 1, 1)
    test_split_date: date = date(2019, 1, 1)

    def __post_init__(self) -> None:
        if self.seed < 0:
            raise ValueError("seed must be non-negative")
        if self.hidden_size < 1:
            raise ValueError("hidden_size must be a positive integer")
        if self.max_epochs < 1:
            raise ValueError("max_epochs must be a positive integer")
        if self.patience < 1:
            raise ValueError("patience must be a positive integer")
        if self.window < 1:
            raise ValueError("window must be a positive integer")
        if self.horizon < 1:
            raise ValueError("horizon must be a positive integer")
        if self.validation_split_date >= self.test_split_date:
            raise ValueError("validation_split_date must be strictly before test_split_date")


@dataclass(frozen=True, slots=True)
class EpochRecord:
    epoch: int
    train_loss: float
    validation_score: float


@dataclass(frozen=True, slots=True)
class FitResult:
    epoch_log: tuple[EpochRecord, ...]
    selected_epoch: int
    best_validation_score: float
    train_seconds: float


def _fit_with_early_stopping(
    model: nn.Module,
    *,
    seed: int,
    learning_rate: float,
    max_epochs: int,
    patience: int,
    train_step: Callable[[], torch.Tensor],
    eval_step: Callable[[], float],
) -> FitResult:
    """Generic full-batch Adam early-stopping loop, shared by both the
    shared and independent conditions: `train_step` does one forward/
    backward/optimizer.step and returns the training loss tensor;
    `eval_step` (called with `torch.no_grad()` and the model in `eval`
    mode) returns a single scalar validation score, lower-is-better for
    both tasks here (BCE and MSE alike)."""
    torch.manual_seed(seed)
    optimizer = torch.optim.Adam(model.parameters(), lr=learning_rate)

    epoch_log: list[EpochRecord] = []
    best_score = float("inf")
    best_state: dict[str, torch.Tensor] | None = None
    best_epoch = -1
    since_improvement = 0

    start = time.perf_counter()
    for epoch in range(max_epochs):
        optimizer.zero_grad()
        loss = train_step()
        loss.backward()  # type: ignore[no-untyped-call]
        optimizer.step()

        model.eval()
        with torch.no_grad():
            validation_score = eval_step()
        model.train()

        epoch_log.append(
            EpochRecord(
                epoch=epoch, train_loss=float(loss.item()), validation_score=validation_score
            )
        )
        if validation_score < best_score:
            best_score = validation_score
            best_state = copy.deepcopy(model.state_dict())
            best_epoch = epoch
            since_improvement = 0
        else:
            since_improvement += 1
            if since_improvement >= patience:
                break
    train_seconds = time.perf_counter() - start

    if best_state is None:
        raise RuntimeError("no epoch completed despite max_epochs >= 1 -- this is a bug")
    model.load_state_dict(best_state)

    return FitResult(
        epoch_log=tuple(epoch_log),
        selected_epoch=best_epoch,
        best_validation_score=best_score,
        train_seconds=train_seconds,
    )


def _lambda_weights(
    train_rec: np.ndarray, train_inf: np.ndarray, val_rec: np.ndarray, val_inf: np.ndarray
) -> tuple[float, float]:
    """Reciprocal of a trivial baseline's VALIDATION loss for each
    task -- see this module's own docstring for why."""
    base_rate = float(np.clip(train_rec.mean(), 1e-6, 1 - 1e-6))
    base_rate_bce = float(
        -np.mean(val_rec * np.log(base_rate) + (1 - val_rec) * np.log(1 - base_rate))
    )
    naive_mean = float(train_inf.mean())
    naive_mse = float(np.mean((val_inf - naive_mean) ** 2))
    lambda_r = 1.0 / max(base_rate_bce, 1e-8)
    lambda_i = 1.0 / max(naive_mse, 1e-8)
    return lambda_r, lambda_i


def _train_shared(
    train_x: np.ndarray,
    train_rec: np.ndarray,
    train_inf: np.ndarray,
    val_x: np.ndarray,
    val_rec: np.ndarray,
    val_inf: np.ndarray,
    *,
    n_series: int,
    hidden_size: int,
    seed: int,
    max_epochs: int,
    patience: int,
    learning_rate: float,
    lambda_r: float,
    lambda_i: float,
) -> tuple[SharedEncoderModel, FitResult]:
    torch.manual_seed(seed)
    model = SharedEncoderModel(
        TemporalEncoder(n_series, hidden_size),
        RecessionHead(hidden_size),
        InflationHead(hidden_size),
    )
    bce = nn.BCEWithLogitsLoss()
    mse = nn.MSELoss()

    x_train_t = torch.tensor(train_x, dtype=torch.float32)
    rec_train_t = torch.tensor(train_rec, dtype=torch.float32)
    inf_train_t = torch.tensor(train_inf, dtype=torch.float32)
    x_val_t = torch.tensor(val_x, dtype=torch.float32)
    rec_val_t = torch.tensor(val_rec, dtype=torch.float32)
    inf_val_t = torch.tensor(val_inf, dtype=torch.float32)

    def train_step() -> torch.Tensor:
        rec_logits, inf_pred = model(x_train_t)
        loss: torch.Tensor = lambda_r * bce(rec_logits, rec_train_t) + lambda_i * mse(
            inf_pred, inf_train_t
        )
        return loss

    def eval_step() -> float:
        rec_logits, inf_pred = model(x_val_t)
        score = lambda_r * bce(rec_logits, rec_val_t) + lambda_i * mse(inf_pred, inf_val_t)
        return float(score.item())

    fit = _fit_with_early_stopping(
        model,
        seed=seed,
        learning_rate=learning_rate,
        max_epochs=max_epochs,
        patience=patience,
        train_step=train_step,
        eval_step=eval_step,
    )
    return model, fit


def _train_single(
    train_x: np.ndarray,
    train_y: np.ndarray,
    val_x: np.ndarray,
    val_y: np.ndarray,
    *,
    head_factory: Callable[[int], nn.Module],
    loss_module: nn.Module,
    n_series: int,
    hidden_size: int,
    seed: int,
    max_epochs: int,
    patience: int,
    learning_rate: float,
) -> tuple[SingleTaskModel, FitResult]:
    torch.manual_seed(seed)
    model = SingleTaskModel(TemporalEncoder(n_series, hidden_size), head_factory(hidden_size))

    x_train_t = torch.tensor(train_x, dtype=torch.float32)
    y_train_t = torch.tensor(train_y, dtype=torch.float32)
    x_val_t = torch.tensor(val_x, dtype=torch.float32)
    y_val_t = torch.tensor(val_y, dtype=torch.float32)

    def train_step() -> torch.Tensor:
        loss: torch.Tensor = loss_module(model(x_train_t), y_train_t)
        return loss

    def eval_step() -> float:
        return float(loss_module(model(x_val_t), y_val_t).item())

    fit = _fit_with_early_stopping(
        model,
        seed=seed,
        learning_rate=learning_rate,
        max_epochs=max_epochs,
        patience=patience,
        train_step=train_step,
        eval_step=eval_step,
    )
    return model, fit


def _verdict(independent_score: float, shared_score: float, *, lower_is_better: bool) -> Verdict:
    if independent_score == 0:
        return "inconclusive"
    improvement = (independent_score - shared_score) / abs(independent_score)
    if not lower_is_better:
        improvement = -improvement
    if improvement > _VERDICT_TOLERANCE:
        return "shared_better"
    if improvement < -_VERDICT_TOLERANCE:
        return "independent_better"
    return "inconclusive"


@dataclass(frozen=True, slots=True)
class EncoderAblationResult:
    config: EncoderAblationConfig
    n_train: int
    n_validation: int
    n_test: int
    lambda_recession: float
    lambda_inflation: float
    shared_encoder_n_parameters: int
    independent_recession_encoder_n_parameters: int
    independent_inflation_encoder_n_parameters: int
    shared_recession_test_roc_auc: float
    shared_recession_test_brier: float
    shared_inflation_test_mae: float
    independent_recession_test_roc_auc: float
    independent_recession_test_brier: float
    independent_inflation_test_mae: float
    recession_verdict: Verdict
    inflation_verdict: Verdict


def run_encoder_ablation(
    config: EncoderAblationConfig,
    *,
    kaggle_csv_path: Path = DEFAULT_KAGGLE_CSV_PATH,
    cpi_csv_path: Path = DEFAULT_CPI_CSV_PATH,
) -> EncoderAblationResult:
    kaggle_observations = load_kaggle_us_macro_observations(kaggle_csv_path)
    cpi_observations = load_cpi_observations(cpi_csv_path)

    examples = build_shared_encoder_dataset(
        kaggle_observations,
        cpi_observations,
        series_ids=KAGGLE_SERIES_IDS,
        cpi_series_id=CPI_SERIES_ID,
        window=config.window,
        horizon=config.horizon,
    )
    train, validation, test = chronological_split3(
        examples, config.validation_split_date, config.test_split_date
    )
    n_series = len(KAGGLE_SERIES_IDS)

    train_x = stack_features(train, window=config.window, n_series=n_series)
    val_x = stack_features(validation, window=config.window, n_series=n_series)
    test_x = stack_features(test, window=config.window, n_series=n_series)
    train_rec, val_rec, test_rec = (
        recession_labels(train),
        recession_labels(validation),
        recession_labels(test),
    )
    train_inf, val_inf, test_inf = (
        inflation_targets(train),
        inflation_targets(validation),
        inflation_targets(test),
    )

    lambda_r, lambda_i = _lambda_weights(train_rec, train_inf, val_rec, val_inf)

    shared_model, _ = _train_shared(
        train_x,
        train_rec,
        train_inf,
        val_x,
        val_rec,
        val_inf,
        n_series=n_series,
        hidden_size=config.hidden_size,
        seed=config.seed,
        max_epochs=config.max_epochs,
        patience=config.patience,
        learning_rate=config.learning_rate,
        lambda_r=lambda_r,
        lambda_i=lambda_i,
    )
    indep_rec_model, _ = _train_single(
        train_x,
        train_rec,
        val_x,
        val_rec,
        head_factory=RecessionHead,
        loss_module=nn.BCEWithLogitsLoss(),
        n_series=n_series,
        hidden_size=config.hidden_size,
        seed=config.seed,
        max_epochs=config.max_epochs,
        patience=config.patience,
        learning_rate=config.learning_rate,
    )
    indep_inf_model, _ = _train_single(
        train_x,
        train_inf,
        val_x,
        val_inf,
        head_factory=InflationHead,
        loss_module=nn.MSELoss(),
        n_series=n_series,
        hidden_size=config.hidden_size,
        seed=config.seed,
        max_epochs=config.max_epochs,
        patience=config.patience,
        learning_rate=config.learning_rate,
    )

    x_test_t = torch.tensor(test_x, dtype=torch.float32)
    shared_model.eval()
    indep_rec_model.eval()
    indep_inf_model.eval()
    with torch.no_grad():
        shared_rec_logits, shared_inf_pred = shared_model(x_test_t)
        shared_rec_probs = torch.sigmoid(shared_rec_logits).numpy()
        shared_inf_preds = shared_inf_pred.numpy()
        indep_rec_probs = torch.sigmoid(indep_rec_model(x_test_t)).numpy()
        indep_inf_preds = indep_inf_model(x_test_t).numpy()

    shared_rec_auc = roc_auc(shared_rec_probs, test_rec)
    shared_rec_brier = float(np.mean((shared_rec_probs - test_rec) ** 2))
    shared_inf_mae = float(np.mean(np.abs(shared_inf_preds - test_inf)))
    indep_rec_auc = roc_auc(indep_rec_probs, test_rec)
    indep_rec_brier = float(np.mean((indep_rec_probs - test_rec) ** 2))
    indep_inf_mae = float(np.mean(np.abs(indep_inf_preds - test_inf)))

    return EncoderAblationResult(
        config=config,
        n_train=len(train),
        n_validation=len(validation),
        n_test=len(test),
        lambda_recession=lambda_r,
        lambda_inflation=lambda_i,
        shared_encoder_n_parameters=count_parameters(shared_model.encoder),
        independent_recession_encoder_n_parameters=count_parameters(indep_rec_model.encoder),
        independent_inflation_encoder_n_parameters=count_parameters(indep_inf_model.encoder),
        shared_recession_test_roc_auc=shared_rec_auc,
        shared_recession_test_brier=shared_rec_brier,
        shared_inflation_test_mae=shared_inf_mae,
        independent_recession_test_roc_auc=indep_rec_auc,
        independent_recession_test_brier=indep_rec_brier,
        independent_inflation_test_mae=indep_inf_mae,
        recession_verdict=_verdict(indep_rec_brier, shared_rec_brier, lower_is_better=True),
        inflation_verdict=_verdict(indep_inf_mae, shared_inf_mae, lower_is_better=True),
    )
