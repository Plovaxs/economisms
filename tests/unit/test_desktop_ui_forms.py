# ruff: noqa: E402
"""PR-205: the form, through the real widgets.

`test_desktop_forms.py` proves that the *specs* reproduce every runner's default recipe. This file
proves the same thing one layer up: with real line edits, date pickers, combo boxes and check boxes
on screen, reading them back still gives the default recipe, and typing into them behaves.
"""

from __future__ import annotations

from typing import Any

import pytest

from tests.unit import desktop_ui_support as support

support.require_qt()

from PySide6.QtWidgets import QCheckBox, QComboBox, QDateEdit, QLineEdit, QPlainTextEdit

from prometheus.desktop import explorers, forms
from prometheus.desktop.forms import assemble, build_form, initial_values, values_from_config
from prometheus.desktop.ui.formview import FormView
from prometheus.orchestration.recipes import (
    RUNNERS,
    ResourceLimits,
    default_recipe,
    prepare_recipe,
)

KINDS = sorted(RUNNERS)
EXPLORER_NAMES = [e.name for e in explorers.EXPLORERS if e.fields]


def recipe_hash(kind: str, config: dict[str, Any]) -> str:
    return prepare_recipe(kind, config, limits=ResourceLimits()).recipe_sha256


@pytest.mark.parametrize("kind", KINDS)
def test_every_runners_form_widgets_read_back_as_its_default_recipe(qapp: Any, kind: str) -> None:
    specs = build_form(kind)
    view = FormView(specs)
    config, errors = assemble(specs, view.values())
    assert errors == {}
    assert recipe_hash(kind, config) == recipe_hash(kind, default_recipe(kind))
    assert set(view.paths()) == set(initial_values(specs)), "one editor per leaf field"


@pytest.mark.parametrize("name", EXPLORER_NAMES)
def test_every_explorers_form_widgets_read_back_as_valid_defaults(qapp: Any, name: str) -> None:
    view = FormView(explorers.explorer(name).fields, columns=1)
    params, errors = explorers.validate(name, view.values())
    assert errors == {} and params, name
    # the editors hold text ("6"); what matters is that it parses to the explorer's own defaults
    assert params == explorers.validate(name, explorers.defaults(name))[0]


def test_the_right_widget_is_used_for_each_kind_of_field(qapp: Any) -> None:
    view = FormView(build_form("simulation"))
    assert isinstance(view.editor_widget(("seed",)), QLineEdit)
    assert isinstance(view.editor_widget(("start_date",)), QDateEdit)
    assert isinstance(view.editor_widget(("option_type",)), QComboBox)
    assert isinstance(view.editor_widget(("firm_seed_capital", "minor_units")), QLineEdit)
    economy = FormView(build_form("economy"))
    assert isinstance(economy.editor_widget(("require_price_resolution",)), QCheckBox)
    study = FormView(build_form("study"))
    assert isinstance(study.editor_widget(("scenarios",)), QPlainTextEdit)


def test_typing_into_a_field_changes_the_recipe_and_only_that_field(qapp: Any) -> None:
    specs = build_form("inflationcast")
    view = FormView(specs)
    view.editor_widget(("max_epochs",)).setText("25")  # type: ignore[attr-defined]
    view.editor_widget(("validation_split_date",)).setDate(  # type: ignore[attr-defined]
        view.editor_widget(("validation_split_date",)).date().addYears(-1)  # type: ignore[attr-defined]
    )
    config, errors = assemble(specs, view.values())
    baseline = default_recipe("inflationcast")
    assert errors == {}
    assert {k for k in config if config[k] != baseline[k]} == {
        "max_epochs",
        "validation_split_date",
    }
    assert config["max_epochs"] == 25 and config["validation_split_date"] == "2018-01-01"


def test_a_change_is_announced(qapp: Any) -> None:
    view = FormView(build_form("inflationcast"))
    heard: list[int] = []
    view.changed.connect(lambda: heard.append(1))
    view.editor_widget(("seed",)).setText("9")  # type: ignore[attr-defined]
    view.editor_widget(("validation_split_date",)).setDate(  # type: ignore[attr-defined]
        view.editor_widget(("validation_split_date",)).date().addDays(1)  # type: ignore[attr-defined]
    )
    assert len(heard) >= 2


def test_mistakes_are_marked_next_to_the_field_in_words(qapp: Any) -> None:
    specs = build_form("inflationcast")
    view = FormView(specs)
    seed = view.editor_widget(("seed",))
    seed.setText("abc")  # type: ignore[attr-defined]
    view.editor_widget(("calibration_coverage",)).setText("nan")  # type: ignore[attr-defined]
    _, errors = assemble(specs, view.values())
    view.set_errors(errors)
    shown = view.error_texts()
    assert set(shown) == {("seed",), ("calibration_coverage",)}
    assert shown[("seed",)].startswith("✕") and "whole number" in shown[("seed",)]
    assert seed.property("invalid") is True
    view.set_errors({})
    assert view.error_texts() == {} and seed.property("invalid") is False


def test_a_problem_inside_a_collapsed_section_opens_it(qapp: Any) -> None:
    specs = build_form("economy")
    view = FormView(specs)
    section = view.section(("firm_capital",))
    assert not section.is_open, "groups start closed"
    view.set_errors({("firm_capital", "minor_units"): "must be a whole number"})
    assert section.is_open
    assert "✕" in view.error_texts()[("firm_capital", "minor_units")]


def test_nested_groups_open_all_the_way_down(qapp: Any) -> None:
    view = FormView(build_form("monetary"))
    view.set_errors({("economy", "firm_capital", "minor_units"): "x"})
    assert view.section(("economy",)).is_open and view.section(("economy", "firm_capital")).is_open


def test_an_optional_field_is_off_until_it_is_set(qapp: Any) -> None:
    specs = build_form("simulation")
    view = FormView(specs)
    path = ("option_maturity_years",)
    gate = view.gate(path)
    assert gate is not None and not gate.isChecked()
    assert not view.editor_widget(path).isEnabled()
    assert view.values()[path] is None
    gate.setChecked(True)
    assert view.editor_widget(path).isEnabled()
    view.editor_widget(path).setText("0.75")  # type: ignore[attr-defined]
    assert view.values()[path] == "0.75"
    config, errors = assemble(specs, view.values())
    assert errors == {} and config["option_maturity_years"] == 0.75
    gate.setChecked(False)
    assert view.values()[path] is None


def test_an_optional_field_that_has_a_default_starts_on(qapp: Any) -> None:
    view = FormView(build_form("economy"))
    gate = view.gate(("productivity_shock_step",))
    assert gate is not None and gate.isChecked()
    assert view.values()[("productivity_shock_step",)] == "4"


def test_reset_restores_the_defaults_and_clears_errors(qapp: Any) -> None:
    specs = build_form("inflationcast")
    view = FormView(specs)
    view.editor_widget(("seed",)).setText("zzz")  # type: ignore[attr-defined]
    view.set_errors({("seed",): "bad"})
    view.reset()
    assert assemble(specs, view.values()) == assemble(specs, initial_values(specs))
    assert view.error_texts() == {}


def test_a_past_jobs_settings_go_back_into_the_widgets(qapp: Any) -> None:
    specs = build_form("economy")
    view = FormView(specs)
    config = default_recipe("economy")
    config["seed"] = 11
    config["firm_capital"] = {"minor_units": 123_456, "currency": "USD"}
    config["payroll_cash_fraction"] = {"numerator": 3, "denominator": 4}
    config["productivity_shock_step"] = None
    view.set_values(values_from_config(specs, config))
    rebuilt, errors = assemble(specs, view.values())
    assert errors == {}
    assert rebuilt["seed"] == 11
    assert rebuilt["firm_capital"] == {"minor_units": 123456, "currency": "USD"}
    assert recipe_hash("economy", rebuilt) == recipe_hash("economy", config)
    assert view.gate(("productivity_shock_step",)).isChecked() is False  # type: ignore[union-attr]


def test_a_list_of_objects_is_edited_as_json_text(qapp: Any) -> None:
    specs = build_form("study")
    view = FormView(specs)
    box = view.editor_widget(("scenarios",))
    assert isinstance(box, QPlainTextEdit) and '"baseline"' in box.toPlainText()
    box.setPlainText("[{oops")
    _, errors = assemble(specs, view.values())
    assert ("scenarios",) in errors and "JSON" in errors[("scenarios",)]


def test_a_date_widget_rejects_nothing_but_reads_back_iso_text(qapp: Any) -> None:
    view = FormView(build_form("inflationcast"))
    values = view.values()
    assert values[("validation_split_date",)] == "2019-01-01"
    assert values[("test_split_date",)] == "2022-01-01"


def test_every_editor_has_an_accessible_name_and_limits_are_in_the_tooltip(qapp: Any) -> None:
    view = FormView(explorers.explorer("market_paths").fields, columns=1)
    for path in view.paths():
        assert view.editor_widget(path).accessibleName(), path
    assert (
        "greater than 0" in view.editor_widget(("s0",)).toolTip()
        or ">" in view.editor_widget(("s0",)).toolTip()
    )
    assert "≤" in view.editor_widget(("sigma",)).toolTip()


def test_the_values_of_a_form_never_change_what_the_runner_would_default_to(qapp: Any) -> None:
    for kind in KINDS:
        view = FormView(forms.build_form(kind))
        view.reset()
        config, errors = assemble(forms.build_form(kind), view.values())
        assert errors == {}, kind
        assert recipe_hash(kind, config) == recipe_hash(kind, default_recipe(kind)), kind
