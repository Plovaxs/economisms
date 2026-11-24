"""E3: is GARCH with filtered historical simulation calibrated on days it never saw? (Finding 15)

The forecaster is `orchestration.market_risk_study`'s own `garch_fhs@all`, reproduced line for line
from `evaluate_baseline_models` and compared with it by the tests: a GARCH(1,1) fitted ONCE on the
returns before 2000 (`fit_garch11`), its conditional volatility filtered through every later return
up to the previous day, and the empirical quantile of its standardised training residuals as the
VaR multiplier. The baseline is the 250-day historical simulation. Nothing is refitted or retuned on
the scored days.

Primary claim (99% VaR): the model is "consistent with coverage" only if the exact binomial interval
for its exceedance rate contains 1% AND the conditional-coverage test does not reject at the
Bonferroni test level `1 - confidence`. With a few hundred days that is weak evidence either way
(about 9 exceedances are expected over 900 days) and the report says so by printing the
interval, not a verdict alone. Secondary: the same at 97.5%, and the paired pinball-loss
difference against the historical simulation (positive favours GARCH-FHS) with a
moving-block-bootstrap interval, using the study's own 22-day block. The margins are the
protocol's proposals: about 5% of GARCH-FHS's score in Finding 15 (3.92 bp at 99%, 8.22 bp at
97.5%).

New closes arrive as a `date,close` CSV whose SHA-256 the caller states in advance; the file is
hashed and parsed from the same bytes.
"""

from __future__ import annotations

import csv
import hashlib
import io
import math
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import numpy as np

from prometheus.confirmatory.intervals import (
    block_interval,
    classify_effect,
    exact_binomial_interval,
)
from prometheus.data_ingestion.kaggle_sp500 import load_daily_closes, log_returns
from prometheus.neural_sde.benchmark import fit_garch11
from prometheus.orchestration.market_risk_study import (
    ALPHAS,
    BLOCK_LENGTH,
    HS_WINDOW,
    TRAIN_END,
    backtest_var,
    rolling_historical_thresholds,
)
from prometheus.titan.risk_metrics import quantile_score

SPLICED_PATH = (
    Path(__file__).resolve().parents[3] / "data_cache" / "kaggle_sp500_spliced_daily_close.csv"
)
PRIMARY_ALPHA = 0.99
MARGIN_BP = {0.99: 0.2, 0.975: 0.4}
N_RESAMPLES = 10_000
BOOTSTRAP_SEED = 1


@dataclass(frozen=True)
class Forecasts:
    """Per-day VaR thresholds (a return below the threshold is an exceedance), every day."""

    return_dates: tuple[date, ...]
    returns: np.ndarray
    garch_fhs: dict[float, np.ndarray]
    historical_250: dict[float, np.ndarray]


def forecast_thresholds(dates: tuple[date, ...], closes: np.ndarray) -> Forecasts:
    """GARCH-FHS and 250-day historical-simulation thresholds, as the study computes them."""
    returns = log_returns(closes)
    return_dates = dates[1:]
    train = np.array([d < TRAIN_END for d in return_dates])
    garch = fit_garch11(returns[train])
    sigma = np.sqrt(garch.conditional_variances(returns))
    standardised = (returns[train] - garch.mu) / sigma[train]
    return Forecasts(
        return_dates=return_dates,
        returns=returns,
        garch_fhs={a: garch.mu + sigma * float(np.quantile(standardised, 1.0 - a)) for a in ALPHAS},
        historical_250={a: rolling_historical_thresholds(returns, HS_WINDOW, a) for a in ALPHAS},
    )


def parse_new_closes(content: bytes, expected_sha256: str) -> tuple[tuple[date, ...], np.ndarray]:
    """Dates and closes of a `date,close` CSV (ISO dates), after checking its SHA-256."""
    digest = hashlib.sha256(content).hexdigest()
    if digest != expected_sha256.strip().lower():
        raise ValueError(
            f"the new closes file does not match the SHA-256 stated for it "
            f"(file {digest}, stated {expected_sha256}); nothing was read"
        )
    dates: list[date] = []
    closes: list[float] = []
    reader = csv.DictReader(io.StringIO(content.decode("utf-8")))
    if reader.fieldnames is None or {"date", "close"} - set(reader.fieldnames):
        raise ValueError("the new closes file must have the columns date,close")
    for row in reader:
        try:
            dates.append(date.fromisoformat(row["date"]))
            closes.append(float(row["close"]))
        except (ValueError, TypeError) as exc:
            raise ValueError(f"malformed row in the new closes file: {row!r}") from exc
    if not dates:
        raise ValueError("the new closes file is empty")
    if any(b <= a for a, b in zip(dates, dates[1:], strict=False)):
        raise ValueError("new dates must be strictly increasing")
    if not all(math.isfinite(c) and c > 0 for c in closes):
        raise ValueError("new closes must be finite and positive")
    return tuple(dates), np.asarray(closes, dtype=np.float64)


def load_new_closes(path: Path, expected_sha256: str) -> tuple[tuple[date, ...], np.ndarray]:
    return parse_new_closes(path.read_bytes(), expected_sha256)


def merge_closes(
    old: tuple[tuple[date, ...], np.ndarray], new: tuple[tuple[date, ...], np.ndarray]
) -> tuple[tuple[date, ...], np.ndarray]:
    """Old closes followed by new ones; the new file may not overlap or precede the old series."""
    if new[0][0] <= old[0][-1]:
        raise ValueError(
            f"new closes must start after {old[0][-1].isoformat()}, "
            f"but the file starts at {new[0][0].isoformat()}"
        )
    return old[0] + new[0], np.concatenate([old[1], new[1]])


def committed_closes() -> tuple[tuple[date, ...], np.ndarray]:
    """The committed spliced S&P 500 series (the OLD data; last day 2023-05-03)."""
    return load_daily_closes(SPLICED_PATH)


def first_untouched_day() -> date:
    return committed_closes()[0][-1] + timedelta(days=1)


def coverage_report(
    returns: np.ndarray, thresholds: np.ndarray, alpha: float, confidence: float
) -> dict[str, Any]:
    """The study's backtest plus the exact binomial interval for the exceedance rate and the
    protocol's reading of it."""
    report = backtest_var(returns, thresholds, alpha)
    exceedances, days = int(report["n_exceedances"]), int(report["n_days"])
    low, high = exact_binomial_interval(exceedances, days, confidence)
    nominal = 1.0 - alpha
    test_level = 1.0 - confidence
    return {
        **report,
        "nominal_rate": nominal,
        "rate_interval": [low, high],
        "rate_interval_confidence": confidence,
        "conditional_coverage_test_level": test_level,
        "consistent_with_coverage": bool(
            low <= nominal <= high and report["conditional_coverage_p"] >= test_level
        ),
    }


def pinball_difference(
    returns: np.ndarray, first: np.ndarray, second: np.ndarray, alpha: float
) -> np.ndarray:
    """Per-day pinball loss of `first` minus that of `second`, in basis points of return."""
    return np.asarray(
        (quantile_score(-returns, -first, alpha) - quantile_score(-returns, -second, alpha)) * 1e4,
        dtype=np.float64,
    )


def analyse_window(
    dates: tuple[date, ...],
    closes: np.ndarray,
    *,
    scored_from: date,
    scored_to: date | None,
    confidence: float,
    n_resamples: int = N_RESAMPLES,
    seed: int = BOOTSTRAP_SEED,
) -> dict[str, Any]:
    """Score the days in `[scored_from, scored_to]` (inclusive)."""
    forecasts = forecast_thresholds(dates, closes)
    window = np.array(
        [d >= scored_from and (scored_to is None or d <= scored_to) for d in forecasts.return_dates]
    )
    n = int(window.sum())
    if n < 2:
        raise ValueError(f"only {n} day(s) fall in the scored window; need at least 2")
    scored_dates = [d for d, keep in zip(forecasts.return_dates, window, strict=True) if keep]
    returns = forecasts.returns[window]
    coverage: dict[str, Any] = {}
    pinball: dict[str, Any] = {}
    for alpha in ALPHAS:
        fhs = forecasts.garch_fhs[alpha][window]
        hist = forecasts.historical_250[alpha][window]
        if not (np.all(np.isfinite(fhs)) and np.all(np.isfinite(hist))):
            raise ValueError("a VaR threshold in the scored window is not finite")
        coverage[f"alpha_{alpha}"] = {
            "garch_fhs": coverage_report(returns, fhs, alpha, confidence),
            "historical_250": coverage_report(returns, hist, alpha, confidence),
        }
        difference = pinball_difference(returns, hist, fhs, alpha)
        interval = block_interval(
            difference,
            block_length=min(BLOCK_LENGTH, n),
            confidence=confidence,
            n_resamples=n_resamples,
            seed=seed,
        )
        pinball[f"alpha_{alpha}"] = {
            "statistic": "mean pinball loss (historical_250 minus garch_fhs), basis points; "
            "positive favours GARCH-FHS",
            "margin_bp": MARGIN_BP[alpha],
            "interval": interval.as_dict(),
            "outcome": classify_effect(interval, MARGIN_BP[alpha]),
        }
    return {
        "endpoint": "E3",
        "primary_alpha": PRIMARY_ALPHA,
        "n_days": n,
        "first_day": scored_dates[0].isoformat(),
        "last_day": scored_dates[-1].isoformat(),
        "coverage": coverage,
        "pinball_difference": pinball,
        "primary_reading": coverage[f"alpha_{PRIMARY_ALPHA}"]["garch_fhs"][
            "consistent_with_coverage"
        ],
    }
