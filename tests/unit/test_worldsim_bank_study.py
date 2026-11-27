"""Finding 29's bank study: the real annual data it builds, its pre-written verdict rules, a tiny
end-to-end estimation and a check that the recorded verdicts follow the rules."""

from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np
import pytest

from prometheus.orchestration import worldsim_bank_study as study
from prometheus.worldsim.bank_calibration import (
    BANK_PARAMETERS,
    TARGETED_MOMENTS,
    UNTARGETED_MOMENTS,
    annual_moments,
)


@pytest.fixture(scope="module")
def tables() -> dict[str, dict[str, np.ndarray]]:
    return study.real_tables(study.load_real_data())


def test_the_real_annual_windows_are_disjoint_and_cover_the_stated_years(
    tables: dict[str, dict[str, np.ndarray]],
) -> None:
    years = {name: set(t["year"].astype(int).tolist()) for name, t in tables.items()}
    assert min(years["full"]) == 1985 and max(years["full"]) == 2022 and len(years["full"]) == 38
    assert years["train"].isdisjoint(years["test"])
    assert years["train"] | years["test"] == years["full"]
    assert max(years["train"]) == 2003 and min(years["test"]) == 2004
    for t in tables.values():
        assert np.isfinite(t["ugap"]).all()  # every year has twelve months of unemployment data


def test_the_real_annual_moments_are_the_known_history(
    tables: dict[str, dict[str, np.ndarray]],
) -> None:
    moments = annual_moments(tables["full"])
    assert all(math.isfinite(v) for v in moments.values())
    assert 0.7 < moments["roa_mean"] < 1.1 and 8.0 < moments["eq_mean"] < 10.0
    assert moments["nco_max"] == pytest.approx(2.56, abs=0.1)  # 2009
    assert moments["nco_corr_ugap"] > 0.2  # losses rise with unemployment
    assert moments["growth_min"] < -5.0  # the 2009 contraction of credit
    assert moments["failed_years_over_1pct"] > 0.05  # 1988-91 and 2008-10


def test_the_pre_written_verdict_rules() -> None:
    assert study.verdict_d2(5) == "SUPPORTED" and study.verdict_d2(7) == "SUPPORTED"
    assert study.verdict_d2(2) == "CONTRADICTED" and study.verdict_d2(0) == "CONTRADICTED"
    assert study.verdict_d2(3) == "INCONCLUSIVE" and study.verdict_d2(4) == "INCONCLUSIVE"
    assert study.verdict_d4(25.0, 20.0) == "SUPPORTED"  # exactly 1.25 times
    assert study.verdict_d4(25.1, 20.0) == "INCONCLUSIVE"
    assert study.verdict_d4(40.0, 20.0) == "INCONCLUSIVE"  # exactly twice is not more than twice
    assert study.verdict_d4(40.1, 20.0) == "CONTRADICTED"


def test_the_study_states_its_hypotheses_before_any_number_and_discloses_what_was_seen() -> None:
    doc = study.__doc__ or ""
    for label in ("K-D1", "K-D2", "K-D3", "K-D4", "K-D5"):
        assert label in doc
    assert "What I had looked at before writing this" in doc
    assert "foregone conclusion" in doc


def test_unit_conversion_round_trips_and_clips() -> None:
    start = study._start_values(
        study.base_world({"loans": 0.6, "securities": 0.2, "cash": 0.07, "deposits": 0.75})
    )
    back = study._from_unit(study._unit(start))
    assert back == pytest.approx(start)
    outside = study._from_unit(np.full(len(BANK_PARAMETERS), 2.0))
    assert all(outside[n] == hi for n, _, hi in BANK_PARAMETERS)


def test_the_base_world_has_the_real_opening_balance_sheet_and_the_fixed_loss_rate() -> None:
    shares = {"loans": 0.6, "securities": 0.2, "cash": 0.07, "deposits": 0.75}
    base = study.base_world(shares)
    b = base.banks
    assert b.loss_given_default == study.FIXED_LOSS_GIVEN_DEFAULT
    assert b.loans + b.securities + b.cash + b.interbank_borrowed == pytest.approx(100.0)
    assert b.deposit_funding == pytest.approx(75.0)
    assert base.n_months == study.SCENARIO_MONTHS


def test_the_serial_bank_simulator_averages_over_seeds_and_skips_failed_paths() -> None:
    simulator = study.BankSimulator(None)
    moments = simulator.bank_moments(
        study.base_world({"loans": 0.6, "securities": 0.2, "cash": 0.07, "deposits": 0.75}), (1, 2)
    )
    assert set(moments) == set(TARGETED_MOMENTS) | set(UNTARGETED_MOMENTS)
    assert all(math.isfinite(v) for v in moments.values())


def test_a_tiny_estimation_run_returns_every_stage(
    tables: dict[str, dict[str, np.ndarray]], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(study, "ESTIMATION_SEEDS", (1, 2))
    shares = {"loans": 0.6, "securities": 0.2, "cash": 0.07, "deposits": 0.75}
    result = study.estimate_banks(
        tables["train"],
        shares,
        study.BankSimulator(None),
        fits=1,
        max_evaluations=4,
        replications=10,
    )
    assert result["years"] == 19 and set(result["values"]) == {n for n, _, _ in BANK_PARAMETERS}
    assert result["config"].banks.payout_ratio == result["values"]["payout_ratio"]
    assert set(result["moment_se"]) == set(TARGETED_MOMENTS)
    assert all(v > 0 for v in result["moment_se"].values())
    ident = study.identification(result, study.BankSimulator(None))
    assert set(ident["parameters"]) == {n for n, _, _ in BANK_PARAMETERS}


def test_the_recorded_verdicts_follow_the_pre_written_rules() -> None:
    recorded = json.loads(
        (
            Path(__file__).resolve().parents[2] / "docs" / "numerics" / "worldsim_bank_study.json"
        ).read_text()
    )
    held = recorded["out_of_sample"]
    gap = held["distance_difference"]
    assert recorded["K-D1"] == held["K-D1"] == study.verdict_a(gap["low"], gap["high"])
    inside = sum(row["bank_calibrated_inside"] for row in held["untargeted"].values())
    assert inside == held["untargeted_inside"] and recorded["K-D2"] == study.verdict_d2(inside)
    macro = recorded["macro_check"]
    assert recorded["K-D4"] == study.verdict_d4(macro["bank_calibrated"], macro["finding28"])
    sane = recorded["sanity"]
    bounded = sane["parameters_at_a_bound"]
    assert (recorded["K-D3"] == "SUPPORTED") == (
        not bounded
        and study.MIN_EQUITY <= sane["mean_equity_ratio_percent"] <= study.MAX_EQUITY
        and sane["collapsed_share"] <= study.MAX_COLLAPSED_SHARE
        and sane["numeric"]["plain"]["failed_paths"] + sane["numeric"]["connected"]["failed_paths"]
        == 0
    )
    robust = recorded["robustness"]["bank_calibrated"]
    from prometheus.orchestration.worldsim_calibration_study import verdict_c

    assert recorded["K-D5"] == verdict_c(
        robust["connected_share_excluding_zero"], robust["plain_share_excluding_zero"]
    )


def test_the_collapse_check_reports_shares_per_world() -> None:
    report = study.collapse_check(
        {"calibrated_banks": study.collapse_worlds()["calibrated_banks"]}, (1, 2)
    )
    row = report["worlds"]["calibrated_banks"]
    assert report["seeds"] == [1, 2] and 0.0 <= row["all_banks_failed_share"] <= 1.0
    assert set(study.collapse_worlds()) == {
        "calibrated",
        "calibrated_full",
        "calibrated_connected",
        "calibrated_banks",
        "calibrated_banks_full",
        "calibrated_banks_connected",
    }


def test_the_second_revision_is_recorded_with_its_own_pre_written_verdicts() -> None:
    recorded = json.loads(
        (
            Path(__file__).resolve().parents[2]
            / "docs"
            / "numerics"
            / "worldsim_bank_study_v2.json"
        ).read_text()
    )
    assert recorded["revision"] == 2
    held = recorded["out_of_sample"]
    gap = held["distance_difference"]
    assert recorded["K-E1"] == study.verdict_a(gap["low"], gap["high"])
    against_first = held["distance_difference_vs_first_revision"]
    assert recorded["K-E2"] == study.verdict_a(against_first["low"], against_first["high"])
    assert recorded["K-E3"] == study.verdict_d2(held["untargeted_inside"])
    macro = recorded["macro_check"]
    assert recorded["K-E5"] == study.verdict_d4(macro["bank_calibrated"], macro["finding28"])
    assert recorded["K-E7"] == ("SUPPORTED" if held["structure_inside"] >= 2 else "CONTRADICTED")
    sane = recorded["sanity"]
    assert (recorded["K-E4"] == "SUPPORTED") == (
        not sane["parameters_at_a_bound"]
        and study.MIN_EQUITY <= sane["mean_equity_ratio_percent"] <= study.MAX_EQUITY
        and sane["collapsed_share"] <= study.MAX_COLLAPSED_SHARE
    )
    # the first run's recorded world, not this one, is what ships
    first = json.loads(
        (
            Path(__file__).resolve().parents[2] / "docs" / "numerics" / "worldsim_bank_study.json"
        ).read_text()
    )
    assert held["distance_first_revision"] == pytest.approx(
        first["out_of_sample"]["distance_bank_calibrated"], rel=1e-9
    )
    assert recorded["K-E2"] == "CONTRADICTED"  # the revision did worse than the first run


def test_the_return_on_assets_decomposition_adds_up_and_is_recorded() -> None:
    report = study.roa_decomposition(study.collapse_worlds()["calibrated_banks"], (1, 2))
    assert report["bank_years"] > 10
    assert report["roa_mean"] == pytest.approx(
        report["income_mean"] - report["loss_mean"] + report["securities_gain_mean"], abs=1e-9
    )
    recorded = json.loads(study.DECOMPOSITION_OUTPUT.read_text())
    for run in ("first_run", "second_run"):
        row = recorded[run]
        # the securities' gain, not lending, is where the volatility of bank earnings comes from
        assert row["securities_gain_sd"] > 5 * max(row["income_sd"], row["loss_sd"])
        assert row["securities_gain_sd"] > 0.9 * row["roa_sd"]
    assert study.second_revision_world().banks.securities_growth_share == 1.0
