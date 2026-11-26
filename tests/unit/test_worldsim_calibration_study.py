"""Finding 28's study: the real data it loads, its pre-written verdict rules, and a tiny end-to-end
run (the full run is in docs/numerics/worldsim_calibration_study.json)."""

from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np
import pytest

from prometheus.orchestration import worldsim_calibration_study as study
from prometheus.worldsim.config import scenario
from prometheus.worldsim.real_calibration import CREDIT_MOMENTS, MACRO_MOMENTS, all_moments


@pytest.fixture(scope="module")
def data() -> dict:
    return study.load_real_data()


def test_the_real_data_is_aligned_and_covers_the_stated_months(data: dict) -> None:
    keys = data["keys"]
    assert keys[0] == (1960, 1) and keys[-1] == (2023, 1) and len(keys) == 757
    for name in ("unemployment", "inflation", "fed_funds", "credit"):
        assert data[name].size == len(keys)
    assert np.isfinite(data["unemployment"]).all() and np.isfinite(data["fed_funds"]).all()
    assert np.isnan(data["credit"][:12]).all() and np.isfinite(data["credit"][-12:]).all()
    assert data["equity_keys"][0] == (1928, 1)
    assert all(math.isfinite(v) and v > -1.0 for v in data["equity"].values())
    assert data["okun_delta_u"].size == data["okun_growth"].size > 150


def test_the_train_and_test_slices_do_not_overlap_and_the_test_slice_is_held_out(
    data: dict,
) -> None:
    train = study.slice_data(data, (1960, 1), study.TRAIN_END)
    test = study.slice_data(data, study.TEST_START, study.DATA_END)
    assert train["keys"][-1] == (1999, 12) and test["keys"][0] == (2000, 1)
    assert set(train["keys"]).isdisjoint(test["keys"])
    assert len(train["keys"]) + len(test["keys"]) == len(data["keys"])
    assert max(k for k in data["equity_keys"] if k <= study.TRAIN_END) == (1999, 12)
    assert len(study.equity_history(data, study.TRAIN_END)) < len(
        study.equity_history(data, study.DATA_END)
    )


def test_the_real_moments_are_finite_and_economically_sensible(data: dict) -> None:
    table = study.real_table(study.slice_data(data, (1960, 1), study.DATA_END))
    moments = all_moments(table)
    assert all(math.isfinite(moments[name]) for name in MACRO_MOMENTS + CREDIT_MOMENTS)
    assert 0.10 < moments["eq_vol_ann"] < 0.20
    assert 0.8 < moments["ugap_ar1"] < 1.0 and moments["infl_ar1"] > 0.9
    assert 0.0 < moments["taylor_rho"] < 1.0
    assert moments["credit_mean"] > 3.0


def test_nber_recessions_are_between_five_and_twenty_percent_of_months(data: dict) -> None:
    assert 0.05 < study.nber_share(data["keys"]) < 0.20


def test_the_pre_written_verdict_rules() -> None:
    assert study.verdict_a(0.5, 3.0) == "SUPPORTED"
    assert study.verdict_a(-3.0, -0.5) == "CONTRADICTED"
    assert study.verdict_a(-1.0, 1.0) == "INCONCLUSIVE"
    assert study.verdict_b(5, 7) == "SUPPORTED" and study.verdict_b(7, 7) == "SUPPORTED"
    assert study.verdict_b(2, 7) == "CONTRADICTED" and study.verdict_b(0, 7) == "CONTRADICTED"
    assert study.verdict_b(3, 7) == "INCONCLUSIVE" and study.verdict_b(4, 7) == "INCONCLUSIVE"
    assert study.verdict_c(0.70, 0.40) == "SUPPORTED" and study.verdict_c(0.65, 0.40) == "SUPPORTED"
    assert study.verdict_c(0.50, 0.40) == "INCONCLUSIVE"
    assert study.verdict_c(0.40, 0.40) == "CONTRADICTED" and study.verdict_c(0.3, 0.4) == (
        "CONTRADICTED"
    )


def test_the_serial_simulator_averages_moments_over_seeds() -> None:
    config = study._with_length(scenario("volatile"), 120)
    moments = study.Simulator(None).moments(config, [1, 2])
    assert set(moments) >= set(MACRO_MOMENTS)
    assert all(math.isfinite(v) for v in moments.values())
    assert config.n_months == 120 + study.BURN_IN


def test_unit_conversion_round_trips_parameters_inside_their_bounds() -> None:
    from prometheus.worldsim.real_calibration import MACRO_PARAMETERS

    values = study._chosen_values(scenario("volatile"))
    back = study._from_unit(study._unit(values, MACRO_PARAMETERS), MACRO_PARAMETERS)
    assert back == pytest.approx(values)
    outside = study._from_unit(np.full(len(MACRO_PARAMETERS), 2.0), MACRO_PARAMETERS)
    assert all(outside[n] == hi for n, _, hi in MACRO_PARAMETERS)


def test_the_study_script_states_its_hypotheses_before_any_number() -> None:
    doc = study.__doc__ or ""
    for label in ("K-A", "K-B", "K-C"):
        assert label in doc
    assert "SUPPORTED" in doc and "CONTRADICTED" in doc and "INCONCLUSIVE" in doc


def test_a_tiny_estimation_run_returns_every_stage_and_respects_the_anchor(
    data: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(study, "EQUITY_SEEDS", (1, 2))
    simulator = study.Simulator(None)
    result = study.estimate(
        data,
        study.TRAIN_END,
        simulator,
        fits=1,
        max_evaluations=4,
        replications=8,
        anchor=True,
        credit_evaluations=4,
    )
    assert result["anchor"] is True and "ygap_sd" in result["macro_names"]
    assert result["months"] == 468 and 0.2 < result["direct"]["okun"] < 0.6
    assert set(result["macro_values"]) == {n for n, _, _ in study.MACRO_PARAMETERS}
    assert result["config"].households.okun == result["direct"]["okun"]
    assert result["real_moments"]["ygap_sd"] == pytest.approx(1.62, abs=0.05)
    plain = study.estimate(
        data,
        study.TRAIN_END,
        simulator,
        fits=1,
        max_evaluations=4,
        replications=8,
        credit_evaluations=4,
    )
    assert plain["anchor"] is False and "ygap_sd" not in plain["macro_names"]
    assert plain["direct"]["okun"] != result["direct"]["okun"]


def test_the_recorded_verdicts_follow_the_pre_written_rules() -> None:
    root = Path(__file__).resolve().parents[2] / "docs" / "numerics"
    for name in ("worldsim_calibration_study.json", "worldsim_calibration_study_v2.json"):
        recorded = json.loads((root / name).read_text())
        held = recorded["out_of_sample"]
        gap = held["distance_difference"]
        assert held["K-A"] == study.verdict_a(gap["low"], gap["high"])
        assert held["K-B"] == study.verdict_b(held["untargeted_inside"], 7)
        calibrated = recorded["robustness"]["calibrated"]
        assert calibrated["K-C"] == study.verdict_c(
            calibrated["connected_share_excluding_zero"], calibrated["plain_share_excluding_zero"]
        )
        assert recorded["K-S"] == study.verdict_s(
            recorded["world_sanity"]["calibrated"], recorded["full_fit"]["macro_values"]
        )
