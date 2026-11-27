"""The annual bank statistics of `worldsim.bank_calibration`, on small hand-made inputs and on a
simulated path, and the dividend payout and aggregates it needs from the banks."""

from __future__ import annotations

import math

import numpy as np
import pytest

from prometheus.worldsim.bank_calibration import (
    ANNUAL_COLUMNS,
    BANK_PARAMETERS,
    TARGETED_MOMENTS,
    UNTARGETED_MOMENTS,
    annual_bootstrap,
    annual_moments,
    annual_unemployment_gap,
    apply_balance_sheet,
    apply_bank,
    balance_sheet_shares,
    interval,
    real_annual_table,
    simulated_annual_moments,
    simulated_annual_table,
)
from prometheus.worldsim.config import Shock, scenario
from prometheus.worldsim.world import simulate_world


def _bank(year: int, scale: float = 1.0) -> dict[str, float | None]:
    return {
        "assets": 1000.0 * scale,
        "loans": 600.0 * scale,
        "securities": 200.0 * scale,
        "cash_and_balances": 80.0 * scale,
        "deposits": 790.0 * scale,
        "equity": 90.0 * scale,
        "net_charge_offs": 6.0 * scale,
        "net_income": 9.0 * scale,
    }


def test_the_unemployment_gap_is_averaged_over_whole_calendar_years() -> None:
    months = [(y, m) for y in (2000, 2001) for m in range(1, 13)] + [(2002, 1)]
    gap = np.arange(len(months), dtype=float)
    # a table drops its first 12 months, so its rows line up with the LAST len(gap) months
    out = annual_unemployment_gap(months, gap[12:], [2000, 2001, 2002])
    assert math.isnan(out[0])  # 2000 has no rows left
    assert out[1] == pytest.approx(np.mean(gap[12:24]))
    assert math.isnan(out[2])  # one month is not a year


def test_real_annual_rows_use_average_stocks_and_year_end_ratios() -> None:
    bank = {1999: _bank(1999, 0.9), 2000: _bank(2000, 1.0)}
    failures = {2000: {"failed_assets": 27.0}}
    table = real_annual_table(bank, failures, {2000: 1.5}, 2000, 2000)
    assets_avg, loans_avg = 0.5 * (900 + 1000), 0.5 * (540 + 600)
    assert table["roa"][0] == pytest.approx(100 * 9.0 / assets_avg)
    assert table["nco"][0] == pytest.approx(100 * 6.0 / loans_avg)
    assert table["eq"][0] == pytest.approx(9.0)
    assert table["growth"][0] == pytest.approx(100 * (600 / 540 - 1))
    assert table["failed"][0] == pytest.approx(100 * 27.0 / 900)  # of the opening assets
    assert table["loans_to_assets"][0] == pytest.approx(60.0)
    assert table["ugap"][0] == 1.5 and table["year"][0] == 2000


def test_a_year_without_its_opening_year_is_skipped_and_a_missing_stock_is_refused() -> None:
    bank = {2000: _bank(2000), 2001: _bank(2001)}
    failures = {2001: {"failed_assets": 0.0}}
    table = real_annual_table(bank, failures, {}, 2000, 2001)
    assert table["year"].tolist() == [2001.0]  # 2000 has no 1999 to open from
    assert math.isnan(table["ugap"][0])  # no gap supplied for the year
    broken = {2000: _bank(2000), 2001: {**_bank(2001), "equity": None}}
    with pytest.raises(ValueError, match="equity is not reported"):
        real_annual_table(broken, failures, {}, 2001, 2001)


def test_moments_bootstrap_and_interval_are_deterministic() -> None:
    rng = np.random.default_rng(0)
    n = 30
    ugap = rng.normal(size=n)
    table = {
        "roa": 1.0 + 0.2 * rng.normal(size=n),
        "eq": 9.0 + rng.normal(size=n),
        "nco": 0.8 + 0.3 * ugap + 0.1 * rng.normal(size=n),
        "growth": 4.0 - ugap + rng.normal(size=n),
        "failed": np.abs(rng.normal(size=n)),
        "loans_to_assets": 58.0 + rng.normal(size=n),
        "ugap": ugap,
        "year": np.arange(n, dtype=float),
    }
    moments = annual_moments(table)
    assert set(moments) == set(TARGETED_MOMENTS) | set(UNTARGETED_MOMENTS)
    assert moments["nco_corr_ugap"] > 0.8 and moments["growth_corr_ugap"] < -0.5
    a = annual_bootstrap(table, replications=20, seed=3)
    b = annual_bootstrap(table, replications=20, seed=3)
    assert a == b and len(a) == 20
    low, high = interval(a, "roa_mean")
    assert low < moments["roa_mean"] < high


def test_a_constant_column_has_zero_correlation_not_nan() -> None:
    n = 10
    table = {c: np.ones(n) for c in ANNUAL_COLUMNS}
    table["year"] = np.arange(n, dtype=float)
    table["ugap"] = np.arange(n, dtype=float)
    assert annual_moments(table)["nco_corr_ugap"] == 0.0


def test_apply_bank_sets_known_parameters_and_refuses_unknown_ones() -> None:
    base = scenario("volatile")
    out = apply_bank(base, {"payout_ratio": 0.4, "net_interest_margin": 0.003})
    assert out.banks.payout_ratio == 0.4 and out.banks.net_interest_margin == 0.003
    assert out.banks.loans == base.banks.loans  # nothing else moved
    with pytest.raises(ValueError, match="unknown bank parameters"):
        apply_bank(base, {"capital_trigger": 0.1})
    assert {n for n, _, _ in BANK_PARAMETERS} >= {"payout_ratio", "loan_growth_base"}


def test_real_balance_sheet_shares_fill_the_simulators_opening_balance_sheet() -> None:
    bank = {y: _bank(y) for y in (2000, 2001)}
    shares = balance_sheet_shares(bank, 2000, 2001)
    assert shares["loans"] == pytest.approx(0.6) and shares["deposits"] == pytest.approx(0.79)
    config = apply_balance_sheet(scenario("volatile"), shares)
    b = config.banks
    assert b.loans + b.securities + b.cash + b.interbank_borrowed == pytest.approx(100.0)
    assert b.loans / b.securities == pytest.approx(0.6 / 0.2)  # real proportions kept
    assert b.deposit_funding == pytest.approx(79.0)
    with pytest.raises(ValueError, match="not reported"):
        balance_sheet_shares({2000: {**_bank(2000), "equity": None}}, 2000, 2000)


# --- the simulator side ---


def test_a_simulated_path_gives_whole_annual_rows_that_add_up() -> None:
    path = simulate_world(scenario("volatile"), 4)
    table = simulated_annual_table(path)
    assert table["roa"].size == (path.n_months - 24) // 12 == 18
    assert all(np.isfinite(table[c]).all() for c in ANNUAL_COLUMNS)
    # year 0 covers months 24..35 with the opening stock at month 23
    losses = path.bank_loan_losses[24:36].sum()
    avg_loans = 0.5 * (path.bank_credit[23] + path.bank_credit[35])
    assert table["nco"][0] == pytest.approx(100 * losses / avg_loans)
    assert table["eq"][0] == pytest.approx(100 * path.bank_equity[35] / path.bank_assets[35])
    assert set(simulated_annual_moments(path)) == set(annual_moments(table))


def test_the_default_world_pays_no_dividends_and_a_payout_world_does_and_holds_less_capital() -> (
    None
):
    base = scenario("volatile")
    none = simulate_world(base, 5)
    assert base.banks.payout_ratio == 0.0 and none.bank_dividends.sum() == 0.0
    paying = simulate_world(apply_bank(base, {"payout_ratio": 0.8}), 5)
    assert paying.bank_dividends.sum() > 0.0 and (paying.bank_dividends >= 0.0).all()
    window = slice(24, 120)  # before any bank has failed in either world
    assert (
        paying.bank_equity[window].sum() / paying.bank_assets[window].sum()
        < none.bank_equity[window].sum() / none.bank_assets[window].sum()
    )


def test_retained_earnings_alone_push_the_capital_ratio_far_above_real_banks() -> None:
    """The reason for the payout: with no dividends the chosen worlds' banks end the 20 years with
    several times the equity real banks hold (Finding 29)."""
    path = simulate_world(scenario("volatile"), 6)
    assert path.bank_equity[-1] / path.bank_assets[-1] > 0.20


def test_the_assets_of_banks_that_fail_are_recorded_in_the_month_they_fail() -> None:
    config = scenario("stressed")
    quiet = simulate_world(config, 2)
    hit = simulate_world(config, 2, [Shock(60, "bank_loss", 0.30)])
    assert hit.new_failures[60:].sum() > quiet.new_failures[60:].sum()
    assert hit.bank_failed_assets[60:].sum() > 0.0
    assert (hit.bank_failed_assets[np.flatnonzero(hit.new_failures == 0)] == 0.0).all()
    # a failed bank's loans stay in the economy: total credit does not fall by its loans
    assert hit.bank_credit[-1] > hit.total_loans[-1]


def test_a_dividend_threshold_makes_banks_retain_profit_below_it() -> None:
    base = apply_bank(scenario("volatile"), {"payout_ratio": 1.0})
    low = simulate_world(base, 8)
    from dataclasses import replace

    high_config = replace(base, banks=replace(base.banks, dividend_threshold=0.30))
    high = simulate_world(high_config, 8)
    early = slice(0, 60)  # later, the world that paid out everything has lost its banks
    assert low.bank_dividends[early].sum() > high.bank_dividends[early].sum()
    window = slice(24, 120)
    assert (
        high.bank_equity[window].sum() / high.bank_assets[window].sum()
        > low.bank_equity[window].sum() / low.bank_assets[window].sum()
    )


def test_securities_grow_with_loans_when_asked_and_not_otherwise() -> None:
    from dataclasses import replace

    base = scenario("volatile")
    grown = replace(base, banks=replace(base.banks, securities_growth_share=1.0))
    a, b = simulate_world(base, 9), simulate_world(grown, 9)
    share_a = a.total_loans[100] / a.bank_assets[100]
    share_b = b.total_loans[100] / b.bank_assets[100]
    assert share_b < share_a  # the loans-to-assets ratio drifts up unless securities grow too
    assert base.banks.securities_growth_share == 0.0 and base.banks.dividend_threshold == 0.0
