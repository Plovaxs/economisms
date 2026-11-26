"""PR-205: the explorers -- the dashboard's views as direct, child-process computations.

Three kinds of claim are pinned here. (1) The parameter bounds and defaults are the dashboard's
own, so an explorer cannot be asked for what the web view would refuse. (2) The picture an
explorer adds (a percentile fan, an option-value curve) agrees with the headline numbers beside
it, because both come from the same seeded simulation. (3) The child process fails closed: a
request that skips the window's validation is refused, a slow calculation can be timed out or
cancelled, and neither leaves a process behind.
"""

from __future__ import annotations

import io
import json
import math
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import pytest

from prometheus.dashboard import app as dashboard_app
from prometheus.dashboard.params import SEED_RANGE
from prometheus.dashboard.views import economy_explorer_as_json
from prometheus.desktop import compute_child, explorers
from prometheus.desktop.explorer_runner import ExplorerError, ExplorerTask, run_explorer
from prometheus.desktop.explorers import EXPLORERS, compute, defaults, explorer, validate
from prometheus.desktop.results import analyze_payload

NAMES = [e.name for e in EXPLORERS]


def params_for(name: str, **changes: Any) -> dict[str, Any]:
    values = defaults(name)
    for key, value in changes.items():
        values[(key,)] = value
    params, errors = validate(name, values)
    assert errors == {}, errors
    return params


def child_processes() -> list[int]:
    found = []
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit():
            continue
        try:
            parent = int((entry / "stat").read_text().rsplit(")", 1)[1].split()[1])
            command = (entry / "cmdline").read_bytes()
        except (OSError, ValueError, IndexError):
            continue
        if parent == os.getpid() and b"prometheus.desktop.compute_child" in command:
            found.append(int(entry.name))
    return found


# ------------------------------------------------------------------ the registry


def test_the_registry_is_complete_and_consistent() -> None:
    assert len(NAMES) == len(set(NAMES)) == 8
    for entry in EXPLORERS:
        keys = [spec.key for spec in entry.fields]
        assert len(keys) == len(set(keys)), entry.name
        assert entry.summary.endswith(".") and entry.title
        assert explorer(entry.name) is entry
    with pytest.raises(KeyError):
        explorer("nonsense")


def test_importing_the_explorers_loads_neither_numpy_nor_torch() -> None:
    code = (
        "import sys; import prometheus.desktop.explorers, prometheus.desktop.results; "
        "print('numpy' in sys.modules, 'torch' in sys.modules)"
    )
    shown = subprocess.run(  # noqa: S603 - fixed argv, this interpreter, a fixed snippet
        [sys.executable, "-I", "-c", code], capture_output=True, text=True, check=True
    ).stdout.split()
    assert shown == ["False", "False"], "the window's own process must stay light"


# ------------------------------------------------------------------ the dashboard's bounds


def bounds(name: str, key: str) -> tuple[float | None, float | None, bool]:
    spec = next(s for s in explorer(name).fields if s.key == key)
    return spec.minimum, spec.maximum, spec.exclusive_minimum


@pytest.mark.parametrize(
    ("name", "key", "dashboard"),
    [
        ("market_paths", "s0", dashboard_app._PRICE),
        ("market_paths", "mu", dashboard_app._DRIFT),
        ("market_paths", "sigma", dashboard_app._VOLATILITY),
        ("market_paths", "maturity", dashboard_app._MATURITY),
        ("hedge_actions", "s0", dashboard_app._PRICE),
        ("hedge_actions", "strike", dashboard_app._PRICE),
        ("hedge_actions", "mu", dashboard_app._DRIFT),
        ("hedge_actions", "sigma", dashboard_app._VOLATILITY),
        ("hedge_actions", "maturity", dashboard_app._MATURITY),
        ("hedge_actions", "risk_free_rate", dashboard_app._RATE),
        ("pricing", "spot", dashboard_app._PRICE),
        ("pricing", "strike", dashboard_app._PRICE),
        ("pricing", "maturity", dashboard_app._MATURITY),
        ("pricing", "volatility", dashboard_app._VOLATILITY),
        ("pricing", "rate", dashboard_app._RATE),
        ("portfolio_risk", "alpha", dashboard_app._ALPHA),
    ],
)
def test_a_float_bound_is_the_dashboards_own(name: str, key: str, dashboard: Any) -> None:
    assert bounds(name, key) == (dashboard.lo, dashboard.hi, dashboard.lo_open)


def test_the_integer_bounds_and_cell_limits_are_the_dashboards_own() -> None:
    # the dashboard states these as literals inside its route handlers; they are restated here
    # and checked against the handlers' behaviour in test_dashboard_*, so a change to either side
    # breaks one of the two
    assert bounds("economy", "n_steps")[:2] == (1, 120)
    assert bounds("market_paths", "n_steps")[:2] == (1, 365)
    assert bounds("market_paths", "n_paths")[:2] == (1, 20_000)
    assert bounds("hedge_actions", "n_steps")[:2] == (1, 250)
    assert bounds("hedge_actions", "n_paths")[:2] == (1, 5000)
    assert bounds("portfolio_risk", "n")[:2] == (10, 100_000)
    for name in ("economy", "market_paths", "hedge_actions", "portfolio_risk"):
        assert bounds(name, "seed")[:2] == SEED_RANGE
    assert explorers.MAX_MARKET_PATH_CELLS == dashboard_app._MAX_MARKET_PATH_CELLS
    assert explorers.MAX_HEDGE_CELLS == dashboard_app._MAX_HEDGE_CELLS


def test_the_defaults_are_the_dashboards_route_defaults() -> None:
    def dflt(name: str) -> dict[str, Any]:
        return {path[0]: value for path, value in defaults(name).items()}

    assert dflt("economy") == {"n_steps": 6, "seed": 0}
    assert dflt("market_paths") == {
        "s0": 100.0,
        "mu": 0.05,
        "sigma": 0.2,
        "maturity": 1.0,
        "n_steps": 50,
        "n_paths": 2000,
        "seed": 0,
    }
    assert dflt("hedge_actions") == {
        "s0": 100.0,
        "mu": 0.05,
        "sigma": 0.2,
        "strike": 100.0,
        "maturity": 1.0,
        "risk_free_rate": 0.03,
        "n_steps": 20,
        "n_paths": 200,
        "seed": 0,
    }
    pricing = dflt("pricing")
    assert (pricing["spot"], pricing["strike"], pricing["rate"]) == (100.0, 100.0, 0.03)
    assert (pricing["maturity"], pricing["volatility"]) == (1.0, 0.2)
    assert dflt("portfolio_risk") == {"seed": 0, "n": 250, "alpha": 0.95}


# ------------------------------------------------------------------ validation


@pytest.mark.parametrize("name", NAMES)
def test_every_explorer_accepts_its_own_defaults(name: str) -> None:
    params, errors = validate(name, defaults(name))
    assert errors == {} and set(params) == {s.key for s in explorer(name).fields}


def test_a_value_outside_its_range_is_named_with_the_limit() -> None:
    values = defaults("economy")
    values[("n_steps",)] = 121
    _, errors = validate("economy", values)
    assert errors == {("n_steps",): "must be at most 120"}
    values[("n_steps",)] = 0
    assert validate("economy", values)[1] == {("n_steps",): "must be at least 1"}


def test_the_edges_of_every_range_are_accepted() -> None:
    values = defaults("market_paths")
    values.update({("sigma",): 0.001, ("maturity",): 50.0, ("n_steps",): 1, ("n_paths",): 20_000})
    assert validate("market_paths", values)[1] == {}
    values[("s0",)] = 0.0
    assert validate("market_paths", values)[1] == {("s0",): "must be greater than 0"}


def test_two_parameters_that_are_fine_alone_can_be_too_much_together() -> None:
    values = defaults("market_paths")
    values.update({("n_steps",): 365, ("n_paths",): 20_000})
    _, errors = validate("market_paths", values)
    assert list(errors) == [()] and "must not exceed 2,000,000" in errors[()]
    hedge = defaults("hedge_actions")
    hedge.update({("n_steps",): 250, ("n_paths",): 5000})
    assert "500,000" in validate("hedge_actions", hedge)[1][()]


def test_a_nonsense_value_is_reported_not_raised() -> None:
    values = defaults("pricing")
    values[("volatility",)] = "nan"
    values[("option_type",)] = "straddle"
    _, errors = validate("pricing", values)
    assert set(errors) == {("volatility",), ("option_type",)}


# ------------------------------------------------------------------ real computations


def test_the_economy_explorer_returns_exactly_what_the_dashboard_computes() -> None:
    params = params_for("economy", n_steps=5, seed=3)
    payload = run_explorer("economy", params)
    here = json.loads(json.dumps(economy_explorer_as_json(n_steps=5, seed=3)))
    assert payload["steps"] == here["steps"] and payload["shocks"] == here["shocks"]
    assert len(payload["steps"]) == 5


def test_the_market_fan_agrees_with_the_summary_it_sits_beside() -> None:
    payload = run_explorer(
        "market_paths", params_for("market_paths", n_steps=40, n_paths=500, seed=5)
    )
    fan = payload["fan"]
    assert len(fan["x"]) == 41 and fan["x"][0] == 0.0 and fan["x"][-1] == pytest.approx(1.0)
    lower, median, upper = fan["5th percentile"], fan["Median"], fan["95th percentile"]
    assert all(low <= mid <= high for low, mid, high in zip(lower, median, upper, strict=True))
    assert lower[0] == median[0] == upper[0] == 100.0, "every path starts at the starting price"
    assert (lower[-1], median[-1], upper[-1]) == (payload["p5"], payload["p50"], payload["p95"])
    assert min(lower) > 0, "a geometric Brownian motion never goes negative"


def test_the_option_curve_agrees_with_the_price_and_obeys_put_call_parity() -> None:
    call = run_explorer("pricing", params_for("pricing"))
    curve = call["value_curve"]
    middle = curve["x"].index(100.0)
    assert curve["Option value"][middle] == pytest.approx(call["price"], rel=1e-12)
    assert all(
        v >= p - 1e-9 for v, p in zip(curve["Option value"], curve["Payoff at expiry"], strict=True)
    )
    assert all(0.0 <= d <= 1.0 for d in call["delta_curve"]["Delta"])
    assert call["delta_curve"]["Delta"] == sorted(call["delta_curve"]["Delta"])

    put = run_explorer("pricing", params_for("pricing", option_type="put"))
    assert all(-1.0 <= d <= 0.0 for d in put["delta_curve"]["Delta"])
    # C - P = S - K e^{-rT}, at every spot on the curve
    for spot, c, p in zip(
        curve["x"], curve["Option value"], put["value_curve"]["Option value"], strict=True
    ):
        assert c - p == pytest.approx(spot - 100.0 * math.exp(-0.03 * 1.0), abs=1e-9)


def test_the_hedge_ratios_are_deltas() -> None:
    payload = run_explorer("hedge_actions", params_for("hedge_actions", n_steps=12, n_paths=50))
    ratios = payload["ratios_path_0"]
    assert len(ratios) >= 12 and all(0.0 <= r <= 1.0 for r in ratios)


def test_portfolio_risk_is_internally_consistent() -> None:
    payload = run_explorer("portfolio_risk", params_for("portfolio_risk", n=400, alpha=0.9, seed=2))
    assert payload["es"] >= payload["var"] > 0
    assert payload["drawdown"] <= 0, "titan.risk_metrics.max_drawdown is documented as <= 0"
    histogram = payload["loss_histogram"]
    assert sum(histogram["Observations"]) == 400
    assert len(histogram["x"]) == len(histogram["Observations"]) == explorers.HISTOGRAM_BINS
    big = run_explorer("portfolio_risk", params_for("portfolio_risk", n=100_000))
    assert len(big["cumulative_pnl"]) <= explorers.MAX_SERIES_POINTS + 1


def test_the_governance_views_return_the_recorded_rows() -> None:
    from prometheus.evidence.validation_issue_tracker import REAL_FINDINGS

    findings = run_explorer("validation_issues", {})["findings"]
    assert [f["finding_id"] for f in findings] == [f.finding_id for f in REAL_FINDINGS]
    rows = run_explorer("experiments", {})["rows"]
    assert rows and {"experiment", "metric_name"} <= set(rows[0])


@pytest.mark.parametrize("name", NAMES)
def test_every_explorer_result_reads_into_something_to_look_at(name: str) -> None:
    payload = run_explorer(name, params_for(name))
    view = analyze_payload(payload, kind=name, title=name)
    assert view.tables or view.charts or view.metrics
    assert all(len(line.y) >= 2 for chart in view.charts for line in chart.lines)


def test_the_same_request_gives_the_same_answer_in_a_fresh_process() -> None:
    params = params_for("market_paths", n_paths=300, seed=11)
    assert run_explorer("market_paths", params) == run_explorer("market_paths", params)
    assert run_explorer("market_paths", params) != run_explorer(
        "market_paths", params_for("market_paths", n_paths=300, seed=12)
    )


def test_compute_in_process_matches_the_child() -> None:
    params = params_for("economy", n_steps=4)
    assert json.loads(json.dumps(compute("economy", params), default=str)) == run_explorer(
        "economy", params
    )


# ------------------------------------------------------------------ the child fails closed


def run_child(request: bytes) -> tuple[int, dict[str, Any]]:
    done = subprocess.run(  # noqa: S603 - fixed argv, this interpreter, a fixed module
        [sys.executable, "-m", "prometheus.desktop.compute_child"],
        input=request,
        capture_output=True,
        timeout=60,
    )
    return done.returncode, json.loads(done.stdout)


def request(**fields: Any) -> bytes:
    body: dict[str, Any] = {
        "explorer": "economy",
        "params": {"n_steps": 3, "seed": 0},
        "timeout": 30,
    }
    body.update(fields)
    return json.dumps(body).encode()


@pytest.mark.parametrize(
    ("raw", "message"),
    [
        (b"not json", "not valid JSON"),
        (b"\xff\xfe", "not valid JSON"),
        (b'{"explorer": "economy", "params": {}, "timeout": NaN}', "not valid JSON"),
        (b"[1, 2]", "wrong shape"),
        (b"x" * 70_000, "too large"),
        (request(extra=1), "wrong shape"),
        (request(params="x"), "wrong shape"),
        (request(explorer=3), "wrong shape"),
        (request(explorer="nonsense"), "unknown explorer"),
        (request(timeout=0), "time limit"),
        (request(timeout=-5), "time limit"),
        (request(timeout=10**9), "time limit"),
        (request(timeout=True), "time limit"),
        (request(timeout="30"), "time limit"),
        (request(params={"n_steps": 3}), "do not match"),
        (request(params={"n_steps": 3, "seed": 0, "extra": 1}), "do not match"),
        (request(params={"n_steps": 10**12, "seed": 0}), "n_steps must be at most 120"),
        (request(params={"n_steps": "three", "seed": 0}), "n_steps must be a whole number"),
        (request(params={"n_steps": 3, "seed": -1}), "seed must be at least 0"),
    ],
)
def test_a_bad_request_is_refused_with_one_short_line(raw: bytes, message: str) -> None:
    status, reply = run_child(raw)
    assert status == 2 and reply["ok"] is False and message in reply["error"]
    assert "Traceback" not in reply["error"] and len(reply["error"]) <= 300


def test_a_request_that_skips_the_windows_validation_still_cannot_ask_for_too_much() -> None:
    huge = {
        "s0": 100.0,
        "mu": 0.05,
        "sigma": 0.2,
        "maturity": 1.0,
        "n_steps": 365,
        "n_paths": 20_000,
        "seed": 0,
    }
    status, reply = run_child(request(explorer="market_paths", params=huge))
    assert status == 2 and "must not exceed 2,000,000" in reply["error"]


def test_a_failure_inside_a_computation_becomes_one_line(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(_: Any) -> dict[str, Any]:
        raise ZeroDivisionError("division by zero")

    monkeypatch.setitem(explorers._COMPUTE, "economy", boom)
    monkeypatch.setattr(compute_child, "_limit_resources", lambda _: None)
    monkeypatch.setattr(sys, "stdin", types_stdin(request()))
    assert compute_child.main() == 2


def types_stdin(raw: bytes) -> Any:
    class Stream:
        buffer = io.BytesIO(raw)

    return Stream()


def test_a_result_that_is_not_finite_is_refused_not_shown(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setitem(explorers._COMPUTE, "economy", lambda _: {"x": float("nan")})
    monkeypatch.setattr(compute_child, "_limit_resources", lambda _: None)
    monkeypatch.setattr(sys, "stdin", types_stdin(request()))
    assert compute_child.main() == 2
    reply = json.loads(capsys.readouterr().out)
    assert reply["ok"] is False and "ValueError" in reply["error"]


def test_an_oversized_result_is_refused(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setitem(explorers._COMPUTE, "economy", lambda _: {"x": "y" * 200})
    monkeypatch.setattr(compute_child, "MAX_OUTPUT_BYTES", 100)
    monkeypatch.setattr(compute_child, "_limit_resources", lambda _: None)
    monkeypatch.setattr(sys, "stdin", types_stdin(request()))
    assert compute_child.main() == 2
    assert "too large" in json.loads(capsys.readouterr().out)["error"]


# ------------------------------------------------------------------ time limits and cancelling


def test_a_calculation_that_runs_out_of_time_is_stopped_and_leaves_nothing_behind() -> None:
    started = time.monotonic()
    with pytest.raises(ExplorerError, match="timed out after 0.2 seconds"):
        run_explorer("market_paths", params_for("market_paths"), timeout=0.2)
    assert time.monotonic() - started < 5
    assert child_processes() == []


def test_cancelling_stops_the_calculation_at_once() -> None:
    import threading

    cancel = threading.Event()
    cancel.set()
    with pytest.raises(ExplorerError, match="cancelled"):
        run_explorer("market_paths", params_for("market_paths"), cancel=cancel)
    assert child_processes() == []


def test_a_child_that_dies_without_a_reply_is_reported(monkeypatch: pytest.MonkeyPatch) -> None:
    from prometheus.desktop import explorer_runner

    with pytest.raises(ExplorerError, match=r"stopped unexpectedly \(exit status 3\)"):
        explorer_runner._read_reply(b"", 3)
    with pytest.raises(ExplorerError, match=r"stopped by the system \(SIGXCPU\)"):
        explorer_runner._read_reply(b"", -24)
    with pytest.raises(ExplorerError, match=r"stopped by the system \(signal 999\)"):
        explorer_runner._read_reply(b"", -999)
    with pytest.raises(ExplorerError, match="unreadable"):
        explorer_runner._read_reply(b'{"ok": "yes"}', 0)
    with pytest.raises(ExplorerError, match="unreadable"):
        explorer_runner._read_reply(b'{"ok": true, "payload": [1]}', 0)
    with pytest.raises(ExplorerError, match="the calculation failed"):
        explorer_runner._read_reply(b'{"ok": false}', 2)
    with pytest.raises(ExplorerError, match="too large"):
        explorer_runner._read_reply(b"x" * (compute_child.MAX_OUTPUT_BYTES + 2048), 0)


def test_a_non_finite_parameter_never_reaches_a_process() -> None:
    with pytest.raises(ValueError, match="JSON"):
        run_explorer("economy", {"n_steps": float("nan"), "seed": 0})
    assert child_processes() == []


# ------------------------------------------------------------------ the background task


def test_a_task_delivers_its_payload_without_blocking_the_caller() -> None:
    task = ExplorerTask("economy", params_for("economy", n_steps=3))
    assert not task.done and task.elapsed == 0.0
    task.start()
    assert task.wait(60) and task.done
    assert task.error is None and task.payload is not None and len(task.payload["steps"]) == 3
    assert task.elapsed > 0


def test_a_task_reports_a_failure_as_text() -> None:
    task = ExplorerTask("economy", {"n_steps": 10**9, "seed": 0})
    task.start()
    assert task.wait(60) and task.payload is None
    assert task.error is not None and "n_steps must be at most 120" in task.error


def test_a_task_can_be_cancelled() -> None:
    task = ExplorerTask("market_paths", params_for("market_paths"))
    task.cancel()
    task.start()
    assert task.wait(30)
    assert task.error == "cancelled" and child_processes() == []


def test_the_childs_cpu_limit_is_a_backstop_not_the_wall_limit() -> None:
    """Run in a subprocess: applying an rlimit to the test process itself would be reckless."""
    code = (
        "import resource; from prometheus.desktop import compute_child as c; "
        "c._limit_resources(0.2); print(resource.getrlimit(resource.RLIMIT_CPU)[0], "
        "resource.getrlimit(resource.RLIMIT_CORE)[0])"
    )
    soft_cpu, soft_core = subprocess.run(  # noqa: S603 - fixed argv, this interpreter
        [sys.executable, "-I", "-c", code], capture_output=True, text=True, check=True
    ).stdout.split()
    assert int(soft_cpu) == compute_child.CPU_BACKSTOP_FLOOR_SECONDS and soft_core == "0"
    assert compute_child.CPU_BACKSTOP_FACTOR >= 4


# ------------------------------------------------------------------ WORLDSIM shock transmission


def test_the_transmission_choices_are_the_worldsim_packages_own() -> None:
    from prometheus.worldsim.calibrated import CALIBRATED_SCENARIOS
    from prometheus.worldsim.config import (
        CONNECTED_SCENARIOS,
        EXTENDED_SCENARIOS,
        SCENARIOS,
        SHOCK_KINDS,
    )
    from prometheus.worldsim.impulse import OUTCOMES

    assert explorers.TRANSMISSION_SCENARIOS == (
        SCENARIOS + EXTENDED_SCENARIOS + CONNECTED_SCENARIOS + CALIBRATED_SCENARIOS
    )
    assert explorers.TRANSMISSION_SHOCKS == SHOCK_KINDS
    assert explorers.TRANSMISSION_OUTCOMES == OUTCOMES


def test_the_transmission_explorer_returns_charts_and_link_tables() -> None:
    payload = compute("worldsim_transmission", params_for("worldsim_transmission", seeds=3))
    assert payload["enters_at"] == "Markets" and payload["synthetic"] is True
    view = analyze_payload(payload, kind="worldsim_transmission", title="Shock transmission")
    assert {"Response macro", "Response markets"} <= {c.title for c in view.charts}
    assert {"Outcomes", "Links"} <= {t.title for t in view.tables}
    links = {row["link"]: row for row in payload["links"]}
    assert links["Household demand"]["significant"] == "yes"


def test_a_transmission_shock_the_scenario_cannot_carry_says_so() -> None:
    payload = compute(
        "worldsim_transmission",
        params_for(
            "worldsim_transmission", scenario="volatile", shock="sovereign_default", seeds=3
        ),
    )
    assert "Nothing to show" in payload["note"] and "links" not in payload
