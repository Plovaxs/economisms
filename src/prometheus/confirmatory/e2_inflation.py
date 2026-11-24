"""E2: the 12-month base-effect rule against persistence of the year-over-year rate (Finding 18).

Both forecasters are `orchestration.inflationcast_long_study`'s own, imported unchanged: persistence
is the previous month's year-over-year rate (`NowcastData.previous_yoy`); the base-effect rule is
`base_mean12`, which forecasts this month's growth as the mean of the previous twelve and
converts it with the exact identity `yoy_from_mom`. Nothing is fitted, so there is nothing to tune
on the scored months. The only code written here builds that study's `NowcastData` from a list
of index levels (the study builds it from a file and a macro grid; the tests prove the two agree
on the committed data) and scores a window of target months.

Statistic: `d_t = |e_persistence| - |e_rule|` in percentage points of year-over-year inflation, so a
positive mean `theta` favours the rule; a moving-block-bootstrap interval at the protocol's
confidence level; the protocol's equivalence margin `MARGIN` (0.03 percentage points, about 10% of
persistence's 0.326 pp test error in Finding 18). Margin, block length and resample count are
proposals the maintainer confirms at the freeze; the sensitivity block lengths are reported, never
decisive.

New observations arrive as a `month,level` CSV whose SHA-256 the caller states in advance: the file
is hashed and parsed from the same bytes, so what is checked is what is read.
"""

from __future__ import annotations

import csv
import hashlib
import io
import math
from datetime import date
from pathlib import Path
from typing import Any

import numpy as np

from prometheus.confirmatory.intervals import block_interval, classify_effect
from prometheus.data_ingestion.kaggle_cpi_index import load_cpi_index
from prometheus.orchestration.inflationcast_long_study import (
    CPI_PATH,
    N_LAGS,
    NowcastData,
    base_effect_forecast,
    yoy_from_mom,
)

MARGIN = 0.03
BLOCK_LENGTH = 3
SENSITIVITY_BLOCK_LENGTHS = (6, 12)
N_RESAMPLES = 10_000
BOOTSTRAP_SEED = 1


def _month_end(year: int, month: int) -> date:
    if not 1 <= month <= 12:
        raise ValueError(f"month must be 1-12, got {month}")
    first_of_next = date(year + (month == 12), month % 12 + 1, 1)
    return date.fromordinal(first_of_next.toordinal() - 1)


def _next_month_end(d: date) -> date:
    return _month_end(d.year + (d.month == 12), d.month % 12 + 1)


def nowcast_data_from_levels(months: tuple[date, ...], levels: np.ndarray) -> NowcastData:
    """The CPI half of `inflationcast_long_study.build_nowcast_data`: one row per TARGET month,
    holding only what is known at the end of that month. The macro grid is not needed by the two
    rules scored here, so it is left empty."""
    n = len(levels)
    if n != len(months) or n < N_LAGS + 2:
        raise ValueError(f"need at least {N_LAGS + 2} consecutive months of index levels")
    mom = np.full(n, np.nan)
    mom[1:] = 100.0 * (levels[1:] / levels[:-1] - 1.0)
    yoy = np.full(n, np.nan)
    yoy[12:] = 100.0 * (levels[12:] / levels[:-12] - 1.0)
    rows = np.arange(N_LAGS + 1, n)
    history = np.stack([mom[rows - N_LAGS + k] for k in range(N_LAGS)], axis=1)
    return NowcastData(
        months=tuple(months[i] for i in rows),
        yoy=yoy[rows],
        mom=mom[rows],
        previous_yoy=yoy[rows - 1],
        base_level=levels[rows - 1],
        year_ago_level=levels[rows - 12],
        mom_history=history,
        macro={},
    )


def parse_new_levels(content: bytes, expected_sha256: str) -> tuple[tuple[date, ...], np.ndarray]:
    """Months and levels of a `month,level` CSV (`YYYY-MM,level`), after checking its SHA-256."""
    digest = hashlib.sha256(content).hexdigest()
    if digest != expected_sha256.strip().lower():
        raise ValueError(
            f"the new CPI file does not match the SHA-256 stated for it "
            f"(file {digest}, stated {expected_sha256}); nothing was read"
        )
    months: list[date] = []
    levels: list[float] = []
    reader = csv.DictReader(io.StringIO(content.decode("utf-8")))
    if reader.fieldnames is None or {"month", "level"} - set(reader.fieldnames):
        raise ValueError("the new CPI file must have the columns month,level")
    for row in reader:
        try:
            year, month = (int(part) for part in row["month"].split("-"))
            level = float(row["level"])
            months.append(_month_end(year, month))
        except (ValueError, AttributeError) as exc:
            raise ValueError(f"malformed row in the new CPI file: {row!r}") from exc
        levels.append(level)
    if not months:
        raise ValueError("the new CPI file is empty")
    if not all(math.isfinite(x) and x > 0 for x in levels):
        raise ValueError("new CPI levels must be finite and positive")
    return tuple(months), np.asarray(levels, dtype=np.float64)


def load_new_levels(path: Path, expected_sha256: str) -> tuple[tuple[date, ...], np.ndarray]:
    return parse_new_levels(path.read_bytes(), expected_sha256)


def merge_levels(
    old: tuple[tuple[date, ...], np.ndarray], new: tuple[tuple[date, ...], np.ndarray]
) -> tuple[tuple[date, ...], np.ndarray]:
    """Old months followed by new ones. The new file must start with the month after the old
    series' last month and have no gaps: overlap would let a revision of an already-read month
    in, and a gap would silently turn a 12-month window into a longer one."""
    old_months, old_levels = old
    new_months, new_levels = new
    if new_months[0] != _next_month_end(old_months[-1]):
        raise ValueError(
            f"the new series must start the month after {old_months[-1]:%Y-%m}, "
            f"but starts at {new_months[0]:%Y-%m}"
        )
    for previous, current in zip(new_months, new_months[1:], strict=False):
        if current != _next_month_end(previous):
            raise ValueError(f"the new series skips a month after {previous:%Y-%m}")
    return old_months + new_months, np.concatenate([old_levels, new_levels])


def analyse_window(
    months: tuple[date, ...],
    levels: np.ndarray,
    *,
    scored_from: date,
    scored_to: date | None,
    confidence: float,
    margin: float = MARGIN,
    block_length: int = BLOCK_LENGTH,
    n_resamples: int = N_RESAMPLES,
    seed: int = BOOTSTRAP_SEED,
    sensitivity_block_lengths: tuple[int, ...] = SENSITIVITY_BLOCK_LENGTHS,
) -> dict[str, Any]:
    """Score target months in `[scored_from, scored_to]` (month ends, inclusive)."""
    data = nowcast_data_from_levels(months, levels)
    scored = np.array(
        [m >= scored_from and (scored_to is None or m <= scored_to) for m in data.months]
    )
    n = int(scored.sum())
    if n < 2:
        raise ValueError(f"only {n} target month(s) fall in the scored window; need at least 2")
    persistence = data.previous_yoy
    rule = yoy_from_mom(data, base_effect_forecast(data, "base_mean12"))
    e_persistence = persistence[scored] - data.yoy[scored]
    e_rule = rule[scored] - data.yoy[scored]
    if not (np.all(np.isfinite(e_persistence)) and np.all(np.isfinite(e_rule))):
        raise ValueError("a forecast error is not finite; the series is malformed")
    difference = np.abs(e_persistence) - np.abs(e_rule)
    primary = block_interval(
        difference,
        block_length=block_length,
        confidence=confidence,
        n_resamples=n_resamples,
        seed=seed,
    )
    sensitivity = {
        str(length): block_interval(
            difference,
            block_length=length,
            confidence=confidence,
            n_resamples=n_resamples,
            seed=seed,
        ).as_dict()
        for length in sensitivity_block_lengths
        if length <= n
    }
    scored_months = [m for m, keep in zip(data.months, scored, strict=True) if keep]
    return {
        "endpoint": "E2",
        "statistic": "theta = mean(|e_persistence| - |e_base_effect|) in percentage points of "
        "year-over-year inflation; positive favours the base-effect rule",
        "n_months": n,
        "first_month": scored_months[0].isoformat(),
        "last_month": scored_months[-1].isoformat(),
        "mae_persistence": float(np.mean(np.abs(e_persistence))),
        "mae_base_effect": float(np.mean(np.abs(e_rule))),
        "margin": margin,
        "interval": primary.as_dict(),
        "outcome": classify_effect(primary, margin),
        "sensitivity": sensitivity,
        "per_month": [
            {
                "month": m.isoformat(),
                "yoy": float(y),
                "persistence": float(p),
                "base_effect": float(r),
            }
            for m, y, p, r in zip(
                scored_months, data.yoy[scored], persistence[scored], rule[scored], strict=True
            )
        ],
    }


def committed_levels() -> tuple[tuple[date, ...], np.ndarray]:
    """The committed snapshot's months and levels (the OLD data; last measured month 2023-03)."""
    return load_cpi_index(CPI_PATH)


def first_untouched_month() -> date:
    """The first target month after the committed snapshot's last measured month."""
    return _next_month_end(committed_levels()[0][-1])
