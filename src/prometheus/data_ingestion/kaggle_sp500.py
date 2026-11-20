"""Daily S&P 500 closing prices, 1927-12-30 .. 2020-11-04, from the Kaggle dataset
`henryhan117/sp-500-historical-data` (Yahoo Finance ^GSPC, ODbL-1.0): the real
market-return series the financial-risk models are evaluated on.

Two properties of the raw file matter for any consumer and are disclosed here
rather than papered over:

- Before 1983-07 the file has Open = High = Low = Close (a close-only era), so
  only CLOSE-based quantities (returns, realised volatility, VaR) are
  meaningful there -- never intraday range estimators.
- `Adj Close` equals `Close` on every row (an index has no dividends to adjust
  for); the snapshot therefore stores `Close` only. Returns here are PRICE
  returns, not total returns.

The committed `data_cache/kaggle_sp500_daily_close.csv` is derived by
`kaggle_build.write_close_csv`; loading makes no network call.
"""

from __future__ import annotations

import math
from datetime import date
from pathlib import Path

import numpy as np

from prometheus.data_ingestion.snapshot_integrity import SnapshotParseError, verified_dict_reader

KAGGLE_SP500_SOURCE_URL = "https://www.kaggle.com/datasets/henryhan117/sp-500-historical-data"
KAGGLE_SP500_SOURCE_LICENSE = "ODbL-1.0 (Kaggle: henryhan117/sp-500-historical-data)"


def load_daily_closes(path: Path, label: str = "S&P 500") -> tuple[tuple[date, ...], np.ndarray]:
    """Dates (ascending, unique) and closing levels of a `date,close` snapshot. Every close
    must be a finite, positive number: `nan` compares false against everything, so a plain
    `c <= 0` test would have let it through."""
    dates: list[date] = []
    closes: list[float] = []
    for row in verified_dict_reader(path, required=("date", "close")):
        try:
            dates.append(date.fromisoformat(row["date"]))
            closes.append(float(row["close"]))
        except ValueError as exc:
            raise SnapshotParseError(f"{path.name}: malformed row {row!r}") from exc
    if any(b <= a for a, b in zip(dates, dates[1:], strict=False)):
        raise ValueError(f"{label} dates must be strictly increasing")
    if not all(math.isfinite(c) and c > 0 for c in closes):
        raise ValueError(f"{label} closes must be finite and positive")
    return tuple(dates), np.asarray(closes, dtype=np.float64)


def load_sp500_closes(path: Path) -> tuple[tuple[date, ...], np.ndarray]:
    """The S&P 500 snapshot (`load_daily_closes` with its own label)."""
    return load_daily_closes(path, "S&P 500")


def log_returns(closes: np.ndarray) -> np.ndarray:
    """Daily log returns; element i is the return from close i to close i+1."""
    if closes.ndim != 1 or closes.size < 2:
        raise ValueError("closes must be a 1-D array with at least two prices")
    return np.diff(np.log(closes))
