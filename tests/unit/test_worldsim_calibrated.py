"""The calibrated scenarios: constants pinned to the study that produced them, and runnable."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from prometheus.dashboard.worldsim_view import worldsim_as_json
from prometheus.worldsim.calibrated import (
    CALIBRATED_SCENARIOS,
    ESTIMATES,
    calibrated_config,
    calibrated_scenario,
)
from prometheus.worldsim.config import scenario
from prometheus.worldsim.world import simulate_world

STUDY = (
    Path(__file__).resolve().parents[2] / "docs" / "numerics" / "worldsim_calibration_study_v2.json"
)


def test_the_constants_are_the_final_estimates_of_the_recorded_study() -> None:
    summary = json.loads(STUDY.read_text())["full_fit"]["configuration"]
    config = calibrated_config()
    assert np.allclose(config.transition, summary["transition"], atol=1e-5)
    assert np.allclose(config.market.mu[:, 0], summary["equity_mu"], atol=1e-8)
    assert np.allclose(config.market.sigma[:, 0], summary["equity_sigma"], atol=1e-8)
    for name, value in summary["macro"].items():
        recorded = getattr(config.macro, name)
        assert np.allclose(recorded, value, rtol=1e-6), name
    assert config.households.okun == pytest.approx(summary["households"]["okun"], rel=1e-6)
    assert config.banks.loan_growth_base == pytest.approx(
        summary["banks"]["loan_growth_base"], rel=1e-6
    )
    assert json.loads(STUDY.read_text())["design"]["output_gap_anchor"] is True


def test_only_what_data_could_estimate_differs_from_the_chosen_world() -> None:
    chosen, calibrated = scenario("volatile"), calibrated_config()
    assert np.array_equal(calibrated.market.mu[:, 1:], chosen.market.mu[:, 1:])
    assert np.array_equal(calibrated.market.sigma[:, 1:], chosen.market.sigma[:, 1:])
    assert calibrated.banks.loans == chosen.banks.loans
    assert calibrated.banks.loss_given_default == chosen.banks.loss_given_default
    assert calibrated.fiscal == chosen.fiscal and calibrated.firms == chosen.firms
    assert calibrated.macro.inflation_target != chosen.macro.inflation_target
    assert calibrated.n_months == chosen.n_months == 240
    assert set(ESTIMATES) >= {"transition", "macro", "okun", "loan_growth_base"}


def test_every_calibrated_scenario_builds_and_simulates_without_failing() -> None:
    assert calibrated_scenario("calibrated").links.enabled is False
    assert calibrated_scenario("calibrated_full").fiscal.enabled is True
    assert calibrated_scenario("calibrated_full").links.enabled is False
    assert calibrated_scenario("calibrated_connected").links.enabled is True
    for name in CALIBRATED_SCENARIOS:
        path = simulate_world(calibrated_scenario(name), 0)
        assert np.isfinite(path.output_gap).all() and np.isfinite(path.asset_returns).all()
        assert path.config_name == name
    with pytest.raises(ValueError):
        calibrated_scenario("nope")


def test_the_dashboard_summary_accepts_calibrated_scenarios() -> None:
    summary = worldsim_as_json(name="calibrated_connected", seed=1)
    assert summary["scenario"] == "calibrated_connected" and summary["synthetic"] is True


BANK_STUDY = Path(__file__).resolve().parents[2] / "docs" / "numerics" / "worldsim_bank_study.json"
COLLAPSE = Path(__file__).resolve().parents[2] / "docs" / "numerics" / "worldsim_bank_collapse.json"


def test_the_bank_constants_are_the_final_fit_of_the_first_run_of_the_bank_study() -> None:
    from prometheus.worldsim.calibrated import BANK_ESTIMATES, calibrated_banks_config

    recorded = json.loads(BANK_STUDY.read_text())["full_fit"]["configuration"]
    banks = calibrated_banks_config().banks
    for name, value in BANK_ESTIMATES.items():
        assert getattr(banks, name) == pytest.approx(recorded[name], rel=1e-9), name
        assert recorded[name] == pytest.approx(value, rel=1e-9), name
    # what the data could not speak to keeps its chosen value
    chosen = calibrated_config().banks
    for name in ("loss_given_default", "capital_trigger", "fire_sale_fraction"):
        assert getattr(banks, name) == getattr(chosen, name)
    assert banks.securities_equity_share == chosen.securities_equity_share == 0.4
    assert banks.dividend_threshold == 0.0 and banks.securities_growth_share == 0.0


def test_the_banks_scenario_exists_only_as_the_plain_world() -> None:
    assert "calibrated_banks" in CALIBRATED_SCENARIOS
    assert not any(n.startswith("calibrated_banks_") for n in CALIBRATED_SCENARIOS)
    config = calibrated_scenario("calibrated_banks")
    assert config.links.enabled is False and config.fiscal.enabled is False
    assert config.banks.payout_ratio > 0.0 and config.macro == calibrated_config().macro
    with pytest.raises(ValueError):
        calibrated_scenario("calibrated_banks_full")


def test_the_recorded_collapse_check_is_why_there_is_no_full_banks_scenario() -> None:
    worlds = json.loads(COLLAPSE.read_text())["worlds"]
    assert worlds["calibrated_banks"]["all_banks_failed_share"] <= 0.05
    assert worlds["calibrated_banks_full"]["all_banks_failed_share"] > 0.5
    assert worlds["calibrated_full"]["all_banks_failed_share"] > 0.2  # Finding 28's own world too
    assert (
        worlds["calibrated_banks_connected"]["all_banks_failed_share"]
        > worlds["calibrated_connected"]["all_banks_failed_share"]
    )
