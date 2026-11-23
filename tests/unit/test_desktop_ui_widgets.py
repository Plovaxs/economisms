# ruff: noqa: E402
"""PR-205: the window's building blocks -- the theme, badges, tiles, tables, the lazy JSON tree,
the chart card with its table view, and the result viewer."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest

from tests.unit import desktop_ui_support as support

support.require_qt()

from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QFileDialog, QTableWidgetSelectionRange

from prometheus.desktop.results import (
    Chart,
    Comparison,
    Line,
    Table,
    analyze_payload,
)
from prometheus.desktop.ui import theme, widgets
from prometheus.desktop.ui.resultview import ResultWidget
from prometheus.desktop.ui.widgets import (
    STATUS_TONES,
    Badge,
    ChartCard,
    DataTable,
    JsonTree,
    Legend,
    MetricTile,
    clear_layout,
    key_value_table,
    parse_number,
    save_text,
)

# ------------------------------------------------------------------ the theme


def test_the_categorical_palette_is_the_validated_reference_palette_unchanged() -> None:
    """If these hexes change, the palette has to be validated again (see `theme.py`)."""
    assert theme.LIGHT.series == (
        "#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#6250d6", "#e34948"
    )  # fmt: skip
    assert theme.DARK.series == (
        "#3987e5", "#d95926", "#199e70", "#c98500", "#d55181", "#008300", "#9085e9", "#e66767"
    )  # fmt: skip
    for palette in (theme.LIGHT, theme.DARK):
        assert len(set(palette.series)) == 8 == len(palette.series)


def test_the_chrome_is_the_reference_chrome() -> None:
    assert (theme.LIGHT.surface, theme.LIGHT.page, theme.LIGHT.ink) == (
        "#fcfcfb",
        "#f9f9f7",
        "#0b0b0b",
    )
    assert (theme.DARK.surface, theme.DARK.page, theme.DARK.ink) == (
        "#1a1a19",
        "#0d0d0d",
        "#f0efec",
    )
    assert (theme.LIGHT.grid, theme.LIGHT.baseline) == ("#e1e0d9", "#c3c2b7")
    assert (theme.DARK.grid, theme.DARK.baseline) == ("#2c2c2a", "#383835")


@pytest.mark.parametrize("palette", [theme.LIGHT, theme.DARK], ids=["light", "dark"])
def test_text_meets_aa_contrast_on_every_surface_it_sits_on(palette: theme.Palette) -> None:
    for surface in (palette.surface, palette.page, palette.raised, palette.sidebar):
        assert theme.contrast_ratio(palette.ink, surface) >= 7.0
        assert theme.contrast_ratio(palette.ink2, surface) >= 4.5
    assert theme.contrast_ratio(palette.on_accent, palette.accent_fill) >= 4.5
    assert theme.contrast_ratio(palette.on_accent, palette.accent_fill_hover) >= 4.5


@pytest.mark.parametrize(("name", "palette"), [("light", theme.LIGHT), ("dark", theme.DARK)])
def test_the_error_text_colour_is_readable_on_its_surface(
    name: str, palette: theme.Palette
) -> None:
    sheet = theme.stylesheet(palette)
    colour = re.search(r'QLabel\[role="error"\] \{ color: (#[0-9a-f]{6})', sheet)
    assert colour is not None
    assert theme.contrast_ratio(colour.group(1), palette.surface) >= 4.5, name


def test_the_contrast_function_is_correct() -> None:
    assert theme.contrast_ratio("#000000", "#ffffff") == pytest.approx(21.0)
    assert theme.contrast_ratio("#ffffff", "#ffffff") == pytest.approx(1.0)


@pytest.mark.parametrize("palette", [theme.LIGHT, theme.DARK], ids=["light", "dark"])
def test_the_style_sheet_has_no_unfilled_placeholder(palette: theme.Palette) -> None:
    sheet = theme.stylesheet(palette)
    assert "$" not in sheet and palette.accent_fill in sheet and palette.surface in sheet


def test_applying_a_theme_sets_the_palette_in_force(qapp: Any) -> None:
    before = theme.current()
    try:
        assert theme.apply_theme(qapp, "light") is theme.LIGHT and theme.current() is theme.LIGHT
        assert theme.apply_theme(qapp, "dark") is theme.DARK
        assert theme.palette_for("system", qapp) in (theme.LIGHT, theme.DARK)
        assert qapp.styleSheet() == theme.stylesheet(theme.DARK)
    finally:
        theme.apply_theme(qapp, before.name)


def _hostile_palette(theme_mode: str) -> Any:
    """What a desktop set to the OPPOSITE scheme hands Qt: dark where the theme is light, and the
    other way round. The first menu bar this app had was dark ink on exactly that."""
    from PySide6.QtGui import QColor, QPalette

    deep = theme_mode == "light"
    hostile = QPalette()
    for role, light_value, dark_value in (
        (QPalette.ColorRole.Window, "#f0f0f0", "#202020"),
        (QPalette.ColorRole.Button, "#e0e0e0", "#323232"),
        (QPalette.ColorRole.Base, "#ffffff", "#141414"),
        (QPalette.ColorRole.Text, "#101010", "#f0f0f0"),
        (QPalette.ColorRole.WindowText, "#101010", "#f0f0f0"),
        (QPalette.ColorRole.Highlight, "#ff00ff", "#ff00ff"),
    ):
        hostile.setColor(role, QColor(dark_value if deep else light_value))
    return hostile


@pytest.fixture
def hostile_desktop(qapp: Any, request: pytest.FixtureRequest) -> Any:
    """Apply `request.param` ("light"/"dark") over a desktop palette of the other scheme."""
    mode = request.param
    before = theme.current()
    qapp.setPalette(_hostile_palette(mode))
    palette = theme.apply_theme(qapp, mode)
    yield palette
    theme.apply_theme(qapp, before.name)


@pytest.mark.parametrize("hostile_desktop", ["light", "dark"], indirect=True)
def test_widgets_the_style_sheet_does_not_paint_take_the_themes_colours(
    hostile_desktop: theme.Palette,
) -> None:
    """A plain list view and a dialog (what a file dialog or a pop-up calendar is made of) have no
    rule in the style sheet, so their colours come from the Qt palette: the theme's, or else the
    desktop's."""
    from PySide6.QtGui import QColor
    from PySide6.QtWidgets import QDialog, QListView

    palette = hostile_desktop
    unstyled = [
        (QListView(), palette.input_background),
        (QDialog(), palette.page),
    ]
    try:
        for widget, _ in unstyled:
            widget.resize(200, 80)
            widget.show()
        support.settle()
        for widget, expected in unstyled:
            pixel = widget.grab().toImage().pixelColor(100, 40)
            assert pixel.name() == QColor(expected).name(), type(widget).__name__
    finally:
        for widget, _ in unstyled:
            widget.close()
            widget.deleteLater()


@pytest.mark.parametrize("hostile_desktop", ["light", "dark"], indirect=True)
def test_the_menu_bar_and_its_menus_are_painted_in_the_theme_not_the_desktop(
    hostile_desktop: theme.Palette,
) -> None:
    from PySide6.QtCore import QPoint
    from PySide6.QtGui import QAction, QColor
    from PySide6.QtWidgets import QMainWindow

    palette = hostile_desktop
    window = QMainWindow()
    menu = window.menuBar().addMenu("&View")
    first = menu.addAction("System")
    chosen = menu.addAction("Dark")
    assert isinstance(first, QAction) and isinstance(chosen, QAction)
    window.resize(300, 80)
    window.show()
    support.settle()
    try:
        bar = window.grab().toImage()
        assert bar.pixelColor(250, 5).name() == QColor(palette.sidebar).name()
        menu.popup(window.mapToGlobal(QPoint(20, 40)))
        menu.setActiveAction(chosen)
        support.settle()
        popup = menu.grab().toImage()
        row = menu.actionGeometry(chosen).center().y()
        edge = menu.width() - 8
        assert (
            popup.pixelColor(edge, menu.actionGeometry(first).center().y()).name()
            == QColor(palette.surface).name()
        )
        assert popup.pixelColor(edge, row).name() == QColor(palette.accent_fill).name()
    finally:
        menu.hide()
        window.close()
        window.deleteLater()


@pytest.mark.parametrize("palette", [theme.LIGHT, theme.DARK], ids=["light", "dark"])
def test_menu_text_is_readable_in_every_state(palette: theme.Palette) -> None:
    assert theme.contrast_ratio(palette.ink, palette.sidebar) >= 7.0  # the bar
    assert theme.contrast_ratio(palette.ink, palette.surface) >= 7.0  # an item
    assert theme.contrast_ratio(palette.ink, palette.hover) >= 7.0  # the bar's open title
    assert theme.contrast_ratio(palette.on_accent, palette.accent_fill) >= 4.5  # the chosen item
    sheet = theme.stylesheet(palette)
    assert "QMenu::item:selected { background: " + palette.accent_fill in sheet


def test_the_qt_palette_carries_the_theme_for_every_role_the_sheet_leaves_to_it() -> None:
    from PySide6.QtGui import QColor, QPalette

    for palette in (theme.LIGHT, theme.DARK):
        colors = theme.qt_palette(palette)
        role = QPalette.ColorRole
        assert colors.color(role.Window).name() == palette.page
        assert colors.color(role.Base).name() == QColor(palette.input_background).name()
        assert colors.color(role.Text).name() == palette.ink
        assert colors.color(role.Highlight).name() == palette.accent_fill
        assert colors.color(role.HighlightedText).name() == palette.on_accent
        assert colors.color(role.PlaceholderText).name() == palette.ink2
        disabled = colors.color(QPalette.ColorGroup.Disabled, role.Text)
        assert disabled.name() == palette.muted


def test_applying_the_same_theme_again_changes_nothing_so_it_stays_cheap(
    qapp: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Each of these calls re-polishes every live widget: a window's worth is the difference
    between 0.2 s and 2.7 s (see `desktop_ui_support.settle`)."""
    before = theme.current()
    try:
        theme.apply_theme(qapp, "dark")
        sheet, colors = qapp.styleSheet(), qapp.palette()
        changes: list[str] = []

        def refuse(what: str) -> Any:
            def record(*_: Any) -> None:
                changes.append(what)

            return record

        monkeypatch.setattr(qapp, "setStyleSheet", refuse("sheet"))
        monkeypatch.setattr(qapp, "setPalette", refuse("palette"))
        theme.apply_theme(qapp, "dark")
        assert changes == [] and qapp.styleSheet() == sheet and qapp.palette() == colors
        theme.apply_theme(qapp, "light")  # a real change does reach both
        assert sorted(changes) == ["palette", "sheet"]
    finally:
        monkeypatch.undo()
        theme.apply_theme(qapp, before.name)


def test_series_colours_are_taken_in_order_and_wrap_only_by_the_callers_choice() -> None:
    assert [theme.DARK.series_color(i).name() for i in range(3)] == list(theme.DARK.series[:3])
    assert theme.DARK.series_color(8).name() == theme.DARK.series[0]
    assert (
        theme.DARK.tone("bad") == theme.DARK.critical and theme.DARK.tone("zzz") == theme.DARK.muted
    )


# ------------------------------------------------------------------ badges, tiles, legend


@pytest.mark.parametrize("status", sorted(STATUS_TONES))
def test_a_badge_always_carries_a_glyph_and_a_word(qapp: Any, status: str) -> None:
    badge = Badge("the word", status)
    tone, glyph = STATUS_TONES[status]
    assert badge.text() == f"{glyph}  the word", "colour is never the only signal"
    assert badge.property("tone") == tone
    assert status in badge.accessibleName() and "the word" in badge.accessibleName()


def test_a_badge_can_change_status_and_unknown_ones_are_neutral(qapp: Any) -> None:
    badge = Badge("queued", "queued")
    badge.set_status("running", "running")
    assert badge.property("tone") == "accent" and "●" in badge.text()
    badge.set_status("something-new", "odd")
    assert badge.property("tone") == "neutral"


def test_a_metric_tile_wraps_long_identifiers_but_keeps_the_real_value(qapp: Any) -> None:
    tile = MetricTile("Data source", "bls_public_api_and_kaggle_local_snapshot")
    assert tile.value_text == "bls_public_api_and_kaggle_local_snapshot"
    assert "​" in tile._value.text(), "a break point after each underscore"
    assert tile.accessibleName() == "Data source: bls_public_api_and_kaggle_local_snapshot"
    short = MetricTile("N", "42")
    assert short._value.property("role") == "metric"
    assert tile._value.property("role") == "h3"
    short.set_value("43")
    assert short.value_text == "43" and "43" in short.accessibleName()


def test_the_legend_appears_only_for_two_or_more_series_and_wraps(qapp: Any) -> None:
    legend = Legend()
    legend.resize(500, 40)
    legend.show()
    names = [(f"series number {i}", theme.DARK.series_color(i)) for i in range(6)]
    legend.set_entries(names[:1])
    assert legend.isHidden(), "one series is named by the title"
    legend.set_entries(names)
    assert not legend.isHidden() and [n for n, _ in legend.entries] == [n for n, _ in names]
    wide, narrow = legend.heightForWidth(1200), legend.heightForWidth(200)
    assert narrow > wide, "it wraps onto more rows when it has less room"
    assert support.distinct_colors(support.grab_pixels(legend)) > 2
    assert "series number 0" in legend.accessibleName()


# ------------------------------------------------------------------ tables


def table(qapp: Any, rows: list[list[str]], numeric: list[bool] | None = None) -> DataTable:
    widget = DataTable("T")
    widget.set_rows(["Name", "Value"], rows, numeric or [False, True])
    return widget


def test_numbers_sort_as_numbers_and_text_as_text(qapp: Any) -> None:
    widget = table(qapp, [["a", "9"], ["b", "10"], ["c", "100"], ["d", "1,000"]])
    widget.sortByColumn(1, Qt.SortOrder.DescendingOrder)
    assert [widget.cell(r, 1) for r in range(4)] == ["1,000", "100", "10", "9"]
    widget.sortByColumn(0, Qt.SortOrder.AscendingOrder)
    assert [widget.cell(r, 0) for r in range(4)] == ["a", "b", "c", "d"]


def test_a_table_keeps_the_order_it_was_given_until_a_header_is_clicked(qapp: Any) -> None:
    widget = table(qapp, [["z", "1"], ["a", "2"], ["m", "3"]])
    assert [widget.cell(r, 0) for r in range(3)] == ["z", "a", "m"]


def test_numeric_columns_are_right_aligned_and_headers_sit_with_their_data(qapp: Any) -> None:
    widget = table(qapp, [["a", "1"]])
    item_text, item_number = widget.item(0, 0), widget.item(0, 1)
    assert item_text is not None and item_number is not None
    assert item_number.textAlignment() & Qt.AlignmentFlag.AlignRight
    assert item_text.textAlignment() & Qt.AlignmentFlag.AlignLeft
    assert widget.horizontalHeader().defaultAlignment() & Qt.AlignmentFlag.AlignLeft


def test_a_table_exports_exactly_what_it_shows(qapp: Any) -> None:
    widget = table(qapp, [["a", "1,000"], ["b, with comma", '2 "quoted"']])
    assert widget.headers() == ["Name", "Value"]
    assert widget.to_csv().splitlines() == [
        "Name,Value",
        'a,"1,000"',
        '"b, with comma","2 ""quoted"""',
    ]
    assert widget.to_text().splitlines()[0] == "Name\tValue"


def test_ctrl_c_copies_the_selection_as_tab_separated_text(qapp: Any) -> None:
    widget = table(qapp, [["a", "1"], ["b", "2"], ["c", "3"]])
    widget.show()
    widget.setRangeSelected(QTableWidgetSelectionRange(0, 0, 1, 1), True)
    assert widget.to_text(selection_only=True) == "a\t1\nb\t2\n"
    QGuiApplication.clipboard().clear()
    QTest.keyClick(widget, Qt.Key.Key_C, Qt.KeyboardModifier.ControlModifier)
    assert QGuiApplication.clipboard().text() == "a\t1\nb\t2\n"


def test_nothing_selected_copies_nothing(qapp: Any) -> None:
    widget = table(qapp, [["a", "1"]])
    assert widget.to_text(selection_only=True) == ""


def test_a_result_table_remembers_how_many_rows_were_cut(qapp: Any) -> None:
    widget = DataTable("T")
    widget.set_table(Table("t", ("A",), (("1",), ("2",)), (True,), truncated=7))
    assert widget.truncated == 7 and widget.rowCount() == 2
    long = DataTable("L")
    long.set_rows(["A"], [["x" * 80]])
    item = long.item(0, 0)
    assert item is not None and "x" * 80 in item.toolTip(), (
        "a clipped cell keeps its text in a tooltip"
    )


def test_key_value_tables_are_two_columns_and_unsorted(qapp: Any) -> None:
    widget = key_value_table("K", [("b", "2"), ("a", "1")])
    assert widget.headers() == ["Name", "Value"] and widget.cell(0, 0) == "b"


@pytest.mark.parametrize(
    ("text", "number"),
    [
        ("1,000", 1000.0),
        (" 2.5 ", 2.5),
        ("-3", -3.0),
        ("1e3", 1000.0),
        ("abc", None),
        ("—", None),
        ("", None),
    ],
)
def test_numbers_are_recognised_in_displayed_text(text: str, number: float | None) -> None:
    assert parse_number(text) == number


def test_saving_text_writes_where_asked_and_a_cancelled_dialog_writes_nothing(
    qapp: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "out.csv"
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *a, **k: (str(target), ""))
    assert save_text(None, "x.csv", "a,b\n1,2\n", "CSV (*.csv)") == target
    assert target.read_text() == "a,b\n1,2\n"
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *a, **k: ("", ""))
    assert save_text(None, "x.csv", "nope", "CSV (*.csv)") is None


def test_clearing_a_layout_removes_its_widgets_and_nested_layouts(qapp: Any) -> None:
    from PySide6.QtWidgets import QHBoxLayout, QLabel, QVBoxLayout, QWidget

    host = QWidget()
    outer = QVBoxLayout(host)
    outer.addWidget(QLabel("a"))
    inner = QHBoxLayout()
    inner.addWidget(QLabel("b"))
    outer.addLayout(inner)
    clear_layout(outer)
    assert outer.count() == 0


# ------------------------------------------------------------------ the JSON tree


def test_the_json_tree_builds_children_only_when_a_node_is_opened(qapp: Any) -> None:
    tree = JsonTree()
    tree.set_payload({"a": {"b": {"c": 1}}, "list": [10, 20], "n": 5, "empty": {}})
    root = tree.invisibleRootItem()
    assert [root.child(i).text(0) for i in range(root.childCount())] == ["a", "list", "n", "empty"]
    first = root.child(0)
    assert first.text(1) == "{1 keys}" and first.child(0).text(0) == "…", (
        "a placeholder, not the data"
    )
    tree.expandItem(first)
    assert first.child(0).text(0) == "b" and first.childCount() == 1
    assert root.child(2).childCount() == 0 and root.child(3).childCount() == 0
    tree.expandItem(root.child(1))
    assert [root.child(1).child(i).text(1) for i in range(2)] == ["10", "20"]


def test_a_huge_list_shows_a_bounded_number_of_children_and_says_so(qapp: Any) -> None:
    tree = JsonTree()
    tree.set_payload({"big": list(range(1000))})
    big = tree.invisibleRootItem().child(0)
    tree.expandItem(big)
    assert big.childCount() == widgets.MAX_TREE_CHILDREN + 1
    assert "700 more" in big.child(big.childCount() - 1).text(0)


def test_setting_a_new_payload_replaces_the_old(qapp: Any) -> None:
    tree = JsonTree()
    tree.set_payload({"x": 1})
    tree.set_payload([1, 2, 3])
    assert tree.invisibleRootItem().childCount() == 3


# ------------------------------------------------------------------ the chart card


def comparison() -> Comparison:
    return Comparison(
        "Models",
        ("mae", "rmse"),
        (("naive", (0.3, 0.4)), ("gru", (3.5, 4.1)), ("mlp", (1.9, 2.8))),
    )


def test_a_comparison_is_bars_with_a_table_twin_and_a_choice_of_column(qapp: Any) -> None:
    card = ChartCard("Models")
    card.show_comparison(comparison())
    assert card.bar_chart.isHidden() is False and card.line_chart.isHidden() is True
    assert [label for label, _ in card.bar_chart.ranked_rows()] == ["gru", "mlp", "naive"]
    assert card.table.headers() == ["Name", "mae", "rmse"] and card.table.rowCount() == 3
    assert card.choice == "mae"
    card.select("rmse")
    assert [v for _, v in card.bar_chart.ranked_rows()] == [4.1, 2.8, 0.4]
    assert not card.table_shown()
    card.set_table_shown(True)
    assert card.table_shown() and "chart" in card._toggle.accessibleName().lower()
    card.set_table_shown(False)
    assert not card.table_shown()


def selectable_chart() -> Chart:
    xs = tuple(float(i) for i in range(10))
    lines = (
        Line("Price", tuple(i * 2.0 for i in range(10)), xs, series="Price"),
        Line("Cash", tuple(50.0 - i for i in range(10)), xs, series="Cash"),
    )
    return Chart("Steps", "Step", lines, selectable=True, original_points=10)


def test_a_chart_card_offers_the_series_and_lists_exactly_the_points_drawn(qapp: Any) -> None:
    card = ChartCard("Steps")
    card.show_chart(selectable_chart())
    assert card.line_chart.isHidden() is False
    assert [card._select.itemText(i) for i in range(card._select.count())] == ["Price", "Cash"]
    assert card.table.headers() == ["Step", "Price"] and card.table.rowCount() == 10
    assert [card.table.cell(r, 1) for r in range(3)] == ["0", "2", "4"]
    card.select("Cash")
    assert [line.name for line in card.line_chart.lines] == ["Cash"]
    assert card.table.headers() == ["Step", "Cash"] and card.table.cell(0, 1) == "50"


def test_the_legend_shows_for_several_series_and_hides_for_one(qapp: Any) -> None:
    card = ChartCard("Two")
    xs = (0.0, 1.0, 2.0)
    card.show_chart(
        Chart("Two", "x", (Line("a", (1.0, 2.0, 3.0), xs), Line("b", (3.0, 2.0, 1.0), xs)))
    )
    assert [n for n, _ in card.legend.entries] == ["a", "b"] and not card.legend.isHidden()
    card.show_chart(Chart("One", "x", (Line("a", (1.0, 2.0, 3.0), xs),)))
    assert card.legend.isHidden()


def test_a_thinned_chart_says_how_much_was_left_out(qapp: Any) -> None:
    card = ChartCard("Big")
    xs = tuple(float(i) for i in range(10))
    card.show_chart(Chart("Big", "x", (Line("a", tuple(range(10)), xs),), original_points=5000))
    assert not card._caption.isHidden()
    assert (
        "10 of 5,000" in card._caption.text()
        and "table lists exactly those" in card._caption.text()
    )


def test_series_beyond_eight_are_reported_in_the_caption(qapp: Any) -> None:
    card = ChartCard("Many")
    xs = (0.0, 1.0, 2.0)
    lines = tuple(Line(f"s{i}", (float(i), 1.0, 2.0), xs) for i in range(10))
    card.show_chart(Chart("Many", "x", lines))
    assert "2 more are left out" in card._caption.text()


def test_a_chart_card_follows_a_theme_change(qapp: Any) -> None:
    card = ChartCard("Steps")
    card.show_chart(selectable_chart())
    before = [c.name() for _, c in card.legend.entries]
    theme.apply_theme(qapp, "light")
    try:
        card.retheme()
        after = [c.name() for _, c in card.line_chart.legend_entries()]
        assert after[0] == theme.LIGHT.series[0].lower() or len(after) == 1
        assert before != after or before == []
    finally:
        theme.apply_theme(qapp, "dark")


# ------------------------------------------------------------------ the result viewer


def result_view(**extra: Any) -> Any:
    payload = {
        "verdict": "classical_better",
        "n": 5,
        "models": {"a": {"mae": 1.0, "rmse": 2.0}, "b": {"mae": 3.0, "rmse": 4.0}},
        "curve": [3.0, 2.0, 1.0, 0.5],
        "steps": [{"step": i, "v": float(i)} for i in range(6)],
        "limitations": ["synthetic data", "one asset"],
        "config": {"seed": 1},
        **extra,
    }
    return analyze_payload(
        payload,
        kind="x",
        title="Example",
        provenance=[("Result hash", "ab" * 32), ("Job", "j-1")],
        disclaimer="SIMULATED DATA -- RESEARCH ONLY.",
    )


def test_the_result_has_the_tabs_its_content_calls_for(qapp: Any) -> None:
    widget = ResultWidget()
    widget.set_view(result_view())
    assert widget.tab_titles() == ["Overview", "Charts", "Tables", "Details · 2 limitations", "Raw"]
    assert widget.verdict.text().endswith("classical better") and not widget.verdict.isHidden()
    assert widget.tabs.currentIndex() == 0, "a verdict and a comparison: open on the overview"
    assert not widget._disclaimer.isHidden() and widget._disclaimer.text().startswith("SIMULATED")


def test_empty_tabs_are_hidden_not_shown_empty(qapp: Any) -> None:
    widget = ResultWidget()
    widget.set_view(analyze_payload({"verdict": "x"}, kind="x", title="Bare"))
    assert widget.tab_titles() == ["Overview", "Details", "Raw"]
    assert widget._disclaimer.isHidden()


def test_a_picture_first_result_opens_on_its_charts(qapp: Any) -> None:
    widget = ResultWidget()
    widget.set_view(analyze_payload({"curve": [1.0, 2.0, 3.0, 4.0]}, kind="x", title="Curve"))
    assert widget.tabs.currentIndex() == 1


def test_a_run_that_calls_itself_invalid_says_so_with_its_reasons(qapp: Any) -> None:
    widget = ResultWidget()
    widget.set_view(
        analyze_payload({"invalid_reasons": ["negative cash"], "n": 1}, kind="x", title="Bad")
    )
    assert not widget.invalid_card.isHidden()
    assert "negative cash" in widget._invalid_text.text()
    widget.set_view(result_view())
    assert widget.invalid_card.isHidden()


def test_every_chart_in_a_result_has_a_table_behind_it(qapp: Any) -> None:
    widget = ResultWidget()
    widget.set_view(result_view())
    assert widget.chart_cards, "the overview and the charts tab"
    for card in widget.chart_cards:
        assert card.table.rowCount() > 0
    assert len(widget.tiles) >= 2 and len(widget.tables) == 1


def test_the_result_hash_can_be_copied(qapp: Any) -> None:
    widget = ResultWidget()
    widget.set_view(result_view())
    QGuiApplication.clipboard().clear()
    widget.copy_button.click()
    assert QGuiApplication.clipboard().text() == "ab" * 32
    widget.set_view(analyze_payload({"n": 1}, kind="x", title="No provenance"))
    assert widget.copy_button.isHidden(), "a button for a hash that does not exist would mislead"


def test_actions_follow_what_the_page_offers(qapp: Any) -> None:
    widget = ResultWidget()
    widget.set_view(result_view())
    widget.set_actions(rerun=True, export=True)
    assert not widget.rerun_button.isHidden() and not widget.export_button.isHidden()
    widget.set_actions(rerun=False, export=False)
    assert widget.rerun_button.isHidden() and widget.export_button.isHidden()
    heard: list[str] = []
    widget.exportRequested.connect(lambda: heard.append("export"))
    widget.rerunRequested.connect(lambda: heard.append("rerun"))
    widget.export_button.click()
    widget.rerun_button.click()
    assert heard == ["export", "rerun"]


def test_clearing_a_result_empties_it(qapp: Any) -> None:
    widget = ResultWidget()
    widget.set_view(result_view())
    widget.clear()
    assert widget.view is None and widget.tabs.count() == 0 and widget.chart_cards == []


def test_each_table_has_its_own_export_button_that_saves_that_table(
    qapp: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from PySide6.QtWidgets import QPushButton

    widget = ResultWidget()
    widget.set_view(result_view(trades=[{"asset": "A", "qty": 2.0}, {"asset": "B", "qty": 3.0}]))
    buttons = [
        b for b in widget.tabs.widget(2).findChildren(QPushButton) if b.text() == "Export CSV…"
    ]
    assert len(buttons) == 2 == len(widget.tables)
    saved: list[str] = []

    def choose(*args: Any, **kwargs: Any) -> tuple[str, str]:
        target = tmp_path / f"table-{len(saved)}.csv"
        saved.append(str(target))
        return str(target), ""

    monkeypatch.setattr(QFileDialog, "getSaveFileName", choose)
    for button in buttons:
        button.click()
    first, second = (Path(path).read_text().splitlines() for path in saved)
    assert first[0] == "Step,V" and second[0] == "Asset,Qty", "each button saves its own table"
    assert second[1:] == ["A,2", "B,3"]


def test_a_stale_export_request_saves_nothing(
    qapp: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Called with no sender, or after the result was cleared, there is nothing to save."""
    widget = ResultWidget()
    widget.set_view(result_view())
    asked: list[str] = []
    monkeypatch.setattr(
        QFileDialog, "getSaveFileName", lambda *a, **k: asked.append("x") or ("", "")
    )
    widget._export_table()  # no sender
    widget.clear()
    widget._export_table()
    assert asked == []


# ------------------------------------------------------------------ data is shown as data

HOSTILE = "<b>bold</b><img src='file:///etc/passwd'><a href='http://example.invalid/x'>click</a>"


def test_text_from_a_result_is_shown_as_typed_never_interpreted_as_markup(qapp: Any) -> None:
    label = widgets.make_label(HOSTILE)
    assert label.textFormat() == Qt.TextFormat.PlainText and label.text() == HOSTILE
    assert widgets.Badge(HOSTILE, "ok").textFormat() == Qt.TextFormat.PlainText
    tile = MetricTile(HOSTILE, HOSTILE)
    assert tile._label.textFormat() == Qt.TextFormat.PlainText
    assert tile._value.textFormat() == Qt.TextFormat.PlainText
    assert tile.value_text == HOSTILE


def test_a_label_that_looks_like_html_really_is_drawn_as_text(qapp: Any) -> None:
    from PySide6.QtWidgets import QLabel

    plain = widgets.make_label(HOSTILE, wrap=False)
    auto = QLabel(HOSTILE)  # Qt's default would parse it, shrinking it to the words "boldclick"
    assert plain.sizeHint().width() > 3 * auto.sizeHint().width()


def test_tooltips_that_carry_data_are_escaped(qapp: Any) -> None:
    shown = widgets.plain_tooltip(HOSTILE)
    assert "<img" not in shown and "<b>" not in shown and "&lt;img" in shown
    assert widgets.plain_tooltip("a & b") == "<p style='white-space:pre-wrap'>a &amp; b</p>"
    table = DataTable("T")
    table.set_rows(["A"], [[HOSTILE + " " + "pad" * 20]])
    item = table.item(0, 0)
    assert item is not None and "<img" not in item.toolTip() and "&lt;img" in item.toolTip()


def test_a_cell_of_a_result_table_is_text_and_so_is_a_tree_node(qapp: Any) -> None:
    table = DataTable("T")
    table.set_rows(["A"], [[HOSTILE]])
    assert table.cell(0, 0) == HOSTILE
    tree = JsonTree()
    tree.set_payload({HOSTILE: HOSTILE})
    node = tree.invisibleRootItem().child(0)
    assert node.text(0) == HOSTILE and node.text(1) == HOSTILE
