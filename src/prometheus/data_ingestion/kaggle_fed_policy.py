"""Monthly US monetary-policy variables from the Federal Reserve's own Kaggle
account (`federalreserve/interest-rates`, "Federal Reserve Interest Rates,
1954-Present", CC0): the effective federal funds rate, the unemployment rate,
the inflation rate and the quarterly real-GDP growth rate -- the variables of a
Taylor-type policy rule.

Coverage (read from the file, not assumed): effective rate and unemployment
1954-07 .. 2017-02, inflation 1958-01 .. 2017-02, real GDP growth quarterly
1954-07 .. 2016-10 (blank in the other months). The file ends in 2017.

Values are PERIOD-MATCHED (a row describes its own month) and are not shifted for
publication lags; the policy study applies its own one-month delay so that a rate
decision is only ever explained by data that existed when it was made.

The committed `data_cache/kaggle_fed_policy_monthly.csv` is derived by
`kaggle_build.build_fed_policy_grid`; loading makes no network call.
"""

from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from prometheus.data_ingestion.snapshot_integrity import verified_dict_reader

KAGGLE_FED_POLICY_SOURCE_URL = "https://www.kaggle.com/datasets/federalreserve/interest-rates"
KAGGLE_FED_POLICY_SOURCE_LICENSE = "CC0-1.0 (Kaggle: federalreserve/interest-rates)"
FED_COLUMNS: tuple[str, ...] = ("FFR_EFFECTIVE", "UNRATE", "INFLATION", "REAL_GDP_GROWTH")


@dataclass(frozen=True, slots=True)
class FedPolicyMonth:
    month_end: date
    ffr_effective: float | None
    unemployment: float | None
    inflation: float | None
    real_gdp_growth: float | None


def _cell(row: dict[str, str], column: str) -> float | None:
    return float(row[column]) if row[column] != "" else None


def load_fed_policy_months(path: Path) -> list[FedPolicyMonth]:
    months: list[FedPolicyMonth] = []
    for row in verified_dict_reader(path, required=("date", *FED_COLUMNS)):
        year, month = int(row["date"][:4]), int(row["date"][4:6])
        months.append(
            FedPolicyMonth(
                month_end=date(year, month, calendar.monthrange(year, month)[1]),
                ffr_effective=_cell(row, "FFR_EFFECTIVE"),
                unemployment=_cell(row, "UNRATE"),
                inflation=_cell(row, "INFLATION"),
                real_gdp_growth=_cell(row, "REAL_GDP_GROWTH"),
            )
        )
    return months
