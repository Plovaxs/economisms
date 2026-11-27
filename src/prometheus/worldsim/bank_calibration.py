"""Estimating the WORLDSIM bank block from real bank data (Finding 29).

Finding 28 left the banks almost entirely chosen and matched one credit series (bank credit of the
Fed's H.8 release, which includes securities) to the simulator's loans. This module compares the
simulated banking system with the FDIC's annual national totals (`data_ingestion.fdic_banks`): the
return on assets, the equity ratio, net loan charge-offs, loan growth and bank failures.

Annual rows, in the real data and in a simulated path alike, are built the same way:

- stocks (assets, equity, loans) at the year end; flows (net income, charge-offs) summed over the
  year and divided by the average of the opening and closing stock, so a growing system is not
  mistaken for a profitable one;
- `nco` is net charge-offs over average loans, `roa` is net income over average assets, `eq` the
  equity ratio at the year end, `growth` the percentage change of loans over the year, `failed`
  the assets of the institutions that failed in the year as a percentage of the assets at its start;
- `ugap` is the year's mean unemployment gap (a Hodrick-Prescott gap of monthly unemployment, the
  same filter on the real and the simulated series).

In a simulated path "loans" are the loans of every bank, failed or not (a failed bank's loans are
taken over; they do not leave the economy), which is how the real aggregate behaves.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import replace
from typing import Any

import numpy as np

from prometheus.worldsim.config import WorldConfig
from prometheus.worldsim.real_calibration import (
    BURN_IN,
    block_bootstrap_indices,
    build_table,
    credit_yoy_from_loans,
    distance,
    standard_errors,
    yoy_from_price_level,
)
from prometheus.worldsim.world import WorldPath

FIRST_YEAR = 1985
"""The first year with an opening stock (equity is reported from 1984)."""
LAST_YEAR = 2022
"""The last complete calendar year of the monthly unemployment data (which ends in 2023-01)."""
BANK_BLOCK = 3
"""Years per moving block when bootstrapping the annual rows."""

TARGETED_MOMENTS: tuple[str, ...] = (
    "roa_mean",
    "roa_sd",
    "eq_mean",
    "nco_mean",
    "nco_sd",
    "nco_corr_ugap",
    "growth_mean",
    "growth_sd",
    "growth_corr_ugap",
)
UNTARGETED_MOMENTS: tuple[str, ...] = (
    "failed_mean",
    "failed_years_over_1pct",
    "nco_max",
    "roa_min",
    "growth_min",
    "eq_sd",
    "loans_to_assets_mean",
)
BANK_PARAMETERS: tuple[tuple[str, float, float], ...] = (
    ("net_interest_margin", 0.0005, 0.0060),
    ("base_default_rate", 0.0001, 0.0060),
    ("default_sensitivity", 0.0, 1.0),
    ("payout_ratio", 0.0, 0.95),
    ("loan_growth_base", -0.002, 0.01),
    ("loan_growth_slope", 0.0, 0.02),
)
ANNUAL_COLUMNS: tuple[str, ...] = (
    "roa",
    "eq",
    "nco",
    "growth",
    "failed",
    "loans_to_assets",
    "ugap",
)


def _corr(a: np.ndarray, b: np.ndarray) -> float:
    if a.size < 3 or float(np.std(a)) < 1e-12 or float(np.std(b)) < 1e-12:
        return 0.0
    return float(np.corrcoef(a, b)[0, 1])


def annual_unemployment_gap(
    months: Sequence[tuple[int, int]], gap: np.ndarray, years: Sequence[int]
) -> np.ndarray:
    """The mean of the monthly gap over each calendar year (NaN for a year without 12 months).

    `gap` may be shorter than `months`: a table drops the months that have no lag, so its rows
    line up with the last `len(gap)` months."""
    aligned = list(months)[len(months) - len(gap) :]
    out = np.full(len(years), np.nan)
    for i, year in enumerate(years):
        values = [g for (y, _), g in zip(aligned, gap, strict=True) if y == year]
        if len(values) == 12:
            out[i] = float(np.mean(values))
    return out


def real_annual_table(
    bank: Mapping[int, Mapping[str, float | None]],
    failures: Mapping[int, Mapping[str, float]],
    ugap_by_year: Mapping[int, float],
    first: int = FIRST_YEAR,
    last: int = LAST_YEAR,
) -> dict[str, np.ndarray]:
    """The real annual rows `first` to `last` (see the module docstring for each column)."""
    years = [y for y in range(first, last + 1) if y in bank and (y - 1) in bank]

    def stock(year: int, name: str) -> float:
        value = bank[year][name]
        if value is None:
            raise ValueError(f"{name} is not reported for {year}")
        return float(value)

    rows: dict[str, list[float]] = {c: [] for c in ANNUAL_COLUMNS}
    for y in years:
        avg_assets = 0.5 * (stock(y, "assets") + stock(y - 1, "assets"))
        avg_loans = 0.5 * (stock(y, "loans") + stock(y - 1, "loans"))
        rows["roa"].append(100.0 * stock(y, "net_income") / avg_assets)
        rows["eq"].append(100.0 * stock(y, "equity") / stock(y, "assets"))
        rows["nco"].append(100.0 * stock(y, "net_charge_offs") / avg_loans)
        rows["growth"].append(100.0 * (stock(y, "loans") / stock(y - 1, "loans") - 1.0))
        rows["failed"].append(100.0 * failures[y]["failed_assets"] / stock(y - 1, "assets"))
        rows["loans_to_assets"].append(100.0 * stock(y, "loans") / stock(y, "assets"))
        rows["ugap"].append(float(ugap_by_year.get(y, np.nan)))
    table = {name: np.asarray(v, dtype=np.float64) for name, v in rows.items()}
    table["year"] = np.asarray(years, dtype=np.float64)
    return table


def annual_moments(
    table: Mapping[str, np.ndarray], index: np.ndarray | None = None
) -> dict[str, float]:
    """Targeted and untargeted moments of the annual rows (`index` selects a resample)."""
    t = {k: (v if index is None else v[index]) for k, v in table.items()}
    keep = np.isfinite(t["ugap"])
    ugap = t["ugap"][keep]
    return {
        "roa_mean": float(t["roa"].mean()),
        "roa_sd": float(t["roa"].std()),
        "eq_mean": float(t["eq"].mean()),
        "nco_mean": float(t["nco"].mean()),
        "nco_sd": float(t["nco"].std()),
        "nco_corr_ugap": _corr(t["nco"][keep], ugap),
        "growth_mean": float(t["growth"].mean()),
        "growth_sd": float(t["growth"].std()),
        "growth_corr_ugap": _corr(t["growth"][keep], ugap),
        "failed_mean": float(t["failed"].mean()),
        "failed_years_over_1pct": float(np.mean(t["failed"] > 1.0)),
        "nco_max": float(t["nco"].max()),
        "roa_min": float(t["roa"].min()),
        "growth_min": float(t["growth"].min()),
        "eq_sd": float(t["eq"].std()),
        "loans_to_assets_mean": float(t["loans_to_assets"].mean()),
    }


def annual_bootstrap(
    table: Mapping[str, np.ndarray],
    *,
    replications: int = 300,
    block: int = BANK_BLOCK,
    seed: int = 0,
) -> list[dict[str, float]]:
    """All annual moments on moving-block resamples of the years."""
    rng = np.random.default_rng(seed)
    n = int(table["roa"].size)
    block = min(block, n)
    out: list[dict[str, float]] = []
    for _ in range(replications):
        indices = block_bootstrap_indices(n, block, rng)
        value = annual_moments(table, indices)
        if all(np.isfinite(v) for v in value.values()):
            out.append(value)
    return out


def interval(replicates: list[dict[str, float]], name: str) -> tuple[float, float]:
    """The 95% percentile interval of one moment over the bootstrap replicates."""
    values = np.array([r[name] for r in replicates])
    return float(np.percentile(values, 2.5)), float(np.percentile(values, 97.5))


def simulated_annual_table(path: WorldPath, burn_in: int = BURN_IN) -> dict[str, np.ndarray]:
    """The annual rows of one simulated path: whole years from month `burn_in` on."""
    start = max(burn_in, 12)
    n = path.n_months
    years = (n - start) // 12
    if years < 3:
        raise ValueError("the path is too short for three annual rows")
    credit = path.bank_credit
    assets = path.bank_assets
    equity = path.bank_equity
    loans_operating = path.total_loans
    # a table drops its first 12 rows (lags), so start it a year early to align row i with month
    # `start + i`
    lead = start - 12
    table = build_table(
        path.unemployment[lead:],
        yoy_from_price_level(path.price_level)[lead:],
        path.policy_rate[lead:],
        path.asset_returns[lead:, 0],
        credit_yoy_from_loans(path.total_loans)[lead:],
    )
    monthly_gap = table["gap"]
    rows: dict[str, list[float]] = {c: [] for c in ANNUAL_COLUMNS}
    for k in range(years):
        a, b = start + 12 * k, start + 12 * (k + 1)  # months a..b-1; opening stock at a-1
        open_i, close_i = a - 1, b - 1
        avg_assets = 0.5 * (assets[open_i] + assets[close_i])
        avg_loans = 0.5 * (credit[open_i] + credit[close_i])
        rows["roa"].append(100.0 * path.bank_net_income[a:b].sum() / max(avg_assets, 1e-9))
        rows["eq"].append(100.0 * equity[close_i] / max(assets[close_i], 1e-9))
        rows["nco"].append(100.0 * path.bank_loan_losses[a:b].sum() / max(avg_loans, 1e-9))
        rows["growth"].append(100.0 * (credit[close_i] / max(credit[open_i], 1e-9) - 1.0))
        rows["failed"].append(
            100.0 * path.bank_failed_assets[a:b].sum() / max(assets[open_i], 1e-9)
        )
        rows["loans_to_assets"].append(
            100.0 * loans_operating[close_i] / max(assets[close_i], 1e-9)
        )
        rows["ugap"].append(float(np.mean(monthly_gap[12 * k : 12 * (k + 1)])))
    out = {name: np.asarray(v, dtype=np.float64) for name, v in rows.items()}
    out["year"] = np.arange(years, dtype=np.float64)
    return out


def simulated_annual_moments(path: WorldPath, burn_in: int = BURN_IN) -> dict[str, float]:
    return annual_moments(simulated_annual_table(path, burn_in))


def bank_standard_errors(
    replicates: list[dict[str, float]], names: tuple[str, ...]
) -> dict[str, float]:
    return standard_errors(replicates, names)


def bank_distance(
    simulated: Mapping[str, float],
    real: Mapping[str, float],
    se: Mapping[str, float],
    names: tuple[str, ...] = TARGETED_MOMENTS,
) -> float:
    return distance(simulated, real, se, names)


def apply_bank(config: WorldConfig, values: Mapping[str, float]) -> WorldConfig:
    """`config` with the estimated bank parameters (names as in `BANK_PARAMETERS`)."""
    allowed = {name for name, _, _ in BANK_PARAMETERS}
    unknown = set(values) - allowed
    if unknown:
        raise ValueError(f"unknown bank parameters {sorted(unknown)}")
    changes: dict[str, Any] = {k: float(v) for k, v in values.items()}
    return replace(config, banks=replace(config.banks, **changes))


def balance_sheet_shares(
    bank: Mapping[int, Mapping[str, float | None]], first: int, last: int
) -> dict[str, float]:
    """Average shares of assets over `first`..`last`: loans, securities, cash, deposits, equity."""
    keys = {
        "loans": "loans",
        "securities": "securities",
        "cash": "cash_and_balances",
        "deposits": "deposits",
        "equity": "equity",
    }
    out: dict[str, float] = {}
    years = [y for y in range(first, last + 1) if y in bank]
    for name, column in keys.items():
        shares = []
        for y in years:
            value, assets = bank[y][column], bank[y]["assets"]
            if value is None or assets is None:
                raise ValueError(f"{column} is not reported for {y}")
            shares.append(value / assets)
        out[name] = float(np.mean(shares))
    return out


def apply_balance_sheet(config: WorldConfig, shares: Mapping[str, float]) -> WorldConfig:
    """Set the opening balance sheet from real shares of assets.

    The simulator's banks hold loans, securities, cash and interbank claims (10 per 100 of assets,
    which no aggregate statistic can identify, so it keeps its chosen value). The real loans,
    securities and cash shares are rescaled to fill the other 90, in their real proportions;
    deposits are funded at the real share of assets. Equity is what is left."""
    banks = config.banks
    interbank_claims = banks.interbank_borrowed  # claims and borrowing are symmetric in the network
    room = 100.0 - interbank_claims
    total = shares["loans"] + shares["securities"] + shares["cash"]
    return replace(
        config,
        banks=replace(
            banks,
            loans=room * shares["loans"] / total,
            securities=room * shares["securities"] / total,
            cash=room * shares["cash"] / total,
            deposit_funding=100.0 * shares["deposits"],
        ),
    )
