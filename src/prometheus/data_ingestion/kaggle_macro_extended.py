"""Extended real US macro-financial features from the SAME Kaggle dataset the
PR-145 snapshot came from (`mikoajfish99/us-recession-and-financial-indicators`,
ODbL-1.0): unemployment, seasonally adjusted CPI inflation, bank-credit growth,
S&P 500 return and realised volatility, plus the three series PR-145 already
used (GDP, claims, Fed funds) re-derived by the committed, tested builder
(`kaggle_build`) so a longer history than PR-145's 1981-12 start is available.

The committed `data_cache/kaggle_us_macro_extended_monthly.csv` is derived from
the raw Kaggle files by `kaggle_build.build_extended_macro_grid` (see its
`.meta.json` for the raw files' SHA-256 digests, the fixed publication-lag
assumption per series and the computed sanity checks). Values are already
re-keyed to the month they became knowable, so `published_at == observation_at`
-- the same convention `kaggle_macro` uses. Cells that do not exist yet (the S&P
500 history starts in 1980, bank credit in 1974) are blank and simply produce no
observation: unlike `kaggle_macro`, this grid is not rectangular, so a consumer
asks for the series it needs and trims to their common months.

The source URL/licence are those of `kaggle_macro` (same dataset) and are
reused rather than redeclared, so the source catalogue lists the dataset once.
"""

from __future__ import annotations

import calendar
import csv
from datetime import date
from pathlib import Path

from prometheus.data_ingestion.kaggle_macro import KAGGLE_SOURCE_LICENSE, KAGGLE_SOURCE_URL
from prometheus.econosim.pit import MacroObservation

EXTENDED_MACRO_COLUMNS: tuple[str, ...] = (
    "GDP_YOY",
    "CLAIMS_YOY",
    "FEDFUNDS",
    "UNRATE",
    "CPI_YOY_SA",
    "BANK_CREDIT_YOY",
    "SPX_YOY",
    "SPX_VOL",
)
SERIES_PREFIX = "KAGGLEX_"
EXTENDED_SERIES_IDS: tuple[str, ...] = tuple(SERIES_PREFIX + c for c in EXTENDED_MACRO_COLUMNS)


def series_id(column: str) -> str:
    if column not in EXTENDED_MACRO_COLUMNS:
        raise ValueError(f"unknown extended macro column {column!r}")
    return SERIES_PREFIX + column


def load_extended_macro_observations(
    path: Path, columns: tuple[str, ...] = EXTENDED_MACRO_COLUMNS
) -> list[MacroObservation]:
    """One observation per (month, requested column) that has a value."""
    unknown = [c for c in columns if c not in EXTENDED_MACRO_COLUMNS]
    if unknown:
        raise ValueError(f"unknown extended macro columns: {unknown}")
    observations: list[MacroObservation] = []
    with path.open() as handle:
        for row in csv.DictReader(handle):
            year, month = int(row["date"][:4]), int(row["date"][4:6])
            observation_at = date(year, month, calendar.monthrange(year, month)[1])
            for column in columns:
                if row[column] == "":
                    continue
                observations.append(
                    MacroObservation(
                        series_id=SERIES_PREFIX + column,
                        observation_at=observation_at,
                        published_at=observation_at,
                        value=float(row[column]),
                        source_url=KAGGLE_SOURCE_URL,
                        source_license=KAGGLE_SOURCE_LICENSE,
                        frequency="M",
                    )
                )
    return observations
