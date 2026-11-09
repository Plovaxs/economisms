"""Real US macro indicators from Kaggle (GDP, unemployment claims,
the Fed funds rate, M2, NASDAQ), closing a gap this repository has
disclosed since DAT-02..04 were first scoped: no real GDP/unemployment/
rate series existed anywhere here (no usable FRED API key in this
environment), so `recessionnet`'s factor-based features and Q-MACRO's
Mkt-RF target were the closest available honest substitutes. This
module uses the Kaggle dataset `mikoajfish99/us-recession-and-
financial-indicators` (ODbL-1.0), itself built from real FRED series
(GDP, CCSA, DFF, WM2NS) plus a bundled NASDAQ daily price history --
giving this repository, for the first time, real GDP growth and real
unemployment-claims growth as RECESSIONNET features, directly
answering the blueprint's own original "GDP, rates, unemployment"
framing rather than a market-factor proxy for it.

The committed `data_cache/kaggle_us_macro_monthly.csv` is a derived,
cleaned snapshot (see its sibling `.meta.json` for exact provenance,
the resampling method, and the fixed per-series publication-lag
assumption applied before committing it) -- this module only loads
that already-clean grid; it does not parse the raw Kaggle CSVs'
vendor-specific quirks (comma-decimal separators, thousands commas),
which were handled once in an uncommitted one-off prep script (see
this module's PR ledger entry for that script's exact logic).

Every series here is already in the SAME "percent units" convention
`french_factors.py`'s Mkt-RF/SMB/HML/RF already use (e.g. 5.2 meaning
5.2%), so `recessionnet.dataset.build_recession_dataset`'s existing
fixed /100 feature scale applies unchanged -- no new scaling code was
needed to reuse every existing RECESSIONNET/Q-MACRO primitive as-is.
"""

from __future__ import annotations

import calendar
import csv
from datetime import date
from pathlib import Path

from prometheus.econosim.pit import MacroObservation

KAGGLE_SOURCE_LICENSE = "ODbL-1.0 (Kaggle: mikoajfish99/us-recession-and-financial-indicators)"
KAGGLE_SOURCE_URL = "https://www.kaggle.com/datasets/mikoajfish99/us-recession-and-financial-indicators"
KAGGLE_SERIES_IDS: tuple[str, ...] = (
    "KAGGLE_GDP_YOY",
    "KAGGLE_CLAIMS_YOY",
    "KAGGLE_FEDFUNDS",
    "KAGGLE_M2_YOY",
    "KAGGLE_NASDAQ_YOY",
)
_COLUMN_NAMES: tuple[str, ...] = ("GDP_YOY", "CLAIMS_YOY", "FEDFUNDS", "M2_YOY", "NASDAQ_YOY")


def load_kaggle_us_macro_observations(path: Path) -> list[MacroObservation]:
    """Loads the committed monthly grid into `MacroObservation`s, one
    per (month, series). `published_at` is set equal to
    `observation_at`: the documented per-series publication lag was
    already applied when the grid was built (see the `.meta.json`
    sidecar), so by construction every value in this file is honestly
    knowable as of its own recorded month."""
    observations: list[MacroObservation] = []
    with path.open() as f:
        for row in csv.DictReader(f):
            year, month = int(row["date"][:4]), int(row["date"][4:6])
            observation_at = date(year, month, calendar.monthrange(year, month)[1])
            for column, series_id in zip(_COLUMN_NAMES, KAGGLE_SERIES_IDS, strict=True):
                observations.append(
                    MacroObservation(
                        series_id=series_id,
                        observation_at=observation_at,
                        published_at=observation_at,
                        value=float(row[column]),
                        source_url=KAGGLE_SOURCE_URL,
                        source_license=KAGGLE_SOURCE_LICENSE,
                        frequency="M",
                    )
                )
    return observations
