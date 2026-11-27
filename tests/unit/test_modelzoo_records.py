"""The recorded model-zoo studies: every verdict stored in `docs/numerics/modelzoo_*.json`
is recomputed here from the numbers stored beside it, with the decision rules written before
the runs. A verdict that does not follow from its own numbers fails."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from prometheus.modelzoo.verdicts import (
    direction_verdict,
    paired_bootstrap_ci,
    summarise_difference,
    threshold_verdict,
)

NUMERICS = Path(__file__).resolve().parents[2] / "docs" / "numerics"


def load(name: str) -> dict[str, Any]:
    return json.loads((NUMERICS / f"modelzoo_{name}.json").read_text())  # type: ignore[no-any-return]


def check_difference(record: dict[str, Any], values: list[float] | np.ndarray) -> None:
    """A stored difference summary equals the one recomputed from the raw per-seed values."""
    again = summarise_difference(values)
    assert record["verdict"] == again["verdict"]
    assert record["mean"] == pytest.approx(again["mean"], rel=1e-9, abs=1e-12)
    assert record["low"] == pytest.approx(again["low"], rel=1e-9, abs=1e-12)
    assert record["high"] == pytest.approx(again["high"], rel=1e-9, abs=1e-12)
    assert record["verdict"] == direction_verdict(record["low"], record["high"])


def combine(verdicts: list[str]) -> str:
    if all(v == "SUPPORTED" for v in verdicts):
        return "SUPPORTED"
    return "CONTRADICTED" if any(v == "CONTRADICTED" for v in verdicts) else "INCONCLUSIVE"


def test_the_bootstrap_helper_reproduces_itself() -> None:
    assert paired_bootstrap_ci([1, 2, 3, 4], seed=0) == paired_bootstrap_ci([1, 2, 3, 4], seed=0)


# ----- tranche 1 --------------------------------------------------------------------------------


def test_operator_verdicts_follow_from_their_numbers() -> None:
    r = load("pde_operators")
    rows = r["rows"]
    col = lambda m, k: np.array([x[m][k] for x in rows])  # noqa: E731
    trivial = np.array([x["trivial_in_distribution"] for x in rows])
    parts = []
    for m in ("fno", "deeponet", "mlp"):
        ratio = float(np.median(col(m, "in_distribution") / trivial))
        assert r["Z-O1_detail"][m]["verdict"] == threshold_verdict(ratio, 0.2, 0.5)
        parts.append(r["Z-O1_detail"][m]["verdict"])
    assert r["Z-O1"] == combine(parts)
    check_difference(r["Z-O2"], col("mlp", "six_to_eight_kinks") - col("fno", "six_to_eight_kinks"))
    check_difference(r["Z-O3"], col("deeponet", "in_distribution") - col("fno", "in_distribution"))
    ratios = {m: col(m, "grid_128") / col(m, "in_distribution") for m in ("fno", "mlp")}
    check_difference(r["Z-O4"], ratios["mlp"] - ratios["fno"])
    assert len(rows) == 8 and r["seeds"] == list(range(71000, 71008))


def test_dynamics_verdicts_follow_from_their_numbers() -> None:
    r = load("pde_dynamics")
    rows = r["rows"]
    drift = lambda s, k: np.array([x[k]["energy_drift"] for x in rows if x["system"] == s])  # noqa: E731
    parts = []
    for key, record in r["Z-D1_detail"].items():
        system, kind = key.split(":")
        check_difference(record, drift(system, "mlp") - drift(system, kind))
        parts.append(record["verdict"])
    assert r["Z-D1"] == combine(parts)
    assert r["Z-D2"] == ("SUPPORTED" if r["Z-D2_worst_defect"] <= 1e-4 else "CONTRADICTED")
    parts = []
    for system, record in r["Z-D3_detail"].items():
        err = lambda k, s=system: np.array(  # noqa: E731
            [x[k]["state_error"]["500"] for x in rows if x["system"] == s]
        )
        check_difference(record, err("sympnet") - err("mlp"))
        parts.append(record["verdict"])
    assert r["Z-D3"] == combine(parts)


def test_mesh_free_solver_verdicts_follow_from_their_numbers() -> None:
    r = load("pde_variational")
    rows = r["rows"]
    assert r["Z-V1"] == threshold_verdict(
        float(np.median([x["dgm_european_error"] for x in rows])), 0.05, 0.10
    )
    assert r["Z-V2"] == threshold_verdict(
        float(np.median([x["dgm_american_error"] for x in rows])), 0.10, 0.20
    )
    check_difference(r["Z-V3"], np.array([x["ritz_error"] - x["fd_error"] for x in rows]))
    top = str(r["Z-V4_dimension"])
    check_difference(
        r["Z-V4"],
        np.array(
            [
                x["kolmogorov"][top]["mc_same_budget_rmse"] - x["kolmogorov"][top]["net_rmse"]
                for x in rows
            ]
        ),
    )


# ----- tranche 2 --------------------------------------------------------------------------------


def test_forecasting_verdicts_follow_from_their_intervals() -> None:
    r = load("forecast_study")
    assert r["test_months"] == 277 and r["seeds"] == list(range(72000, 72005))
    for key in ("Z-F1", "Z-F3", "Z-F5", "Z-F6"):
        record = r[key]
        # lower error is claimed, so the verdict is read from the interval of |e_first| - |e_second|
        expected = (
            "SUPPORTED"
            if record["ci_high"] < 0
            else "CONTRADICTED"
            if record["ci_low"] > 0
            else "INCONCLUSIVE"
        )
        assert record["verdict"] == expected, key
    detail = r["Z-F2"]["detail"]
    assert set(detail) == {"nbeats", "nhits", "patchtst", "s4d", "mamba_lite"}
    assert r["Z-F2"]["verdict"] == combine([d["verdict"] for d in detail.values()])
    scores = r["scores"]
    deep = [
        m
        for m in scores
        if m not in ("base_mean12", "ridge_own", "mlp_own") and not m.endswith("_core")
    ]
    chosen = min(deep, key=lambda m: scores[m]["validation_mae_mom"])
    assert r["validation_selected"] == chosen  # picked on validation, never on the test months
    z4 = r["Z-F4"]
    assert z4["verdict"] == ("SUPPORTED" if 0.70 <= z4["coverage_80"] <= 0.90 else "CONTRADICTED")


# ----- tranche 3 --------------------------------------------------------------------------------


def test_structural_macro_verdicts_follow_from_their_numbers() -> None:
    r = load("macro_structural")
    closed = r["economies"]["closed_form"]
    assert r["Z-M1"] == threshold_verdict(
        float(np.median([x["deq_policy_error"] for x in closed["rows"]])), 0.005, 0.02
    )
    for key, economy in (("Z-M2", "closed_form"), ("Z-M3", "general")):
        e = r["economies"][economy]
        check_difference(
            r[key], np.array([e["vfi_log10_euler"] - x["deq_log10_euler"] for x in e["rows"]])
        )


def test_portfolio_verdicts_are_consistent_with_their_intervals() -> None:
    r = load("macro_portfolio")
    assert r["test_months"] > 100
    for key in ("Z-P1", "Z-P2", "Z-P3"):
        rec = r[key]
        expected = (
            "SUPPORTED"
            if rec["ci_low"] > 0
            else "CONTRADICTED"
            if rec["ci_high"] < 0
            else "INCONCLUSIVE"
        )
        assert rec["verdict"] == expected, key
    assert r["Z-P4"] == (
        "SUPPORTED" if r["Z-P4_worst_gradient_difference"] < 1e-5 else "CONTRADICTED"
    )
    assert r["sharpe"]["dfl"] == pytest.approx(r["Z-P1"]["sharpe_first"])
    assert r["sharpe"]["two_stage"] == pytest.approx(r["Z-P1"]["sharpe_second"])


def test_network_verdicts_follow_from_their_numbers() -> None:
    r = load("macro_networks")
    rows = r["rows"]
    col = lambda k: np.array([x[k] for x in rows])  # noqa: E731
    check_difference(r["Z-G1"], col("truncated3_60") - col("gnn_60"))
    check_difference(r["Z-G2"], col("blind_60") - col("gnn_60"))
    assert r["Z-G3"] == threshold_verdict(float(np.median(col("gnn_60") / col("gnn_30"))), 2.0, 4.0)


def test_causal_and_survival_verdicts_follow_from_their_numbers() -> None:
    r = load("macro_causal")
    dml, iv, sv = r["dml_rows"], r["iv_rows"], r["survival_rows"]
    check_difference(r["Z-C1"], np.array([x["ols_error"] - x["dml_error"] for x in dml]))
    check_difference(r["Z-C2"], np.array([x["two_sls"] - x["deepiv"] for x in iv]))
    check_difference(r["Z-C3"], np.array([x["ols"] - x["deepiv"] for x in iv]))
    check_difference(r["Z-S1"], np.array([x["deepsurv"] - x["cox"] for x in sv]))
    gap = float(np.median([x["oracle"] - x["deepsurv"] for x in sv]))
    assert r["Z-S2"] == threshold_verdict(gap, 0.03, 0.06)


# ----- tranche 4 --------------------------------------------------------------------------------


def test_amplitude_estimation_verdicts_follow_from_their_numbers() -> None:
    r = load("quantum_amplitude")
    calls = np.log([x["calls"] for x in r["rows"]])
    slope = lambda k: float(np.polyfit(calls, np.log([x[k] for x in r["rows"]]), 1)[0])  # noqa: E731
    assert slope("rmse_ideal") == pytest.approx(r["slope_ideal"])
    assert slope("rmse_monte_carlo") == pytest.approx(r["slope_monte_carlo"])
    assert r["Z-Q1"] == ("SUPPORTED" if r["slope_ideal"] < -0.75 else "CONTRADICTED")
    assert r["Z-Q2"] == ("SUPPORTED" if -0.6 <= r["slope_monte_carlo"] <= -0.4 else "CONTRADICTED")
    assert r["Z-Q3"]["verdict"] == direction_verdict(r["Z-Q3"]["low"], r["Z-Q3"]["high"])
    last = r["rows"][-1]
    assert (
        last["rmse_noisy"] > last["rmse_monte_carlo"]
    )  # the noisy estimator is no better than Monte Carlo


def test_qaoa_vqe_reservoir_and_tensor_verdicts_follow_from_their_numbers() -> None:
    q = load("quantum_qaoa")
    ratio = float(np.median([x["p3"]["approximation_ratio"] for x in q["rows"]]))
    prob = float(np.median([x["p3"]["optimum_probability"] for x in q["rows"]]))
    assert q["Z-Q4"] == threshold_verdict(-ratio, -0.95, -0.85)
    assert q["Z-Q5"] == ("SUPPORTED" if prob >= 10 / 256 else "CONTRADICTED")
    check_difference(
        q["Z-Q6"],
        [x["p3"]["approximation_ratio"] - x["p1"]["approximation_ratio"] for x in q["rows"]],
    )
    v = load("quantum_vqe")
    assert v["Z-Q7"] == threshold_verdict(
        float(np.median([x["layers4"] for x in v["rows"]])), 0.01, 0.05
    )
    assert v["Z-Q8"] == (
        "SUPPORTED" if v["Z-Q8_worst_gradient_difference"] <= 1e-6 else "CONTRADICTED"
    )
    check_difference(v["Z-Q9"], [x["layers1"] - x["layers4"] for x in v["rows"]])
    res = load("quantum_reservoir")
    check_difference(res["Z-Q10"], [x["ar5"] - x["quantum"] for x in res["rows"]])
    check_difference(res["Z-Q11"], [x["esn"] - x["quantum"] for x in res["rows"]])
    t = load("quantum_tensor")
    by_d = {x["d"]: x for x in t["rows"]}
    smooth = by_d[7]["smooth"]["max_rank"] / by_d[4]["smooth"]["max_rank"]
    kinked = by_d[7]["kinked"]["max_rank"] / by_d[4]["kinked"]["max_rank"]
    assert t["Z-T1"] == ("SUPPORTED" if smooth <= 1.5 and kinked >= 2.0 else "CONTRADICTED")
    worst = max(x[k]["relative_integral_error"] for x in t["rows"] for k in ("kinked", "smooth"))
    assert t["Z-T2"] == ("SUPPORTED" if worst <= 1e-6 else "CONTRADICTED")
    share = by_d[7]["kinked"]["parameters"] / by_d[7]["full_size"]
    assert t["Z-T3"] == ("SUPPORTED" if share <= 0.20 else "CONTRADICTED")


# ----- tranche 5 --------------------------------------------------------------------------------


def test_pipeline_verdicts_follow_from_their_numbers() -> None:
    h = load("pipelines_hedge")
    rows = h["rows"]
    ratio = float(
        np.median([x["risk"]["surrogate"]["std"] / x["risk"]["exact"]["std"] for x in rows])
    )
    tail = float(
        np.median(
            [
                x["risk"]["surrogate"]["expected_shortfall"]
                / x["risk"]["unhedged"]["expected_shortfall"]
                for x in rows
            ]
        )
    )
    assert h["Z-I1"] == threshold_verdict(ratio, 1.5, 3.0)
    assert h["Z-I2"] == threshold_verdict(tail, 0.25, 0.5)
    assert h["Z-I3"] == threshold_verdict(
        float(np.median([x["mean_abs_delta_error"] for x in rows])), 0.05, 0.10
    )
    b = load("pipelines_banks")
    assert b["Z-I4"] == threshold_verdict(b["median_relative_gap_to_direct"], 0.02, 0.05)
    assert b["Z-I5"]["verdict"] == direction_verdict(b["Z-I5"]["low"], b["Z-I5"]["high"])
    assert b["Z-I6"] == ("SUPPORTED" if b["Z-I6_discretisation_error"] < 0.01 else "CONTRADICTED")
    assert b["rmse_quantum"] < b["rmse_monte_carlo"]  # what Z-I5 says
