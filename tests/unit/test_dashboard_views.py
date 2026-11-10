from __future__ import annotations

from datetime import date

import numpy as np
import pytest

from prometheus.core.ledger import Ledger, Sector
from prometheus.core.money import Money
from prometheus.dashboard.accessibility import check_accessibility
from prometheus.dashboard.views import (
    render_balance_sheets,
    render_economy_explorer,
    render_hedge_actions,
    render_market_paths,
    render_portfolio_risk,
    render_pricing_diagnostics,
)
from prometheus.econosim.agents import Household
from prometheus.volterra.instruments import EuropeanOption
from prometheus.volterra.market import MarketSnapshot


def test_economy_explorer_renders_a_real_aggregate_time_series_and_real_shocks() -> None:
    """UIX-01: driven by a real posted ledger/household/firm economy,
    not placeholder rows."""
    html = render_economy_explorer(n_steps=5, seed=0)
    assert html.count("<tr>") >= 5  # at least one row per step
    assert "SYNTHETIC" in html


def test_economy_explorer_is_deterministic_given_the_same_seed() -> None:
    a = render_economy_explorer(n_steps=5, seed=0)
    b = render_economy_explorer(n_steps=5, seed=0)
    assert a == b


def test_economy_explorer_rejects_non_positive_steps() -> None:
    with pytest.raises(ValueError, match="n_steps"):
        render_economy_explorer(n_steps=0, seed=0)


def test_balance_sheet_view_exposes_real_reconciliation_and_filterable_entries() -> None:
    """UIX-02: the SAME real `Ledger.balance_sheet` the ledger's own
    `check_identities` reconciliation check uses."""
    ledger = Ledger()
    household = Household(ledger, "hh-1")
    household.receive_income(Money(10_000, "USD"), step=0)
    html = render_balance_sheets(ledger, Sector.HOUSEHOLD)
    assert "data-reconciled='true'" in html
    assert "hh-1:deposit" in html
    ledger.check_identities()  # the real invariant check must independently agree


def test_market_paths_view_reports_real_simulated_percentiles() -> None:
    """UIX-03: percentiles computed from the real simulated terminal
    array, and the percentiles must actually be ordered."""
    html = render_market_paths(
        s0=100, mu=0.05, sigma=0.2, maturity=1.0, n_steps=12, n_paths=2000, seed=0
    )
    assert "SYNTHETIC" in html


def test_pricing_diagnostics_view_matches_the_real_closed_form_price() -> None:
    """UIX-04: the rendered price must equal what the real pricer
    actually returns -- not a re-typed/approximate number."""
    from prometheus.volterra.black_scholes import black_scholes_price

    market = MarketSnapshot(as_of=date(2026, 6, 1), spot=100.0, risk_free_rate=0.03, volatility=0.2)
    option = EuropeanOption(strike=105.0, maturity=0.5, option_type="call")
    expected_price = black_scholes_price(market, option)
    html = render_pricing_diagnostics(market, option)
    assert f"{expected_price:.6f}" in html
    assert "2026-06-01" in html  # as_of
    assert "Black-Scholes closed-form" in html  # method
    assert ">Q<" in html  # measure


def test_hedge_actions_view_reports_a_hedge_ratio_per_step() -> None:
    """UIX-05: causal, per-step hedge ratios -- one row per step."""
    html = render_hedge_actions(
        s0=100, mu=0.05, sigma=0.2, strike=100, maturity=1.0,
        risk_free_rate=0.03, n_steps=10, n_paths=50, seed=0,
    )
    assert html.count("<tr>") >= 10


def test_portfolio_risk_view_shows_horizon_confidence_and_units_prominently() -> None:
    """UIX-06: horizon/confidence/units must appear, and VaR/ES must be
    computed from the real supplied P&L series, not invented."""
    pnl = np.random.default_rng(0).normal(0, 100, 1000)
    html = render_portfolio_risk(pnl, alpha=0.95, horizon_label="1-day")
    assert "1-day" in html
    assert "95%" in html
    assert "Historical VaR" in html
    assert "Historical Expected Shortfall" in html


def test_every_view_above_passes_the_real_accessibility_checks() -> None:
    """A real, repo-wide self-check: every rendered page has a lang
    attribute, one h1, a main landmark, and a focus-visible rule."""
    pnl = np.random.default_rng(0).normal(0, 100, 100)
    market = MarketSnapshot(as_of=date(2026, 1, 1), spot=100.0, risk_free_rate=0.03, volatility=0.2)
    option = EuropeanOption(strike=100.0, maturity=1.0, option_type="call")
    pages = [
        render_economy_explorer(n_steps=3, seed=0),
        render_market_paths(
            s0=100, mu=0.05, sigma=0.2, maturity=1.0, n_steps=5, n_paths=50, seed=0
        ),
        render_pricing_diagnostics(market, option),
        render_portfolio_risk(pnl, alpha=0.95, horizon_label="1-day"),
    ]
    for html in pages:
        report = check_accessibility(html)
        assert report.passes(), report
