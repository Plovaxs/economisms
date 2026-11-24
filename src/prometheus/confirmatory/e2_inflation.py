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

A new series arrives as a `month,level` CSV whose SHA-256 the caller states in advance: the file
is hashed and parsed from the same bytes, so what is checked is what is read. It is scored ON ITS
OWN, as one vintage: it starts early enough to give the first scored month its twelve months of
history, and it is not joined to the committed series, because seasonally adjusted indexes are
revised and a join would put a revision artefact into the first scored month. `vintage_overlap`
reports how far the two differ on the months they share.
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

from prometheus.confirmatory.intervals import Interval, block_interval, classify_effect
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
            text = row["level"].strip()
            level = float("nan") if text == "" else float(text)  # blank: BLS published no value
            months.append(_month_end(year, month))
        except (ValueError, AttributeError) as exc:
            raise ValueError(f"malformed row in the new CPI file: {row!r}") from exc
        levels.append(level)
    if not months:
        raise ValueError("the new CPI file is empty")
    if not all(math.isnan(x) or (math.isfinite(x) and x > 0) for x in levels):
        raise ValueError("new CPI levels must be finite and positive (or blank for a gap)")
    indices = [m.year * 12 + m.month for m in months]
    if any(b - a != 1 for a, b in zip(indices, indices[1:], strict=False)):
        raise ValueError("the new CPI months must be consecutive (a gap is a blank level)")
    return tuple(months), np.asarray(levels, dtype=np.float64)


def load_new_levels(path: Path, expected_sha256: str) -> tuple[tuple[date, ...], np.ndarray]:
    return parse_new_levels(path.read_bytes(), expected_sha256)


def vintage_overlap(
    committed: tuple[tuple[date, ...], np.ndarray], series: tuple[tuple[date, ...], np.ndarray]
) -> dict[str, Any]:
    """How far the new series differs from the committed one on the months both contain.

    Seasonally adjusted indexes are revised, so a series downloaded now is a different VINTAGE
    from the committed one. Joining the two would put a revision artefact into the first scored
    month, so the endpoint scores a single-vintage series on its own and reports this difference
    instead: the size of the revisions, on months the repository has already read."""
    old = dict(zip(committed[0], committed[1].tolist(), strict=True))
    new = {m: v for m, v in zip(series[0], series[1].tolist(), strict=True) if not math.isnan(v)}
    shared = sorted(set(old) & set(new))
    if not shared:
        return {"n_overlap_months": 0}
    relative = np.array([abs(new[m] - old[m]) / old[m] for m in shared])
    return {
        "n_overlap_months": len(shared),
        "first_overlap_month": shared[0].isoformat(),
        "last_overlap_month": shared[-1].isoformat(),
        "max_relative_difference": float(relative.max()),
        "mean_relative_difference": float(relative.mean()),
    }


def impute_single_gaps(levels: np.ndarray) -> np.ndarray:
    """Replace each isolated missing level by the geometric mean of its two neighbours.

    A SENSITIVITY device only (the primary analysis never invents a level); longer gaps stay
    missing."""
    filled = levels.copy()
    for i in range(1, len(levels) - 1):
        if (
            math.isnan(levels[i])
            and not math.isnan(levels[i - 1])
            and not math.isnan(levels[i + 1])
        ):
            filled[i] = math.sqrt(levels[i - 1] * levels[i + 1])
    return filled


def _score_window(
    months: tuple[date, ...],
    levels: np.ndarray,
    scored_from: date,
    scored_to: date | None,
) -> dict[str, Any]:
    """Errors of both rules over the scored window; a target month that needs a missing level is
    EXCLUDED and listed, never dropped silently."""
    data = nowcast_data_from_levels(months, levels)
    in_window = np.array(
        [m >= scored_from and (scored_to is None or m <= scored_to) for m in data.months]
    )
    window_months = [m for m, keep in zip(data.months, in_window, strict=True) if keep]
    if not window_months:
        raise ValueError("no target month falls in the scored window")
    first_wanted = _month_end(scored_from.year, scored_from.month)
    if window_months[0] != first_wanted:
        raise ValueError(
            f"the series supports target months only from {window_months[0]:%Y-%m}, "
            f"but the scored window starts at {first_wanted:%Y-%m}: it needs "
            f"{N_LAGS + 1} months of index levels before the first scored month"
        )
    persistence = data.previous_yoy
    rule = yoy_from_mom(data, base_effect_forecast(data, "base_mean12"))
    usable = in_window & np.isfinite(persistence) & np.isfinite(rule) & np.isfinite(data.yoy)
    excluded = [m for m, w, u in zip(data.months, in_window, usable, strict=True) if w and not u]
    e_persistence = persistence[usable] - data.yoy[usable]
    e_rule = rule[usable] - data.yoy[usable]
    return {
        "data": data,
        "usable": usable,
        "usable_months": [m for m, u in zip(data.months, usable, strict=True) if u],
        "excluded": excluded,
        "n_window": len(window_months),
        "persistence": persistence,
        "rule": rule,
        "difference": np.abs(e_persistence) - np.abs(e_rule),
        "e_persistence": e_persistence,
        "e_rule": e_rule,
    }


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
    """Score target months in `[scored_from, scored_to]` (month ends, inclusive) of ONE series.

    The series must reach back far enough that every scored month has its twelve months of growth
    history; a window that would silently lose its first months is refused. A target month that
    needs a missing index level is excluded and listed (`excluded_months`); if the series has gaps,
    `sensitivity_imputed` repeats the endpoint with each isolated gap filled by interpolation."""
    scored = _score_window(months, levels, scored_from, scored_to)
    difference = scored["difference"]
    n = int(difference.size)
    if n < 2:
        raise ValueError(f"only {n} target month(s) fall in the scored window; need at least 2")

    def interval(sample: np.ndarray, length: int) -> Interval:
        return block_interval(
            sample,
            block_length=length,
            confidence=confidence,
            n_resamples=n_resamples,
            seed=seed,
        )

    primary = interval(difference, block_length)
    report: dict[str, Any] = {
        "endpoint": "E2",
        "statistic": "theta = mean(|e_persistence| - |e_base_effect|) in percentage points of "
        "year-over-year inflation; positive favours the base-effect rule",
        "n_months": n,
        "n_months_in_window": scored["n_window"],
        "excluded_months": [m.isoformat() for m in scored["excluded"]],
        "excluded_because": "a target month is excluded when the index level it needs is missing",
        "first_month": scored["usable_months"][0].isoformat(),
        "last_month": scored["usable_months"][-1].isoformat(),
        "mae_persistence": float(np.mean(np.abs(scored["e_persistence"]))),
        "mae_base_effect": float(np.mean(np.abs(scored["e_rule"]))),
        "margin": margin,
        "interval": primary.as_dict(),
        "outcome": classify_effect(primary, margin),
        "sensitivity": {
            str(length): interval(difference, length).as_dict()
            for length in sensitivity_block_lengths
            if length <= n
        },
        "per_month": [
            {
                "month": m.isoformat(),
                "yoy": float(y),
                "persistence": float(p),
                "base_effect": float(r),
            }
            for m, y, p, r in zip(
                scored["usable_months"],
                scored["data"].yoy[scored["usable"]],
                scored["persistence"][scored["usable"]],
                scored["rule"][scored["usable"]],
                strict=True,
            )
        ],
    }
    if np.isnan(levels).any():
        filled = _score_window(months, impute_single_gaps(levels), scored_from, scored_to)
        diff = filled["difference"]
        if diff.size >= 2:
            imputed = interval(diff, min(block_length, int(diff.size)))
            report["sensitivity_imputed"] = {
                "note": "each isolated missing level replaced by the geometric mean of its "
                "neighbours; a sensitivity analysis, never decisive",
                "n_months": int(diff.size),
                "excluded_months": [m.isoformat() for m in filled["excluded"]],
                "interval": imputed.as_dict(),
                "outcome": classify_effect(imputed, margin),
            }
    return report


def committed_levels() -> tuple[tuple[date, ...], np.ndarray]:
    """The committed snapshot's months and levels (the OLD data; last measured month 2023-03)."""
    return load_cpi_index(CPI_PATH)


def first_untouched_month() -> date:
    """The first target month after the committed snapshot's last measured month."""
    return _next_month_end(committed_levels()[0][-1])
