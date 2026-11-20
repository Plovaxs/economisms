"""Do 76 years of CPI history and the arithmetic of base effects improve the nowcast? (PR-203)

INFLATIONCAST's own benchmark found naive persistence of the year-over-year rate unbeaten -- on a
test set of 13 months (the BLS snapshot starts in 2007 and the Kaggle predictors end in 2023-01).
This study gives the question a test set about twenty times larger and adds one piece of
structure the YoY rate hides. Writing `I_t` for the index level,

    YoY_t - YoY_{t-1}  ~  MoM_t - MoM_{t-12}

so a year-over-year nowcast is a forecast of ONE unknown number, this month's growth `MoM_t`,
because the month that drops out of the window (`MoM_{t-12}`) is already known. Persistence of
the YoY rate implicitly forecasts `MoM_t = MoM_{t-12}`; a forecast of the recent monthly trend does
not need that. Every model below forecasts `MoM_t` and converts it to a YoY nowcast with the
exact identity `YoY_t = I_{t-1} (1 + MoM_t) / I_{t-12} - 1`.

The nowcast is made at the end of month t, before month t's CPI is published (mid-month t+1): it
may use index levels up to month t-1 and the macro-financial predictors on grid row t.

Five questions, written down BEFORE any number below was computed, each with its predicted
direction. A paired comparison (mean absolute YoY error, 12-month moving-block bootstrap, 95%
interval) is SUPPORTED if the interval lies on the predicted side of zero, CONTRADICTED if on
the other side, INCONCLUSIVE if it contains zero:

  Q1  The base-effect rule (`base_mean12`: forecast MoM as its 12-month mean) has a LOWER error
      than persistence of the YoY rate.
  Q2  A learned MoM model (`ridge_own`: ridge regression on the last 12 monthly growth rates)
      has a LOWER error than the best base-effect rule.
  Q3  Adding macro-financial predictors (unemployment and the policy rate, level and 3-month
      change) LOWERS the error of the ridge and of the neural model.
  Q4  More history LOWERS the error: ridge trained from 1949 versus from 1980, and the neural
      model from 1962 versus from 1980.
  Q5  Descriptive only: errors in 2020-2023, when inflation moved out of its post-1990 range.

Splits by target month: fit through 1989-12, validate 1990-1999 (selects the ridge penalty and
early-stops the neural model, nothing else), test 2000-01 .. 2023-01 (277 months). The neural
model is averaged over five seeds in forecast space.

Data (committed, no network call): `kaggle_cpi_index_monthly.csv` (CPI-U seasonally adjusted
levels) and `kaggle_us_macro_extended_monthly.csv`. Caveat: the CPI levels are the seasonally
adjusted series as it stands today, not the real-time vintage.
"""

from __future__ import annotations

import argparse
import copy
import json
import math
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

import numpy as np
import torch
from torch import nn

from prometheus.data_ingestion.kaggle_cpi_index import load_cpi_index
from prometheus.data_ingestion.kaggle_macro_extended import load_extended_macro_observations
from prometheus.experiments.block_bootstrap import moving_block_bootstrap

DATA_DIR = Path(__file__).resolve().parents[3] / "data_cache"
CPI_PATH = DATA_DIR / "kaggle_cpi_index_monthly.csv"
MACRO_PATH = DATA_DIR / "kaggle_us_macro_extended_monthly.csv"
TRAIN_END = date(1989, 12, 31)
VALIDATION_END = date(1999, 12, 31)
SURGE_START = date(2020, 1, 31)
N_LAGS = 12
BLOCK_MONTHS = 12
MACRO_COLUMNS = ("UNRATE", "FEDFUNDS", "CLAIMS_YOY", "GDP_YOY", "BANK_CREDIT_YOY", "SPX_YOY")
CORE_COLUMNS = ("UNRATE", "FEDFUNDS")
EXTRA_COLUMNS = ("CLAIMS_YOY", "GDP_YOY", "BANK_CREDIT_YOY", "SPX_YOY")
RIDGE_PENALTIES = (1e-3, 1e-2, 1e-1, 1.0, 10.0, 100.0, 1_000.0)
HISTORY_STARTS: dict[str, date] = {
    "1949": date(1949, 1, 31),
    "1962": date(1962, 1, 31),
    "1980": date(1980, 1, 31),
    "1981": date(1981, 1, 31),
}
"""Where each variant's training window begins (target months)."""


# ------------------------------------------------------------------------------ the data


@dataclass(frozen=True)
class NowcastData:
    """One row per TARGET month t, with only what is known at the end of month t."""

    months: tuple[date, ...]
    yoy: np.ndarray
    mom: np.ndarray
    previous_yoy: np.ndarray
    base_level: np.ndarray
    year_ago_level: np.ndarray
    mom_history: np.ndarray
    macro: dict[str, np.ndarray]

    def mask(self, start: date | None, end: date | None) -> np.ndarray:
        return np.array(
            [(start is None or m >= start) and (end is None or m <= end) for m in self.months]
        )


def build_nowcast_data(cpi_path: Path = CPI_PATH, macro_path: Path = MACRO_PATH) -> NowcastData:
    months, levels = load_cpi_index(cpi_path)
    n = len(levels)
    mom = np.full(n, np.nan)
    mom[1:] = 100.0 * (levels[1:] / levels[:-1] - 1.0)
    yoy = np.full(n, np.nan)
    yoy[12:] = 100.0 * (levels[12:] / levels[:-12] - 1.0)
    rows = np.arange(N_LAGS + 1, n)  # a target month needs MoM_{t-12} .. MoM_{t-1}
    history = np.stack([mom[rows - N_LAGS + k] for k in range(N_LAGS)], axis=1)
    target_months = tuple(months[i] for i in rows)

    observed: dict[str, dict[date, float]] = {c: {} for c in MACRO_COLUMNS}
    for obs in load_extended_macro_observations(macro_path, columns=MACRO_COLUMNS):
        observed[obs.series_id.removeprefix("KAGGLEX_")][obs.observation_at] = obs.value
    macro = {
        column: np.array([observed[column].get(m, np.nan) for m in target_months])
        for column in MACRO_COLUMNS
    }
    return NowcastData(
        months=target_months,
        yoy=yoy[rows],
        mom=mom[rows],
        previous_yoy=yoy[rows - 1],
        base_level=levels[rows - 1],
        year_ago_level=levels[rows - 12],
        mom_history=history,
        macro=macro,
    )


def _change_over_three_months(values: np.ndarray) -> np.ndarray:
    out = np.full_like(values, np.nan, dtype=np.float64)
    out[3:] = values[3:] - values[:-3]
    return out


def feature_matrix(data: NowcastData, kind: str) -> np.ndarray:
    """`own`: the last 12 monthly growth rates. `core`: plus unemployment and the policy rate
    (level and 3-month change). `all`: plus four more macro-financial series."""
    if kind not in ("own", "core", "all"):
        raise ValueError(f"unknown feature set {kind!r}")
    columns: list[np.ndarray] = [data.mom_history]
    if kind in ("core", "all"):
        for name in CORE_COLUMNS:
            series = data.macro[name]
            columns += [series[:, None], _change_over_three_months(series)[:, None]]
    if kind == "all":
        columns += [data.macro[name][:, None] for name in EXTRA_COLUMNS]
    return np.hstack(columns)


def yoy_from_mom(data: NowcastData, mom_forecast: np.ndarray) -> np.ndarray:
    """The exact identity: `YoY_t = I_{t-1} (1 + MoM_t) / I_{t-12} - 1`, in percent."""
    return np.asarray(
        100.0 * (data.base_level * (1.0 + mom_forecast / 100.0) / data.year_ago_level - 1.0),
        dtype=np.float64,
    )


# ------------------------------------------------------------------------------ the models


def base_effect_forecast(data: NowcastData, name: str) -> np.ndarray:
    history = data.mom_history
    if name == "base_last":
        return np.asarray(history[:, -1], dtype=np.float64)
    if name == "base_mean3":
        return np.asarray(history[:, -3:].mean(axis=1), dtype=np.float64)
    if name == "base_mean12":
        return np.asarray(history.mean(axis=1), dtype=np.float64)
    raise ValueError(f"unknown base-effect rule {name!r}")


@dataclass(frozen=True)
class Ridge:
    mean: np.ndarray
    scale: np.ndarray
    coefficients: np.ndarray
    intercept: float

    def predict(self, x: np.ndarray) -> np.ndarray:
        return np.asarray(
            ((x - self.mean) / self.scale) @ self.coefficients + self.intercept, dtype=np.float64
        )


def fit_ridge(x: np.ndarray, y: np.ndarray, penalty: float) -> Ridge:
    if penalty < 0:
        raise ValueError("penalty must be non-negative")
    mean, scale = x.mean(axis=0), x.std(axis=0) + 1e-12
    z = (x - mean) / scale
    centred = y - y.mean()
    gram = z.T @ z + penalty * np.eye(z.shape[1])
    coefficients = np.linalg.solve(gram, z.T @ centred)
    return Ridge(mean, scale, coefficients, float(y.mean()))


class MomNetwork:
    """A small MLP from standardised features to the monthly growth rate."""

    def __init__(self, n_features: int, mean: np.ndarray, scale: np.ndarray, seed: int) -> None:
        torch.manual_seed(seed)
        self.mean, self.scale = mean, scale
        self.net = nn.Sequential(
            nn.Linear(n_features, 16), nn.Tanh(), nn.Linear(16, 16), nn.Tanh(), nn.Linear(16, 1)
        )

    def _tensor(self, x: np.ndarray) -> torch.Tensor:
        return torch.tensor((x - self.mean) / self.scale, dtype=torch.float32)

    def predict(self, x: np.ndarray) -> np.ndarray:
        with torch.no_grad():
            return np.asarray(
                self.net(self._tensor(x)).squeeze(-1).numpy().astype(np.float64), dtype=np.float64
            )


def train_mom_network(
    train_x: np.ndarray,
    train_y: np.ndarray,
    validation_x: np.ndarray,
    validation_y: np.ndarray,
    *,
    seed: int,
    max_epochs: int = 600,
    patience: int = 40,
) -> MomNetwork:
    """Full-batch Adam on squared error; the validation split only chooses the epoch."""
    model = MomNetwork(train_x.shape[1], train_x.mean(axis=0), train_x.std(axis=0) + 1e-12, seed)
    optimiser = torch.optim.Adam(model.net.parameters(), lr=3e-3)
    inputs = model._tensor(train_x)
    targets = torch.tensor(train_y, dtype=torch.float32)
    validation_inputs = model._tensor(validation_x)
    validation_targets = torch.tensor(validation_y, dtype=torch.float32)
    best, best_state, stale = math.inf, copy.deepcopy(model.net.state_dict()), 0
    for _ in range(max_epochs):
        optimiser.zero_grad()
        loss = torch.mean((model.net(inputs).squeeze(-1) - targets) ** 2)
        loss.backward()  # type: ignore[no-untyped-call]
        optimiser.step()
        with torch.no_grad():
            validation_loss = float(
                torch.mean((model.net(validation_inputs).squeeze(-1) - validation_targets) ** 2)
            )
        if validation_loss < best - 1e-9:
            best, best_state, stale = validation_loss, copy.deepcopy(model.net.state_dict()), 0
        else:
            stale += 1
            if stale >= patience:
                break
    model.net.load_state_dict(best_state)
    return model


# ------------------------------------------------------------------------------ the study


def _errors(data: NowcastData, forecast: np.ndarray, rows: np.ndarray) -> np.ndarray:
    return np.asarray(forecast[rows] - data.yoy[rows], dtype=np.float64)


def _summary(errors: np.ndarray) -> dict[str, float]:
    return {
        "mae": float(np.mean(np.abs(errors))),
        "rmse": float(np.sqrt(np.mean(errors**2))),
        "bias": float(np.mean(errors)),
    }


def verdict(ci_low: float, ci_high: float, *, predicted_negative: bool = True) -> str:
    """The pre-registered decision rule."""
    if ci_low > 0.0 and ci_high > 0.0:
        return "CONTRADICTED" if predicted_negative else "SUPPORTED"
    if ci_low < 0.0 and ci_high < 0.0:
        return "SUPPORTED" if predicted_negative else "CONTRADICTED"
    return "INCONCLUSIVE"


def _paired(
    first: np.ndarray, second: np.ndarray, rng: np.random.Generator, resamples: int
) -> dict[str, Any]:
    """Mean of |e_first| - |e_second| with a moving-block-bootstrap interval."""
    difference = np.abs(first) - np.abs(second)
    boot = moving_block_bootstrap(np.mean, difference, BLOCK_MONTHS, rng, n_resamples=resamples)
    return {
        "mae_difference_first_minus_second": boot.point_estimate,
        "ci_low": boot.ci_low,
        "ci_high": boot.ci_high,
        "preregistered_verdict": verdict(boot.ci_low, boot.ci_high),
    }


def run_study(
    cpi_path: Path = CPI_PATH,
    macro_path: Path = MACRO_PATH,
    *,
    seeds: Sequence[int] = (0, 1, 2, 3, 4),
    max_epochs: int = 600,
    patience: int = 40,
    block_resamples: int = 2000,
) -> dict[str, Any]:
    data = build_nowcast_data(cpi_path, macro_path)
    train_rows = data.mask(None, TRAIN_END)
    validation_rows = data.mask(TRAIN_END, VALIDATION_END) & ~train_rows
    # the CPI index runs two months past the macro grid: score only months every model can use
    complete = ~np.isnan(feature_matrix(data, "all")).any(axis=1)
    test_rows = ~(train_rows | validation_rows) & complete
    test_months = [m for m, keep in zip(data.months, test_rows, strict=True) if keep]
    surge = np.array([m >= SURGE_START for m in test_months])
    forecasts: dict[str, np.ndarray] = {"persistence_yoy": data.previous_yoy}
    for rule in ("base_last", "base_mean3", "base_mean12"):
        forecasts[rule] = yoy_from_mom(data, base_effect_forecast(data, rule))

    selection: dict[str, Any] = {}
    train_sizes: dict[str, int] = {}

    def usable(features: np.ndarray, rows: np.ndarray) -> np.ndarray:
        return np.asarray(rows & ~np.isnan(features).any(axis=1), dtype=bool)

    def window(start_label: str) -> np.ndarray:
        return data.mask(HISTORY_STARTS[start_label], None)

    def add_ridge(kind: str, start_label: str) -> None:
        x = feature_matrix(data, kind)
        fit_rows = usable(x, train_rows & window(start_label))
        val_rows = usable(x, validation_rows)
        best_error, best = math.inf, None
        for penalty in RIDGE_PENALTIES:
            model = fit_ridge(x[fit_rows], data.mom[fit_rows], penalty)
            mom = np.full(len(data.months), np.nan)
            mom[val_rows] = model.predict(x[val_rows])
            error = float(np.mean(np.abs(yoy_from_mom(data, mom)[val_rows] - data.yoy[val_rows])))
            if error < best_error:
                best_error, best = error, (penalty, model)
        assert best is not None  # noqa: S101
        penalty, model = best
        name = f"ridge_{kind}@{start_label}"
        mom = np.full(len(data.months), np.nan)
        mom[test_rows] = model.predict(x[test_rows])
        forecasts[name] = yoy_from_mom(data, mom)
        selection[name] = {"penalty": penalty, "validation_mae": best_error}
        train_sizes[name] = int(fit_rows.sum())

    def add_network(kind: str, start_label: str) -> None:
        x = feature_matrix(data, kind)
        fit_rows = usable(x, train_rows & window(start_label))
        val_rows = usable(x, validation_rows)
        per_seed = []
        for seed in seeds:
            model = train_mom_network(
                x[fit_rows],
                data.mom[fit_rows],
                x[val_rows],
                data.mom[val_rows],
                seed=seed,
                max_epochs=max_epochs,
                patience=patience,
            )
            per_seed.append(model.predict(x[test_rows]))
        mom = np.full(len(data.months), np.nan)
        mom[test_rows] = np.mean(per_seed, axis=0)
        name = f"mlp_{kind}@{start_label}"
        forecasts[name] = yoy_from_mom(data, mom)
        train_sizes[name] = int(fit_rows.sum())

    for kind, start_label in (
        ("own", "1949"),
        ("own", "1962"),
        ("own", "1980"),
        ("core", "1962"),
        ("core", "1980"),
        ("all", "1981"),
    ):
        add_ridge(kind, start_label)
    for kind, start_label in (("own", "1962"), ("own", "1980"), ("core", "1962"), ("core", "1980")):
        add_network(kind, start_label)

    errors = {name: _errors(data, forecast, test_rows) for name, forecast in forecasts.items()}
    scores = {
        name: {
            **_summary(e),
            "mae_2000_2019": float(np.mean(np.abs(e[~surge]))),
            "mae_2020_onward": float(np.mean(np.abs(e[surge]))),
        }
        for name, e in errors.items()
    }

    rng = np.random.default_rng(0)
    specs: dict[str, tuple[str, str]] = {
        "Q1_base_effect_vs_persistence": ("base_mean12", "persistence_yoy"),
        "Q2_ridge_own_vs_base_effect": ("ridge_own@1962", "base_mean12"),
        "Q3_ridge_core_vs_own": ("ridge_core@1962", "ridge_own@1962"),
        "Q3_mlp_core_vs_own": ("mlp_core@1962", "mlp_own@1962"),
        "Q4_ridge_1949_vs_1980": ("ridge_own@1949", "ridge_own@1980"),
        "Q4_mlp_1962_vs_1980": ("mlp_own@1962", "mlp_own@1980"),
    }
    comparisons = {
        label: {
            "first": first,
            "second": second,
            **_paired(errors[first], errors[second], rng, block_resamples),
        }
        for label, (first, second) in specs.items()
    }
    # Descriptive (not tested): the other base-effect rules and the ridge from 1962 vs 1980.
    descriptive = {
        label: {
            "first": first,
            "second": second,
            **_paired(errors[first], errors[second], rng, block_resamples),
        }
        for label, (first, second) in {
            "D1_base_mean3_vs_persistence": ("base_mean3", "persistence_yoy"),
            "D2_base_last_vs_persistence": ("base_last", "persistence_yoy"),
            "D3_ridge_1962_vs_1980": ("ridge_own@1962", "ridge_own@1980"),
            "D4_ridge_all_vs_own_1981": ("ridge_all@1981", "ridge_own@1980"),
        }.items()
    }
    for row in descriptive.values():
        del row["preregistered_verdict"]

    return {
        "config": {
            "train_end": TRAIN_END.isoformat(),
            "validation_end": VALIDATION_END.isoformat(),
            "surge_start": SURGE_START.isoformat(),
            "seeds": list(seeds),
            "block_months": BLOCK_MONTHS,
            "ridge_penalties": list(RIDGE_PENALTIES),
        },
        "data": {
            "n_target_months": len(data.months),
            "first_target_month": data.months[0].isoformat(),
            "n_train": int(train_rows.sum()),
            "n_validation": int(validation_rows.sum()),
            "n_test": int(test_rows.sum()),
            "n_test_2020_onward": int(surge.sum()),
            "test_first_month": test_months[0].isoformat(),
            "test_last_month": test_months[-1].isoformat(),
            "training_rows_per_model": train_sizes,
            "test_yoy_range": [
                float(data.yoy[test_rows].min()),
                float(data.yoy[test_rows].max()),
            ],
        },
        "scores": scores,
        "selection": selection,
        "comparisons": comparisons,
        "descriptive_comparisons": descriptive,
        "caveats": [
            "One country, one price index, one test window that contains the 2008 collapse and the "
            "2021-2022 surge; 277 monthly errors are serially dependent (12-month blocks).",
            "The index levels are the seasonally adjusted series as it stands today, not the "
            "real-time vintage; seasonal factors are re-estimated for years after publication.",
            "The macro predictors sit on the grid's fixed-lag point-in-time convention, not on "
            "fetched release vintages.",
            "The 2020-onward subperiod has only 37 months; it is reported, not tested.",
            "Models forecast the monthly growth rate and are converted to a YoY nowcast by an "
            "exact identity; the neural numbers are an average over five seeds.",
        ],
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument("--seeds", type=int, default=5)
    parser.add_argument("--max-epochs", type=int, default=600)
    parser.add_argument("--patience", type=int, default=40)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    if args.seeds < 1:
        parser.error("--seeds must be a positive integer")
    report = run_study(
        seeds=list(range(args.seeds)), max_epochs=args.max_epochs, patience=args.patience
    )
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2))
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
