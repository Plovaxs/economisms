"""Real-data policy-rule study (PR-200): how well do monetary-policy rules explain what
the Federal Reserve actually did?

The policy simulator (`policylab`) trains a reinforcement-learning policy against a
Taylor-rule baseline on a SYNTHETIC economy. This study puts the same kind of rule in front
of real data -- the Federal Reserve's own Kaggle dataset (`kaggle_fed_policy`: effective
federal funds rate, unemployment, inflation, 1958-1989 train, 1990-1999 validation, and a
2000-2017 test period that contains the 2008 crisis and the zero lower bound) -- and asks
a deliberately modest question: predict this month's effective rate from what was known at
the start of the month (the previous month's rate, unemployment and inflation, i.e. a
one-month publication delay).

Models:

- `persistence`        this month's rate = last month's.
- `simulator_taylor`   `policylab.TaylorRuleBaseline` with the simulator's OWN default
                       parameters (3% neutral rate, 2% target, 1.5 on inflation, 0.5 on the
                       output gap, `PolicyLabEnvConfig`), evaluated on real data. The output
                       gap is proxied from unemployment by Okun's law (gap = -2 x (u - u*),
                       u* = the training-window mean): a disclosed assumption.
- `ols_partial`        the standard partial-adjustment Taylor rule
                       i_t = c + rho i_{t-1} + a pi_{t-1} + b u_{t-1}, by least squares; its
                       long-run inflation response a / (1 - rho) is what the Taylor principle
                       (greater than 1) is about.
- `neural_ensemble`    a small MLP that predicts the CHANGE in the rate from six lagged
                       features, early-stopped on the validation split, averaged over seeds.

The "more data" axis is the length of the training window (1958-1989, the last 20 years,
the last 10). Errors are reported on the whole test period and on the months before the
zero lower bound (2008-11), after which every linear rule fails by construction. Paired
squared-error differences use a 12-month moving-block bootstrap.

A standalone research CLI: no network call, all data committed.
"""

from __future__ import annotations

import argparse
import copy
import json
import math
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

import numpy as np
import torch
from torch import nn

from prometheus.data_ingestion.kaggle_fed_policy import FedPolicyMonth, load_fed_policy_months
from prometheus.experiments.block_bootstrap import moving_block_bootstrap
from prometheus.policylab.environment import PolicyLabEnvConfig, PolicyLabState
from prometheus.policylab.taylor_rule import TaylorRuleBaseline

DATA_PATH = Path(__file__).resolve().parents[3] / "data_cache" / "kaggle_fed_policy_monthly.csv"
TRAIN_END = date(1989, 12, 31)
VALIDATION_END = date(1999, 12, 31)
ZLB_START = date(2008, 11, 30)
WINDOW_STARTS: dict[str, date | None] = {
    "10y": date(1980, 1, 1),
    "20y": date(1970, 1, 1),
    "all": None,
}
BLOCK_LENGTH = 12
OKUN_COEFFICIENT = -2.0
FEATURE_NAMES = (
    "rate_lag",
    "inflation_lag",
    "unemployment_lag",
    "d_unemployment",
    "d_inflation",
    "d_rate",
)


@dataclass(frozen=True, slots=True)
class PolicyRows:
    """Row t explains month t's effective rate from months t-1 and t-2 only."""

    months: tuple[date, ...]
    features: np.ndarray
    target: np.ndarray


def build_rows(months: Sequence[FedPolicyMonth]) -> PolicyRows:
    complete = [
        m
        for m in months
        if m.ffr_effective is not None and m.unemployment is not None and m.inflation is not None
    ]
    if len(complete) < 3:
        raise ValueError("need at least three complete months")
    ends = [m.month_end for m in complete]
    for earlier, later in zip(ends, ends[1:], strict=False):
        if (later.year - earlier.year) * 12 + later.month - earlier.month != 1:
            raise ValueError(f"months are not consecutive between {earlier} and {later}")
    rate = np.array([m.ffr_effective for m in complete], dtype=np.float64)
    unemployment = np.array([m.unemployment for m in complete], dtype=np.float64)
    inflation = np.array([m.inflation for m in complete], dtype=np.float64)
    rows = np.arange(2, len(complete))
    features = np.column_stack(
        [
            rate[rows - 1],
            inflation[rows - 1],
            unemployment[rows - 1],
            unemployment[rows - 1] - unemployment[rows - 2],
            inflation[rows - 1] - inflation[rows - 2],
            rate[rows - 1] - rate[rows - 2],
        ]
    )
    return PolicyRows(tuple(ends[2:]), features, rate[rows])


def simulator_taylor_prediction(features: np.ndarray, natural_unemployment: float) -> np.ndarray:
    """The simulator's own `TaylorRuleBaseline`, in percent, on real lagged data."""
    config = PolicyLabEnvConfig()
    rule = TaylorRuleBaseline(
        neutral_rate=config.neutral_rate,
        inflation_target=config.inflation_target,
        rate_max=config.rate_max,
    )
    out = np.empty(len(features))
    for i, row in enumerate(features):
        state = PolicyLabState(
            inflation=row[1] / 100.0,
            output_gap=OKUN_COEFFICIENT * (row[2] - natural_unemployment) / 100.0,
            rate=row[0] / 100.0,
            step=0,
        )
        out[i] = rule.act(state) * 100.0
    return out


def fit_ols(features: np.ndarray, target: np.ndarray, n_features: int = 3) -> np.ndarray:
    """Least squares of the rate on a constant and the first `n_features` lagged features
    (3 = the classic partial-adjustment Taylor rule; 6 = all features the neural rule sees)."""
    design = np.column_stack([np.ones(len(features)), features[:, :n_features]])
    coefficients, *_ = np.linalg.lstsq(design, target, rcond=None)
    return np.asarray(coefficients, dtype=np.float64)


def ols_predict(coefficients: np.ndarray, features: np.ndarray) -> np.ndarray:
    design = np.column_stack([np.ones(len(features)), features[:, : len(coefficients) - 1]])
    return np.asarray(design @ coefficients, dtype=np.float64)


def long_run_response(coefficients: np.ndarray) -> tuple[float, float]:
    """(long-run inflation response, long-run unemployment response) of the fitted rule."""
    rho = coefficients[1]
    if rho >= 1.0:
        return math.nan, math.nan
    return float(coefficients[2] / (1.0 - rho)), float(coefficients[3] / (1.0 - rho))


def bootstrap_long_run_response(
    features: np.ndarray,
    target: np.ndarray,
    block_length: int,
    rng: np.random.Generator,
    n_resamples: int,
) -> tuple[float, float, float]:
    """95% moving-block-bootstrap interval of the long-run inflation response, over the
    resamples where it is defined (rho < 1), and the share of resamples where it is not
    (a unit-root fit has no long-run response, which a percentile of NaNs would hide)."""
    n = len(target)
    blocks = -(-n // block_length)
    values: list[float] = []
    for _ in range(n_resamples):
        starts = rng.integers(0, n - block_length + 1, size=blocks)
        index = np.concatenate([np.arange(s, s + block_length) for s in starts])[:n]
        phi = long_run_response(fit_ols(features[index], target[index], 3))[0]
        values.append(phi)
    defined = np.array([v for v in values if not math.isnan(v)])
    low, high = (
        (float(q) for q in np.quantile(defined, [0.025, 0.975]))
        if len(defined)
        else (math.nan, math.nan)
    )
    return low, high, 1.0 - len(defined) / n_resamples


class NeuralRule:
    def __init__(self, mean: np.ndarray, scale: np.ndarray, seed: int) -> None:
        torch.manual_seed(seed)
        self.mean, self.scale = mean, scale
        self.net = nn.Sequential(
            nn.Linear(6, 16), nn.Tanh(), nn.Linear(16, 16), nn.Tanh(), nn.Linear(16, 1)
        )

    def change(self, features: np.ndarray) -> torch.Tensor:
        x = torch.tensor((features - self.mean) / self.scale, dtype=torch.float32)
        out: torch.Tensor = self.net(x).squeeze(-1)
        return out

    def predict(self, features: np.ndarray) -> np.ndarray:
        with torch.no_grad():
            return np.asarray(features[:, 0] + self.change(features).numpy(), dtype=np.float64)


def train_neural_rule(
    train_x: np.ndarray,
    train_y: np.ndarray,
    validation_x: np.ndarray,
    validation_y: np.ndarray,
    *,
    seed: int,
    max_epochs: int = 600,
    patience: int = 40,
) -> NeuralRule:
    """Full-batch Adam on the squared error of the predicted CHANGE in the rate; the
    validation split only chooses the epoch."""
    model = NeuralRule(train_x.mean(axis=0), train_x.std(axis=0) + 1e-9, seed)
    optimiser = torch.optim.Adam(model.net.parameters(), lr=3e-3)
    train_delta = torch.tensor(train_y - train_x[:, 0], dtype=torch.float32)
    validation_delta = torch.tensor(validation_y - validation_x[:, 0], dtype=torch.float32)
    best, best_state, stale = math.inf, copy.deepcopy(model.net.state_dict()), 0
    for _ in range(max_epochs):
        optimiser.zero_grad()
        loss = torch.mean((model.change(train_x) - train_delta) ** 2)
        loss.backward()  # type: ignore[no-untyped-call]
        optimiser.step()
        with torch.no_grad():
            validation_loss = float(
                torch.mean((model.change(validation_x) - validation_delta) ** 2)
            )
        if validation_loss < best - 1e-9:
            best, best_state, stale = validation_loss, copy.deepcopy(model.net.state_dict()), 0
        else:
            stale += 1
            if stale >= patience:
                break
    model.net.load_state_dict(best_state)
    return model


def _errors(prediction: np.ndarray, actual: np.ndarray) -> dict[str, float]:
    error = prediction - actual
    return {"rmse": float(np.sqrt(np.mean(error**2))), "mae": float(np.mean(np.abs(error)))}


def run_study(
    path: Path = DATA_PATH,
    *,
    seeds: Sequence[int] = (0, 1, 2, 3, 4),
    block_resamples: int = 2000,
) -> dict[str, Any]:
    rows = build_rows(load_fed_policy_months(path))
    months = np.array(rows.months)
    train_all = months <= TRAIN_END
    validation = (months > TRAIN_END) & (months <= VALIDATION_END)
    test = months > VALIDATION_END
    test_pre_zlb = test & (months < ZLB_START)
    x, y = rows.features, rows.target

    predictions: dict[str, np.ndarray] = {"persistence": x[:, 0]}
    long_run: dict[str, Any] = {}
    for label, start in WINDOW_STARTS.items():
        window = train_all & (np.array([start is None or m >= start for m in months]))
        natural_unemployment = float(x[window, 2].mean())
        predictions[f"simulator_taylor@{label}"] = simulator_taylor_prediction(
            x, natural_unemployment
        )
        coefficients = fit_ols(x[window], y[window], 3)
        predictions[f"ols_partial@{label}"] = ols_predict(coefficients, x)
        predictions[f"ols_six@{label}"] = ols_predict(fit_ols(x[window], y[window], 6), x)
        phi_pi, phi_u = long_run_response(coefficients)
        long_run[label] = {
            "n_train_months": int(window.sum()),
            "persistence_rho": float(coefficients[1]),
            "long_run_inflation_response": phi_pi,
            "long_run_unemployment_response": phi_u,
        }
        members = [
            train_neural_rule(
                x[window], y[window], x[validation], y[validation], seed=seed
            ).predict(x)
            for seed in seeds
        ]
        predictions[f"neural_ensemble@{label}"] = np.mean(members, axis=0)

    rng = np.random.default_rng(0)
    low, high, undefined = bootstrap_long_run_response(
        x[train_all], y[train_all], BLOCK_LENGTH, rng, block_resamples
    )
    long_run["all"]["long_run_inflation_response_ci"] = [low, high]
    long_run["all"]["share_of_resamples_with_rho_at_least_1"] = undefined
    long_run["simulator_default_response"] = 1.5

    results: dict[str, Any] = {}
    for name, prediction in predictions.items():
        results[name] = {
            "test_all": _errors(prediction[test], y[test]),
            "test_pre_zlb": _errors(prediction[test_pre_zlb], y[test_pre_zlb]),
        }

    comparisons: dict[str, Any] = {}
    persistence_error = (predictions["persistence"][test_pre_zlb] - y[test_pre_zlb]) ** 2
    for name in ("simulator_taylor@all", "ols_partial@all", "ols_six@all", "neural_ensemble@all"):
        difference = (predictions[name][test_pre_zlb] - y[test_pre_zlb]) ** 2 - persistence_error
        interval = moving_block_bootstrap(
            np.mean, difference, BLOCK_LENGTH, rng, n_resamples=block_resamples
        )
        comparisons[f"{name}_vs_persistence_pre_zlb"] = {
            "mean_squared_error_difference": interval.point_estimate,
            "ci_low": interval.ci_low,
            "ci_high": interval.ci_high,
            "verdict": (
                "lower_error_than_persistence"
                if interval.ci_high < 0
                else "higher_error_than_persistence"
                if interval.ci_low > 0
                else "inconclusive"
            ),
        }
    nonlinear_gain = (predictions["neural_ensemble@all"][test_pre_zlb] - y[test_pre_zlb]) ** 2 - (
        predictions["ols_six@all"][test_pre_zlb] - y[test_pre_zlb]
    ) ** 2
    interval = moving_block_bootstrap(
        np.mean, nonlinear_gain, BLOCK_LENGTH, rng, n_resamples=block_resamples
    )
    comparisons["neural_ensemble_vs_ols_six_pre_zlb"] = {
        "mean_squared_error_difference": interval.point_estimate,
        "ci_low": interval.ci_low,
        "ci_high": interval.ci_high,
        "verdict": (
            "neural_has_lower_error"
            if interval.ci_high < 0
            else "neural_has_higher_error"
            if interval.ci_low > 0
            else "inconclusive"
        ),
    }
    for label_a, label_b in (
        ("ols_partial", "10y"),
        ("ols_six", "10y"),
        ("neural_ensemble", "10y"),
    ):
        difference = (predictions[f"{label_a}@all"][test_pre_zlb] - y[test_pre_zlb]) ** 2 - (
            predictions[f"{label_a}@{label_b}"][test_pre_zlb] - y[test_pre_zlb]
        ) ** 2
        interval = moving_block_bootstrap(
            np.mean, difference, BLOCK_LENGTH, rng, n_resamples=block_resamples
        )
        comparisons[f"{label_a}_all_vs_10y_pre_zlb"] = {
            "mean_squared_error_difference": interval.point_estimate,
            "ci_low": interval.ci_low,
            "ci_high": interval.ci_high,
        }

    return {
        "config": {
            "train_end": TRAIN_END.isoformat(),
            "validation_end": VALIDATION_END.isoformat(),
            "zlb_start": ZLB_START.isoformat(),
            "seeds": list(seeds),
            "block_length_months": BLOCK_LENGTH,
            "okun_coefficient": OKUN_COEFFICIENT,
            "features": list(FEATURE_NAMES),
        },
        "data": {
            "n_rows": len(months),
            "first_month": months[0].isoformat(),
            "last_month": months[-1].isoformat(),
            "n_train": int(train_all.sum()),
            "n_validation": int(validation.sum()),
            "n_test": int(test.sum()),
            "n_test_pre_zlb": int(test_pre_zlb.sum()),
        },
        "long_run": long_run,
        "results": results,
        "comparisons": comparisons,
        "caveats": [
            "One country, one central bank, 206 test months, a regime break (the zero lower bound) "
            "in the middle of the test period.",
            "Inflation is the dataset's own measure; the output gap is proxied from unemployment "
            "by an assumed Okun coefficient.",
            "Effective rates are monthly values; the one-month publication delay is a "
            "simplification.",
            "The dataset ends in 2017 and some of its columns are sparse.",
        ],
    }


def main(
    argv: Sequence[str] | None = None, *, runner: Callable[..., dict[str, Any]] = run_study
) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument("--seeds", type=int, default=5)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    if args.seeds < 1:
        parser.error("--seeds must be a positive integer")
    report = runner(seeds=list(range(args.seeds)))
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2))
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
