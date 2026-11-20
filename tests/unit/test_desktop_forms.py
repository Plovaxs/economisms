"""PR-205: forms derived from the runners' typed configs.

The central claim: for every one of the 16 runners, the form the window shows first reproduces the
runner's own default recipe *exactly* (same recipe hash after the real typed decoding), so the
window cannot drift from what a runner accepts, and a runner whose config contains a type the form
cannot show fails here instead of disappearing from the window.
"""

from __future__ import annotations

import contextlib
import copy
import math
from datetime import date, datetime
from fractions import Fraction
from typing import Any, cast

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from prometheus.desktop import forms
from prometheus.desktop.forms import (
    FieldSpec,
    UnsupportedFieldError,
    assemble,
    build_form,
    find,
    humanize,
    initial_values,
    leaves,
    parse_value,
)
from prometheus.orchestration.recipes import RUNNERS, ResourceLimits, default_recipe, prepare_recipe

KINDS = sorted(RUNNERS)


def _spec(kind: forms.FieldKind, **extra: Any) -> FieldSpec:
    return FieldSpec(key="x", path=("x",), label="X", kind=kind, default=None, **extra)


# ------------------------------------------------------------------ the central claim


@pytest.mark.parametrize("kind", KINDS)
def test_every_runner_has_a_form_that_reproduces_its_default_recipe(kind: str) -> None:
    specs = build_form(kind)
    config, errors = assemble(specs, initial_values(specs))
    assert errors == {}
    assert (
        prepare_recipe(kind, config, limits=ResourceLimits()).recipe_sha256
        == prepare_recipe(kind, default_recipe(kind), limits=ResourceLimits()).recipe_sha256
    )


@pytest.mark.parametrize("kind", KINDS)
def test_every_leaf_field_is_an_editable_kind_with_a_unique_path(kind: str) -> None:
    specs = build_form(kind)
    paths = [spec.path for spec in leaves(specs)]
    assert paths and len(paths) == len(set(paths))
    assert all(spec.kind != "group" for spec in leaves(specs))
    assert {spec.key for spec in specs} == set(default_recipe(kind)), "no top-level field is lost"


def test_nested_fields_are_reachable_not_collapsed_away() -> None:
    # every nested Money/policy/hedge field is reachable, not collapsed away
    specs = build_form("monetary")
    assert find(specs, ("economy", "firm_capital", "minor_units")).kind == "int"
    assert find(specs, ("policy", "neutral_rate")).kind == "float"
    assert find(specs, ("hedge", "option_type")).choices == ("call", "put")


def test_changing_a_field_changes_the_recipe_and_only_that_field() -> None:
    specs = build_form("inflationcast")
    values = initial_values(specs)
    values[("seed",)] = 7
    values[("max_epochs",)] = "25"
    config, errors = assemble(specs, values)
    assert errors == {}
    assert config["seed"] == 7 and config["max_epochs"] == 25
    baseline = default_recipe("inflationcast")
    assert {k for k in config if config[k] != baseline[k]} == {"seed", "max_epochs"}
    assert (
        prepare_recipe("inflationcast", config).recipe_sha256
        != prepare_recipe("inflationcast", baseline).recipe_sha256
    )


# ------------------------------------------------------------------ what the specs say


def test_field_kinds_follow_the_annotations() -> None:
    specs = build_form("economy")
    assert find(specs, ("seed",)).kind == "int"
    assert find(specs, ("start_date",)).kind == "date"
    assert find(specs, ("firm_capital",)).kind == "group"
    assert find(specs, ("firm_capital", "currency")).kind == "text"
    assert find(specs, ("payroll_cash_fraction",)).kind == "fraction"
    assert find(specs, ("payroll_cash_fraction",)).default == "1"
    assert find(specs, ("require_price_resolution",)).kind == "bool"


def test_optional_fields_remember_a_value_to_show_when_switched_on() -> None:
    shock = find(build_form("economy"), ("productivity_shock_step",))
    assert shock.optional and shock.kind == "int"
    assert shock.fallback == 0
    option_maturity = find(build_form("simulation"), ("option_maturity_years",))
    assert option_maturity.optional and option_maturity.default is None
    assert option_maturity.fallback == 0.0


def test_literals_become_choices_and_lists_become_text() -> None:
    simulation = build_form("simulation")
    assert find(simulation, ("option_type",)).choices == ("call", "put")
    benchmark = build_form("benchmark")
    seeds = find(benchmark, ("test_seeds",))
    assert seeds.kind == "list" and seeds.element == "int"
    assert seeds.default == ", ".join(str(s) for s in default_recipe("benchmark")["test_seeds"])
    assert find(build_form("rl_hedge"), ("reward_objective",)).choices == ("mean_loss", "cvar")


def test_a_list_of_objects_is_edited_as_json_and_a_list_of_strings_with_commas_too() -> None:
    study = build_form("study")
    scenarios = find(study, ("scenarios",))
    assert scenarios.kind == "json" and '"baseline"' in scenarios.default
    assert find(study, ("training_seeds",)).kind == "json"
    assert find(build_form("qmacro"), ("feature_series_ids",)).kind == "list"
    comma = forms._spec("tags", tuple[str, ...], ["a,b", "c"], ("tags",))
    assert comma.kind == "json", "a string containing a comma cannot survive a comma-separated list"


def test_an_unsupported_annotation_fails_loudly() -> None:
    with pytest.raises(UnsupportedFieldError, match="no form editor"):
        forms._spec("x", dict, {}, ("x",))
    with pytest.raises(UnsupportedFieldError, match="only `X \\| None`"):
        forms._spec("x", int | str, 1, ("x",))
    with pytest.raises(UnsupportedFieldError):
        forms._spec("x", int | str | None, 1, ("x",))


def test_find_reports_an_unknown_path() -> None:
    with pytest.raises(KeyError):
        find(build_form("inflationcast"), ("no_such_field",))


@pytest.mark.parametrize(
    ("name", "label"),
    [
        ("n_train_paths", "Number of train paths"),
        ("n", "N"),
        ("seed", "Seed"),
        ("cvar_alpha", "CVaR alpha"),
        ("gru_units", "GRU units"),
        ("pinn_epochs", "PINN epochs"),
        ("firm_opening_capital_minor_units", "Firm opening capital minor units"),
        ("test_seeds", "Test seeds"),
        ("__", ""),
    ],
)
def test_labels_are_readable(name: str, label: str) -> None:
    assert humanize(name) == label


# ------------------------------------------------------------------ parsing what people type


@pytest.mark.parametrize(
    ("raw", "expected"),
    [(7, 7), ("42", 42), (" -3 ", -3), ("+5", 5), (4.0, 4), ("000", 0), (-1, -1)],
)
def test_integers_accept_what_a_person_means(raw: Any, expected: int) -> None:
    assert parse_value(_spec("int"), raw) == expected


@pytest.mark.parametrize(
    "raw",
    [
        True,
        False,
        1.5,
        "1.5",
        "1e3",
        "1_000",
        "0x10",
        "",
        " ",
        "abc",
        "٣",
        "1" * 19,
        None,
        [1],
        math.inf,
    ],
)
def test_integers_reject_everything_else(raw: Any) -> None:
    with pytest.raises(ValueError, match="whole number"):
        parse_value(_spec("int"), raw)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (1, 1.0),
        ("0.5", 0.5),
        (" -2.25 ", -2.25),
        (".5", 0.5),
        ("5.", 5.0),
        ("1e3", 1000.0),
        ("2E-2", 0.02),
    ],
)
def test_floats_accept_plain_decimals(raw: Any, expected: float) -> None:
    assert parse_value(_spec("float"), raw) == expected


@pytest.mark.parametrize(
    "raw",
    ["nan", "inf", "-inf", "Infinity", "1_000", "0x10", "1e9999", "", "1,5", "--1", True, None],
)
def test_floats_reject_what_python_would_quietly_accept(raw: Any) -> None:
    with pytest.raises(ValueError, match="number"):
        parse_value(_spec("float"), raw)


def test_a_non_finite_float_object_is_refused_too() -> None:
    for value in (math.nan, math.inf, -math.inf):
        with pytest.raises(ValueError, match="finite"):
            parse_value(_spec("float"), value)


def test_numeric_bounds_are_enforced_with_a_message_naming_the_limit() -> None:
    bounded = _spec("float", minimum=0.0, exclusive_minimum=True, maximum=10.0)
    assert parse_value(bounded, "0.001") == 0.001
    with pytest.raises(ValueError, match="greater than 0"):
        parse_value(bounded, "0")
    with pytest.raises(ValueError, match="at most 10"):
        parse_value(bounded, "10.5")
    closed = _spec("int", minimum=1, maximum=5)
    assert parse_value(closed, 1) == 1 and parse_value(closed, 5) == 5
    with pytest.raises(ValueError, match="at least 1"):
        parse_value(closed, 0)


@pytest.mark.parametrize(
    "raw", ["2026-01-31", " 2026-01-31 ", date(2026, 1, 31), datetime(2026, 1, 31, 13, 45)]
)
def test_dates_accept_iso_text_and_date_objects(raw: Any) -> None:
    assert parse_value(_spec("date"), raw) == "2026-01-31"


@pytest.mark.parametrize(
    "raw",
    [
        "20260131",
        "2026-1-31",
        "2026-13-01",
        "2026-02-30",
        "2026-W05-1",
        "31/01/2026",
        "",
        20260131,
        None,
    ],
)
def test_dates_reject_other_spellings_python_would_parse(raw: Any) -> None:
    with pytest.raises(ValueError, match="calendar date"):
        parse_value(_spec("date"), raw)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("3/10", (3, 10)),
        ("0.25", (1, 4)),
        ("1", (1, 1)),
        (" 2/4 ", (1, 2)),
        ("-1/3", (-1, 3)),
        (".5", (1, 2)),
        ("1e-2", (1, 100)),
        (Fraction(7, 8), (7, 8)),
        (3, (3, 1)),
    ],
)
def test_fractions_are_exact_ratios(raw: Any, expected: tuple[int, int]) -> None:
    assert parse_value(_spec("fraction"), raw) == {
        "numerator": expected[0],
        "denominator": expected[1],
    }


@pytest.mark.parametrize("raw", ["1/0", "abc", "1/2/3", "1_0", "", "nan", True, None, "1 / 2"])
def test_bad_fractions_are_reported_never_raised_as_other_errors(raw: Any) -> None:
    with pytest.raises(ValueError, match="number or a ratio|denominator"):
        parse_value(_spec("fraction"), raw)


def test_lists_are_comma_separated_and_name_the_bad_item() -> None:
    ints = _spec("list", element="int")
    assert parse_value(ints, "1, 2,3") == [1, 2, 3]
    assert parse_value(ints, "") == [] and parse_value(ints, "  ") == []
    with pytest.raises(ValueError, match="item 2 must be a whole number"):
        parse_value(ints, "1, x, 3")
    floats = _spec("list", element="float")
    assert parse_value(floats, "0.5, 1e-2") == [0.5, 0.01]
    with pytest.raises(ValueError, match="item 1"):
        parse_value(floats, "nan")
    assert parse_value(_spec("list", element="text"), "a, b ,c") == ["a", "b", "c"]
    with pytest.raises(ValueError, match="comma-separated"):
        parse_value(ints, 5)


def test_json_fields_report_where_the_syntax_broke() -> None:
    json_field = _spec("json")
    assert parse_value(json_field, '[{"a": 1}]') == [{"a": 1}]
    with pytest.raises(ValueError, match=r"line 2, column"):
        parse_value(json_field, "[\n{oops]")
    with pytest.raises(ValueError, match="JSON list"):
        parse_value(json_field, '{"a": 1}')
    with pytest.raises(ValueError, match="JSON text"):
        parse_value(json_field, 3)


def test_choices_booleans_and_text_are_checked() -> None:
    choice = _spec("choice", choices=("call", "put"))
    assert parse_value(choice, "put") == "put"
    with pytest.raises(ValueError, match="one of: call, put"):
        parse_value(choice, "straddle")
    assert parse_value(_spec("bool"), True) is True
    with pytest.raises(ValueError, match="on or off"):
        parse_value(_spec("bool"), "yes")
    assert parse_value(_spec("text"), "USD") == "USD"
    with pytest.raises(ValueError, match="text"):
        parse_value(_spec("text"), 3)
    with pytest.raises(ValueError, match="cannot be edited"):
        parse_value(_spec("group"), 1)


# ------------------------------------------------------------------ assembling a whole form


def test_every_problem_is_reported_at_once_keyed_by_field() -> None:
    specs = build_form("inflationcast")
    values = initial_values(specs)
    values[("seed",)] = "x"
    values[("validation_split_date",)] = "yesterday"
    values[("calibration_coverage",)] = "nan"
    config, errors = assemble(specs, values)
    assert set(errors) == {("seed",), ("validation_split_date",), ("calibration_coverage",)}
    assert "seed" not in config and "max_epochs" in config


def test_optional_fields_may_be_unset_but_required_ones_may_not() -> None:
    specs = build_form("economy")
    values = initial_values(specs)
    values[("productivity_shock_step",)] = None
    config, errors = assemble(specs, values)
    assert errors == {} and config["productivity_shock_step"] is None
    values[("seed",)] = None
    _, errors = assemble(specs, values)
    assert errors == {("seed",): "is required"}


def test_a_value_missing_from_a_nested_group_is_reported_at_its_full_path() -> None:
    specs = build_form("economy")
    values = initial_values(specs)
    del values[("firm_capital", "currency")]
    _, errors = assemble(specs, values)
    assert errors == {("firm_capital", "currency"): "is required"}


def test_the_inputs_are_never_mutated() -> None:
    specs = build_form("study")
    values = initial_values(specs)
    snapshot = copy.deepcopy(values)
    assemble(specs, values)
    assert values == snapshot


def test_an_edited_list_of_objects_flows_through_the_real_validation() -> None:
    specs = build_form("study")
    values = initial_values(specs)
    values[("scenarios",)] = (
        '[{"name": "baseline", "mu": 0.08, "volatility": 0.2, "cost_rate": 0.005},'
        ' {"name": "stress", "mu": 0.0, "volatility": 0.45, "cost_rate": 0.01}]'
    )
    config, errors = assemble(specs, values)
    assert errors == {} and [s["name"] for s in config["scenarios"]] == ["baseline", "stress"]
    assert prepare_recipe("study", config, limits=ResourceLimits()).recipe_sha256


# ------------------------------------------------------------------ hostile input


@pytest.mark.parametrize(
    "kind", ["int", "float", "date", "fraction", "list", "json", "choice", "bool", "text"]
)
@settings(max_examples=200, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(raw=st.one_of(st.text(), st.integers(), st.floats(), st.binary(), st.none(), st.booleans()))
def test_no_input_makes_the_parser_raise_anything_but_value_error(kind: str, raw: Any) -> None:
    spec = _spec(cast(forms.FieldKind, kind), choices=("a", "b"), element="int")
    with contextlib.suppress(ValueError):
        parse_value(spec, raw)
