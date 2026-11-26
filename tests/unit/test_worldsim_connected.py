"""WORLDSIM interconnection: the loops are off unless asked, and each one does its job when on."""

from __future__ import annotations

import json
from dataclasses import replace

import numpy as np
import pytest

from prometheus.orchestration import worldsim_connected_study as study
from prometheus.worldsim import impulse
from prometheus.worldsim.config import (
    CONNECTED_SCENARIOS,
    Shock,
    connected_scenario,
    full_scenario,
    scenario,
)
from prometheus.worldsim.households_block import AggregateHouseholds
from prometheus.worldsim.world import simulate_world

V2_PINS = {
    ("volatile_full", "none", 0): (10, -705.787, 1.07967, 0.41406, 0.0),
    ("volatile_full", "none", 1): (0, -56.97, 0.6222, 0.08839, 0.0),
    ("stressed_full", "none", 0): (10, -1592.258, 2.72895, 0.87821, 0.0),
    ("stressed_full", "none", 1): (10, -1211.483, 1.83059, 0.48167, 0.0),
    ("stressed_full", "recapitalise", 0): (0, -1282.995, 2.75162, 0.87411, 588.654),
    ("stressed_full", "recapitalise", 1): (0, -844.229, 1.54489, 0.4804, 437.653),
    ("stressed_full", "liquidity", 0): (10, -1569.572, 2.65083, 0.87579, 0.0),
    ("stressed_full", "liquidity", 1): (10, -1174.718, 1.75735, 0.48013, 0.0),
}


@pytest.mark.parametrize(("name", "mode", "seed"), list(V2_PINS))
def test_with_the_links_off_the_finding_26_world_is_unchanged(
    name: str, mode: str, seed: int
) -> None:
    failed, gap_sum, debt, fx, injected = V2_PINS[(name, mode, seed)]
    path = simulate_world(full_scenario(name, mode=mode), seed)  # type: ignore[arg-type]
    assert int(path.bank_failed[-1].sum()) == failed
    assert float(path.output_gap.sum()) == pytest.approx(gap_sum, abs=2e-3)
    assert float(path.debt_ratio[-1]) == pytest.approx(debt, abs=2e-5)
    assert float(path.fx_level[-1]) == pytest.approx(fx, abs=2e-5)
    assert float(path.injection.sum()) == pytest.approx(injected, abs=2e-3)


def test_the_link_series_are_empty_when_the_links_are_off() -> None:
    path = simulate_world(full_scenario("stressed_full"), 1)
    assert np.all(path.gini == 0.0) and np.all(path.consumption == 0.0)
    assert not path.sovereign_default.any() and path.deposit_insurance_cost.sum() == 0.0


def test_the_connected_scenarios_exist_and_unknown_ones_are_rejected() -> None:
    for name in CONNECTED_SCENARIOS:
        assert connected_scenario(name).links.enabled
    assert connected_scenario("sovereign_stress").fiscal.initial_debt == 1.30
    assert connected_scenario("rising_inequality").households.top_income_growth > 0.0
    with pytest.raises(ValueError, match="unknown connected scenario"):
        connected_scenario("nope")
    with pytest.raises(ValueError, match="unknown shock"):
        Shock(5, "nope")
    with pytest.raises(ValueError, match="month >= 1"):
        Shock(0, "equity_crash")


def test_a_shock_changes_nothing_before_its_month_and_uses_no_random_numbers() -> None:
    config = connected_scenario("volatile_connected")
    base = simulate_world(config, 3)
    shocked = simulate_world(config, 3, [Shock(100, "equity_crash", 0.3)])
    assert np.array_equal(base.regime, shocked.regime)
    assert np.array_equal(base.asset_returns[:100], shocked.asset_returns[:100])
    assert shocked.asset_returns[100, 0] < base.asset_returns[100, 0] - 0.25


@pytest.mark.parametrize(
    ("kind", "size", "series"),
    [
        ("rate_hike", 3.0, "policy_rate"),
        ("fx_crash", 0.2, "fx_level"),
        ("supply_shock", 3.0, "inflation"),
    ],
)
def test_macro_shocks_move_their_own_series_the_month_they_happen(
    kind: str, size: float, series: str
) -> None:
    config = connected_scenario("volatile_connected")
    base = simulate_world(config, 2)
    shocked = simulate_world(config, 2, [Shock(80, kind, size)])
    assert getattr(shocked, series)[80] > getattr(base, series)[80]


def test_a_demand_shock_lowers_consumption_and_a_bank_loss_lowers_capital() -> None:
    config = connected_scenario("volatile_connected")
    base = simulate_world(config, 2)
    demand = simulate_world(config, 2, [Shock(80, "demand_shock", 0.2)])
    assert demand.consumption[80] < base.consumption[80]
    loss = simulate_world(config, 2, [Shock(80, "bank_loss", 0.08)])
    assert loss.bank_capital_ratio[80].mean() < base.bank_capital_ratio[80].mean()


def test_a_sovereign_default_cuts_debt_and_hurts_the_banks_holding_its_bonds() -> None:
    config = connected_scenario("volatile_connected")
    base = simulate_world(config, 5)
    shocked = simulate_world(config, 5, [Shock(100, "sovereign_default")])
    assert shocked.sovereign_default[100] and not base.sovereign_default[100]
    assert shocked.debt_ratio[100] < base.debt_ratio[100]
    assert shocked.fx_level[100] > base.fx_level[100]
    exposed = shocked.bank_capital_ratio[100].mean()
    no_bonds = replace(config, links=replace(config.links, bank_sovereign_share=0.0))
    clean = simulate_world(no_bonds, 5, [Shock(100, "sovereign_default")])
    assert exposed < clean.bank_capital_ratio[100].mean()


def test_a_default_is_followed_by_a_period_without_another() -> None:
    config = connected_scenario("sovereign_stress")
    for seed in range(12):
        months = np.where(simulate_world(config, seed).sovereign_default)[0]
        if months.size > 1:
            assert np.all(np.diff(months) >= config.links.exclusion_months)


def test_bank_failures_cost_the_state_and_full_insurance_leaves_nothing_to_the_depositors() -> None:
    config = connected_scenario("stressed_connected")
    costs = [simulate_world(config, s).deposit_insurance_cost.sum() for s in range(8)]
    assert max(costs) > 0.0
    insured = replace(config, links=replace(config.links, insured_share=1.0))
    assert all(simulate_world(insured, s).uninsured_loss.sum() == 0.0 for s in range(4))


def test_uninsured_deposit_losses_hit_only_the_wealthiest_depositors() -> None:
    config = connected_scenario("volatile_connected")
    block = AggregateHouseholds(config.households, config.links, 0.3, 0, 12)
    before = block.wealth.copy()
    block.step(1, np.zeros(4), 2.0, 0.0, 0.5, 0.0)
    after = block.wealth
    top = block.depositors
    assert np.all(after[top] < before[top] * 1.001)
    assert np.mean(after[top] / before[top]) < np.mean(after[~top] / before[~top])


def test_progressive_taxes_raise_revenue_and_a_wealth_tax_lowers_top_wealth() -> None:
    config = connected_scenario("volatile_connected")

    def tax_share(links: object) -> float:
        block = AggregateHouseholds(config.households, links, 0.3, 0, 12)  # type: ignore[arg-type]
        return block.step(1, np.zeros(4), 2.0, 0.0, 0.0, 0.0).tax_share

    flat = tax_share(config.links)
    progressive = tax_share(replace(config.links, tax_progressivity=0.4))
    assert progressive > flat
    taxed = AggregateHouseholds(
        config.households, replace(config.links, wealth_tax_rate=0.05), 0.3, 0, 12
    )
    plain = AggregateHouseholds(config.households, config.links, 0.3, 0, 12)
    taxed.step(1, np.zeros(4), 2.0, 0.0, 0.0, 0.0)
    plain.step(1, np.zeros(4), 2.0, 0.0, 0.0, 0.0)
    assert taxed.wealth.max() < plain.wealth.max()


def test_the_inequality_forces_raise_the_gini_while_the_ordinary_world_lowers_it() -> None:
    rising = connected_scenario("rising_inequality")
    ordinary = connected_scenario("volatile_connected")
    seeds = range(8)
    rise = np.mean(
        [simulate_world(rising, s).gini[-1] - simulate_world(rising, s).gini[0] for s in seeds]
    )
    drift = np.mean(
        [simulate_world(ordinary, s).gini[-1] - simulate_world(ordinary, s).gini[0] for s in seeds]
    )
    assert rise > 0.0 > drift


def test_leaning_against_leverage_raises_the_policy_rate_when_leverage_is_high() -> None:
    config = connected_scenario("stressed_connected")
    lean = replace(config, links=replace(config.links, financial_stability_phi=0.2))
    base_rate = simulate_world(config, 1).policy_rate
    lean_rate = simulate_world(lean, 1).policy_rate
    leverage = simulate_world(config, 1).firm_leverage
    assert np.any(leverage > 0.5)
    assert lean_rate.max() > base_rate.max()


def test_the_consumption_link_moves_output_and_firm_distress_moves_unemployment() -> None:
    config = connected_scenario("stressed_connected")
    no_link = replace(config, links=replace(config.links, demand_coupling=0.0))
    assert not np.array_equal(
        simulate_world(config, 2).output_gap, simulate_world(no_link, 2).output_gap
    )
    no_firm = replace(config, links=replace(config.links, firm_unemployment=0.0))
    assert (
        simulate_world(config, 2).unemployment.max()
        >= simulate_world(no_firm, 2).unemployment.max()
    )


def test_the_impulse_matrix_has_every_cell_and_the_connected_world_responds_more() -> None:
    seeds = range(6)
    connected = impulse.impulse_matrix(
        connected_scenario("volatile_connected"), seeds, ("equity_crash", "sovereign_default")
    )
    plain = impulse.impulse_matrix(
        full_scenario("volatile_full"), seeds, ("equity_crash", "sovereign_default")
    )
    assert set(connected["matrix"]["equity_crash"]) == set(impulse.OUTCOMES)
    assert connected["cells"] == 2 * len(impulse.OUTCOMES)
    assert connected["cells_excluding_zero"] > plain["cells_excluding_zero"]
    default_row = connected["matrix"]["sovereign_default"]
    assert (
        default_row["output_gap"]["estimate"] < 0.0 and default_row["public_debt"]["estimate"] < 0.0
    )
    with pytest.raises(ValueError, match="too short"):
        impulse.impulse_matrix(replace(scenario("volatile"), n_months=60), seeds)


def test_a_small_connected_study_answers_every_question_and_is_reproducible() -> None:
    kwargs = {"n_seeds": 6, "workers": 1, "impulse_seeds": 4, "sensitivity_seeds": 2}
    first = study.run_study(**kwargs)
    second = study.run_study(**kwargs)
    assert json.dumps(first, sort_keys=True) == json.dumps(second, sort_keys=True)
    assert len(first["hypotheses"]) == 8
    assert set(first["impulse_responses"]) == {"connected", "unconnected"}
    assert len(first["sensitivity_sovereign_stress_25_percent_moves"]) == len(
        study.SENSITIVITY_PARAMETERS
    )


def test_the_dashboard_shows_a_connected_scenario() -> None:
    from prometheus.dashboard.worldsim_view import render_worldsim, worldsim_as_json

    summary = worldsim_as_json(name="sovereign_stress", seed=2)
    assert "sovereign_defaults" in summary["extensions"] and summary["bailout_mode"] == "none"
    assert "Bank rescue policy" in render_worldsim(name="rising_inequality", seed=1)
