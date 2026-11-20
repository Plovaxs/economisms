"""PR-205: turning a run's JSON payload into headline numbers, tables and charts.

The rules are tested on small hand-made shapes (so each rule is pinned down by itself) and on the
output of real runners (so the rules are known to fit what this repository actually produces).
"""

from __future__ import annotations

import json
import math
from typing import Any

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from prometheus.desktop import results
from prometheus.desktop.results import (
    MAX_CHART_POINTS,
    MAX_DEPTH,
    MAX_TABLE_ROWS,
    Chart,
    Line,
    analyze_payload,
    build_result_view,
    format_value,
    is_number,
)

DIGEST = "ab" * 32


def view(payload: dict[str, Any]) -> results.ResultView:
    return analyze_payload(payload, kind="demo", title="Demo")


# ------------------------------------------------------------------ small helpers


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (None, "—"),
        (True, "yes"),
        (False, "no"),
        (0, "0"),
        (1234567, "1,234,567"),
        (0.0, "0"),
        (0.31374, "0.3137"),
        (1234.5678, "1235"),
        (123456.789, "123,456.8"),
        (0.0000123, "1.230e-05"),
        (12345678.9, "1.235e+07"),
        (float("nan"), "nan"),
        (float("inf"), "inf"),
        ("naive_persistence", "naive_persistence"),
        ({"minor_units": 5, "currency": "USD"}, "minor_units=5, currency=USD"),
        ([1, 2, 3], "[3 items]"),
    ],
)
def test_values_are_formatted_briefly_and_honestly(value: Any, expected: str) -> None:
    assert format_value(value) == expected


def test_a_very_long_string_is_cut_with_an_ellipsis_not_silently() -> None:
    shown = format_value("x" * 1000)
    assert shown.endswith("…") and len(shown) == results.MAX_TEXT


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (1, True),
        (2.5, True),
        (True, False),
        (False, False),
        (float("nan"), False),
        (float("inf"), False),
        (10**400, False),
        ("3", False),
        (None, False),
    ],
)
def test_a_number_is_a_finite_real_number_and_not_a_bool(value: Any, expected: bool) -> None:
    assert is_number(value) is expected


# ------------------------------------------------------------------ headline numbers


def test_top_level_scalars_are_headline_numbers_and_the_verdict_leads() -> None:
    found = view(
        {
            "schema_version": 1,
            "accounting_convention": "x-v1",
            "best": "naive_persistence",
            "n": 5,
            "verdict": "classical_better",
            "valid": True,
        }
    )
    assert [m.label for m in found.metrics] == ["Verdict", "Best", "N", "Valid"]
    assert found.verdict == "classical_better"
    assert found.metrics[-1].value == "yes"
    assert not found.invalid


def test_hashes_and_long_text_do_not_become_headline_tiles() -> None:
    found = view(
        {
            "verdict": "inconclusive",
            "policy_hash": DIGEST,
            "decision_rule": "All declared scenarios must exceed the margin in the same direction",
            "design_record": "line one\nline two",
            "short": "ok",
        }
    )
    assert [m.label for m in found.metrics] == ["Verdict", "Short"]
    assert [label for label, _ in found.details] == ["Decision rule", "Design record"]
    hashes = next(s for s in found.sections if s.title == "Content hashes")
    assert hashes.items == (("Policy hash", DIGEST),)


def test_only_a_bounded_number_of_tiles_is_shown() -> None:
    found = view({f"k{i:02d}": i for i in range(40)})
    assert len(found.metrics) == results.MAX_METRICS


# ------------------------------------------------------------------ sections and comparisons


def test_a_flat_object_is_a_key_value_section() -> None:
    found = view({"calibration": {"coverage": 0.9, "p_value": 1e-5, "n": 56}})
    section = found.sections[0]
    assert section.title == "Calibration"
    assert section.items == (("Coverage", "0.9"), ("P value", "1.000e-05"), ("N", "56"))


def test_objects_sharing_numeric_keys_are_a_comparison() -> None:
    found = view(
        {
            "models": {
                "naive": {"mae": 0.3, "rmse": 0.4, "epoch": None},
                "gru": {"mae": 3.5, "rmse": 4.1, "epoch": 6},
                "mlp": {"mae": 1.8, "rmse": 2.8, "epoch": 6},
            }
        }
    )
    assert len(found.comparisons) == 1
    comparison = found.comparisons[0]
    assert comparison.columns == ("mae", "rmse", "epoch")
    assert [name for name, _ in comparison.rows] == ["naive", "gru", "mlp"]
    assert comparison.rows[0][1] == (0.3, 0.4, None), "a missing value stays missing"
    assert found.sections == (), "a comparison is not also shown as sections"


def test_a_column_present_in_too_few_rows_is_left_out() -> None:
    found = view({"m": {"a": {"x": 1.0, "rare": 2.0}, "b": {"x": 2.0}, "c": {"x": 3.0}}})
    assert found.comparisons[0].columns == ("x",)


def test_two_objects_without_shared_numbers_are_not_a_comparison() -> None:
    found = view({"m": {"a": {"label": "x"}, "b": {"label": "y"}}})
    assert found.comparisons == ()


def test_a_single_object_is_not_a_comparison() -> None:
    assert view({"m": {"only": {"mae": 1.0}}}).comparisons == ()


# ------------------------------------------------------------------ lists of numbers


def test_a_list_of_numbers_is_a_line_chart() -> None:
    found = view({"training_loss_history": [3.0, 2.0, 1.5, 1.4]})
    chart = found.charts[0]
    assert chart.title == "Training loss history"
    assert chart.lines[0].y == (3.0, 2.0, 1.5, 1.4)
    assert chart.lines[0].x == (0.0, 1.0, 2.0, 3.0)
    assert chart.choices == () and chart.visible() == chart.lines


@pytest.mark.parametrize(
    "values",
    [[1.0, 2.0], [], [True, False, True], [1.0, float("nan"), 3.0], [1, "x", 3], [1.0, None, 3.0]],
)
def test_lists_that_are_not_clean_numbers_are_not_charted(values: list[Any]) -> None:
    assert view({"series": values}).charts == ()


def test_a_long_series_is_thinned_but_keeps_its_first_and_last_point() -> None:
    values = [float(i) for i in range(MAX_CHART_POINTS * 5 + 3)]
    chart = view({"history": values}).charts[0]
    line = chart.lines[0]
    assert len(line.y) <= MAX_CHART_POINTS + 1
    assert line.y[0] == 0.0 and line.y[-1] == values[-1]
    assert chart.original_points == len(values), "the chart says how much it left out"
    assert line.x is not None and len(line.x) == len(line.y)


def test_a_matrix_is_drawn_as_several_lines_together() -> None:
    paths = [[100.0, 101.0, 99.0, 103.0], [100.0, 98.0, 97.0, 99.0]]
    chart = view({"paths": paths}).charts[0]
    assert len(chart.lines) == 2 and not chart.selectable
    assert chart.lines[1].y == tuple(paths[1])


def test_a_matrix_shows_at_most_a_dozen_lines() -> None:
    chart = view({"paths": [[1.0, 2.0, 3.0]] * 30}).charts[0]
    assert len(chart.lines) == results.MAX_LINES


# ------------------------------------------------------------------ lists of records


def _steps(n: int = 5) -> list[dict[str, Any]]:
    return [{"step": i, "price": 100.0 + i, "cash": 50.0 - i, "flat": 7.0} for i in range(n)]


def test_records_become_a_table_and_a_selectable_chart_against_the_step_column() -> None:
    found = view({"steps": _steps()})
    table, chart = found.tables[0], found.charts[0]
    assert table.columns == ("Step", "Price", "Cash", "Flat")
    assert table.numeric == (True, True, True, True)
    assert len(table.rows) == 5 and table.rows[0][:2] == ("0", "100")
    assert chart.selectable and chart.x_label == "Step"
    assert chart.choices == ("Price", "Cash"), "a constant column is not worth a line"
    assert chart.lines[0].x == (0.0, 1.0, 2.0, 3.0, 4.0)


def test_a_chart_shows_the_chosen_series_and_falls_back_to_the_first() -> None:
    chart = view({"steps": _steps()}).charts[0]
    assert [line.name for line in chart.visible("Cash")] == ["Cash"]
    assert [line.name for line in chart.visible("nonsense")] == ["Price"]
    assert [line.name for line in chart.visible(None)] == ["Price"]


def test_a_repeated_step_column_is_split_into_one_line_per_seed() -> None:
    rows = [
        {"epoch": epoch, "seed": seed, "reward": float(epoch * (seed + 1))}
        for seed in (0, 1)
        for epoch in range(4)
    ]
    chart = view({"log": rows}).charts[0]
    assert chart.choices == ("Reward",)
    lines = chart.visible("Reward")
    assert [line.name for line in lines] == ["Seed 0", "Seed 1"]
    assert lines[1].y == (0.0, 2.0, 4.0, 6.0) and lines[1].x == (0.0, 1.0, 2.0, 3.0)


def test_a_seed_is_a_label_not_a_measurement() -> None:
    rows = [{"epoch": i, "seed": 0, "path_seed": i % 3, "loss": 1.0 / (i + 1)} for i in range(6)]
    assert view({"log": rows}).charts[0].choices == ("Loss",)


def test_without_a_step_column_rows_are_plotted_by_position() -> None:
    chart = view({"rows": [{"price": 1.0}, {"price": 2.0}, {"price": 4.0}]}).charts[0]
    assert chart.x_label == "Row" and chart.lines[0].x == (0.0, 1.0, 2.0)


def test_one_record_is_a_table_but_not_a_chart() -> None:
    found = view({"rows": [{"price": 1.0}]})
    assert len(found.tables) == 1 and found.charts == ()


def test_a_long_table_is_cut_and_says_how_much() -> None:
    found = view({"rows": [{"i": i, "v": float(i)} for i in range(MAX_TABLE_ROWS + 50)]})
    table = found.tables[0]
    assert len(table.rows) == MAX_TABLE_ROWS and table.truncated == 50


def test_money_and_fractions_become_numbers_with_their_unit_in_the_label() -> None:
    rows = [
        {
            "step": i,
            "firm_cash": {"minor_units": 1000 * i, "currency": "USD"},
            "sales": {"numerator": 3 * i, "denominator": 2},
            "actions": {"payroll": {"minor_units": 5 * i, "currency": "USD"}, "clamped": False},
        }
        for i in range(4)
    ]
    found = view({"steps": rows})
    columns = found.tables[0].columns
    assert "Firm cash (minor units)" in columns and "Sales" in columns
    assert "Actions › Payroll (minor units)" in columns and "Actions › Clamped" in columns
    chart = found.charts[0]
    assert chart.visible("Firm cash (minor units)")[0].y == (0.0, 1000.0, 2000.0, 3000.0)
    assert chart.visible("Sales")[0].y == (0.0, 1.5, 3.0, 4.5)


def test_a_zero_denominator_does_not_become_a_number() -> None:
    rows = [{"step": i, "ratio": {"numerator": 1, "denominator": 0}} for i in range(3)]
    assert view({"steps": rows}).charts == ()


def test_digest_columns_are_not_shown_in_tables() -> None:
    rows = [{"step": i, "state_hash": DIGEST, "value": float(i)} for i in range(3)]
    assert view({"steps": rows}).tables[0].columns == ("Step", "Value")


def test_lists_inside_records_are_left_to_the_raw_tree_without_failing() -> None:
    rows = [{"step": i, "balances": [["a", 1], ["b", 2]], "value": float(i)} for i in range(3)]
    assert view({"steps": rows}).tables[0].columns == ("Step", "Value")


def test_a_list_of_something_else_is_ignored() -> None:
    assert view({"things": ["a", "b", "c"], "mixed": [1, {"a": 1}, "x"]}).tables == ()


# ------------------------------------------------------------------ notes, validity, configuration


def test_limitations_are_shown_as_notes() -> None:
    found = view({"limitations": ["synthetic data", "single asset"]})
    assert found.notes == (("Limitations", ("synthetic data", "single asset")),)
    assert not found.invalid


def test_a_run_that_reports_itself_invalid_is_flagged() -> None:
    assert view({"invalid_reasons": ["negative cash"]}).invalid
    assert view({"valid": False}).invalid
    assert not view({"invalid_reasons": [], "valid": True}).invalid
    assert view({"invalid_reasons": []}).notes == ()


def test_the_run_configuration_is_listed_separately_and_not_as_a_section() -> None:
    found = view(
        {
            "config": {
                "seed": 7,
                "firm_capital": {"minor_units": 100, "currency": "USD"},
                "test_seeds": [1, 2, 3],
                "economy": {"n_households": 2, "wage": {"minor_units": 5, "currency": "USD"}},
            },
            "evaluation": {"config": {"nested": 1}, "ok": True},
        }
    )
    labels = dict(found.configuration)
    assert labels["Seed"] == "7"
    assert labels["Firm capital"] == "minor_units=100, currency=USD"
    assert labels["Test seeds"] == "1, 2, 3"
    assert labels["Economy › Number of households"] == "2"
    assert "Nested" not in labels, "a nested config repeats the top one"
    assert all("Config" not in section.title for section in found.sections)


def test_pathologically_deep_nesting_is_bounded_not_a_crash() -> None:
    node: dict[str, Any] = {"leaf": 1.0, "other": 2.0}
    for _ in range(MAX_DEPTH * 10):
        node = {"child": node, "x": 1}
    found = view(node)
    assert found.metrics, "the shallow part is still read"


# ------------------------------------------------------------------ artifacts


def _bundle(kind: str, payload: dict[str, Any]) -> dict[str, Any]:
    return {
        kind: payload,
        "job_context": {
            "kind": kind,
            "job_id": "j" * 36,
            "attempt": 1,
            "recipe_sha256": DIGEST,
            "trace_id": "t" * 32,
        },
        "artifact_integrity": {"content_sha256": DIGEST},
        "run_manifest": {"result_hash": DIGEST, "run_id": "r-1", "created_at": "2026-11-20"},
        "runtime": {
            "python": "3.14.7",
            "platform": "Linux",
            "source_sha256": DIGEST,
            "dependencies": {"numpy": "2.5.4"},
        },
        "disclaimer": "SIMULATED DATA -- RESEARCH ONLY.",
    }


def test_a_bundle_is_read_through_its_own_kind_with_provenance() -> None:
    found = build_result_view(_bundle("inflationcast", {"verdict": "classical_better"}))
    assert found.kind == "inflationcast" and found.title == "Inflationcast"
    assert found.verdict == "classical_better"
    assert found.disclaimer.startswith("SIMULATED DATA")
    facts = dict(found.provenance)
    assert facts["Job"] == "j" * 36 and facts["Python"] == "3.14.7" and facts["numpy"] == "2.5.4"
    assert facts["Artifact SHA-256"] == DIGEST and facts["Run id"] == "r-1"


def test_a_bundle_without_its_own_payload_is_refused() -> None:
    bundle = _bundle("inflationcast", {})
    del bundle["inflationcast"]
    with pytest.raises(ValueError, match="no result payload"):
        build_result_view(bundle)
    with pytest.raises(ValueError, match="no result payload"):
        build_result_view({"job_context": {"kind": "x"}, "x": [1, 2]})


# ------------------------------------------------------------------ the chart object itself


def test_a_chart_that_is_not_selectable_draws_everything() -> None:
    lines = (Line("a", (1.0,)), Line("b", (2.0,)))
    chart = Chart("t", "x", lines)
    assert chart.choices == () and chart.visible("a") == lines


def test_lines_of_one_series_are_drawn_together() -> None:
    lines = (
        Line("Seed 0", (1.0,), series="Reward"),
        Line("Seed 1", (2.0,), series="Reward"),
        Line("Seed 0", (3.0,), series="Loss"),
    )
    chart = Chart("t", "x", lines, selectable=True)
    assert chart.choices == ("Reward", "Loss")
    assert len(chart.visible("Reward")) == 2 and len(chart.visible("Loss")) == 1


# ------------------------------------------------------------------ hostile payloads

_JSON = st.recursive(
    st.none()
    | st.booleans()
    | st.integers(min_value=-(10**30), max_value=10**30)
    | st.floats(allow_nan=True, allow_infinity=True)
    | st.text(max_size=70),
    lambda children: (
        st.lists(children, max_size=8) | st.dictionaries(st.text(max_size=12), children, max_size=8)
    ),
    max_leaves=60,
)


@settings(
    max_examples=300,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow, HealthCheck.data_too_large],
)
@given(payload=st.dictionaries(st.text(max_size=12), _JSON, max_size=8))
def test_no_payload_makes_the_analyzer_raise(payload: dict[str, Any]) -> None:
    found = view(payload)
    for chart in found.charts:
        for line in chart.lines:
            assert all(math.isfinite(value) for value in line.y)
            assert len(line.y) <= MAX_CHART_POINTS + 1
    for table in found.tables:
        assert len(table.rows) <= MAX_TABLE_ROWS
        assert all(len(row) == len(table.columns) for row in table.rows)


# ------------------------------------------------------------------ real runner output


def _real(kind: str, **overrides: Any) -> results.ResultView:
    from prometheus.evidence.jsonio import strict_json_loads
    from prometheus.experiments.manifest import json_default
    from prometheus.orchestration.recipes import default_recipe, execute_recipe

    config = default_recipe(kind)
    config.update(overrides)
    raw = execute_recipe(kind, config).evidence_bundle
    # what the window reads is the verified JSON from the artifact store, in which an exact
    # Fraction is already an object of two integers -- never the in-memory Python value
    bundle = strict_json_loads(json.dumps(raw, default=json_default, allow_nan=False))
    bundle["job_context"] = {"kind": kind, "job_id": "0" * 36}
    return build_result_view(bundle)


def test_the_pde_solver_result_is_a_table_of_methods_with_a_chart() -> None:
    found = _real("pde_solver", pinn_epochs=20, bsde_epochs=5)
    table = found.tables[0]
    assert "Method" in table.columns and "Price" in table.columns
    assert len(table.rows) >= 3
    assert found.charts and "Price" in found.charts[0].choices


def test_the_rl_hedge_result_has_a_verdict_and_a_learning_curve() -> None:
    found = _real("rl_hedge", n_epochs=6, n_paths=64)
    assert found.verdict in {"static_better", "trained_better", "inconclusive"}
    chart = found.charts[0]
    assert chart.x_label == "Epoch" and "Mean reward" in chart.choices
    assert "Seed" not in chart.choices


def test_the_economy_result_charts_its_exact_money_and_fraction_columns() -> None:
    found = _real("economy")
    chart = found.charts[0]
    assert chart.x_label == "Step"
    assert any("minor units" in choice for choice in chart.choices)
    assert "Cumulative sales" in chart.choices
    assert any(label == "Limitations" for label, _ in found.notes)
