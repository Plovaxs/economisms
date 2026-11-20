"""Monthly US consumer-price index levels, 1947-1 .. 2023-3, from the Kaggle backbone dataset
`mikoajfish99/us-recession-and-financial-indicators` (FRED `CPIAUCSL`, seasonally adjusted,
ODbL-1.0).

Why LEVELS: the year-over-year inflation rate is an arithmetic function of two index levels,
`YoY_t = I_t / I_{t-12} - 1`, so one month's YoY differs from the previous month's by exactly the
new month's growth minus the growth of the month that just dropped out of the window. Only the
index levels expose that "base effect"; the extended macro grid keeps the YoY rate alone.

Point-in-time convention (the repository's own, see `kaggle_build`): the level of month `m` is
first knowable 15 days after `m` ends and is stored on the first month-end at or after that
moment, so **row `r` holds the index of month `r - 1`**. `load_cpi_index` undoes the shift and
returns each level against the month it measures.

Caveat disclosed rather than hidden: `CPIAUCSL` is the seasonally adjusted series as it stands
TODAY. Seasonal factors are re-estimated for several years after the fact, so a level in this file
may differ slightly from what was published at the time (the real-time vintage is not reachable
from this environment).
"""

from __future__ import annotations

import calendar
import math
from datetime import date
from pathlib import Path

import numpy as np

from prometheus.data_ingestion.snapshot_integrity import SnapshotParseError, verified_dict_reader

CPI_INDEX_COLUMN = "CPI_INDEX_SA"
CPI_PUBLICATION_LAG_DAYS = 15
"""The same fixed, documented assumption `inflationcast.data` makes for the BLS series."""


def _month_end(year: int, month: int) -> date:
    return date(year, month, calendar.monthrange(year, month)[1])


def load_cpi_index(path: Path) -> tuple[tuple[date, ...], np.ndarray]:
    """(month-end of each MEASURED month, index level), consecutive months, ascending."""
    months: list[date] = []
    levels: list[float] = []
    for row in verified_dict_reader(path, required=("date", CPI_INDEX_COLUMN)):
        try:
            year, month = int(row["date"][:4]), int(row["date"][4:6])
            level = float(row[CPI_INDEX_COLUMN])
            effective = year * 12 + (month - 1)
            measured = effective - 1  # the row holds the PREVIOUS month's index
            months.append(_month_end(measured // 12, measured % 12 + 1))
        except (ValueError, IndexError) as exc:
            raise SnapshotParseError(f"{path.name}: malformed row {row!r}") from exc
        levels.append(level)
    if not months:
        raise ValueError("the CPI index snapshot is empty")
    if not all(math.isfinite(x) and x > 0 for x in levels):
        raise ValueError("CPI index levels must be finite and positive")
    indices = [m.year * 12 + m.month for m in months]
    if any(b - a != 1 for a, b in zip(indices, indices[1:], strict=False)):
        raise ValueError("CPI index months must be consecutive")
    return tuple(months), np.asarray(levels, dtype=np.float64)
