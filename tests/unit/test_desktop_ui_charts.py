# ruff: noqa: E402
"""PR-205: the charts. The number formatting and the geometry are plain functions, tested with
properties; the widgets are tested for what they *say* (legend, readout, labels, what is drawn and
what is left out) and for how they respond to the pointer and the keyboard, plus that something
real and theme-dependent is painted. Exact pixels are deliberately not asserted."""

from __future__ import annotations

import math
from typing import Any

import pytest
from hypothesis import assume, given, settings
from hypothesis import strategies as st

from tests.unit import desktop_ui_support as support

support.require_qt()

from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest

from prometheus.desktop.results import Chart, Line
from prometheus.desktop.ui import theme
from prometheus.desktop.ui.charts import (
    BAR_MAX_THICKNESS,
    MAX_SERIES,
    BarChart,
    LineChart,
    bar_layout,
    format_ticks,
    nice_step,
    nice_ticks,
    ticks_within,
)

# ------------------------------------------------------------------ round tick values


@pytest.mark.parametrize(
    ("raw", "step"),
    [
        (0.8, 1.0),
        (1.0, 1.0),
        (1.5, 2.0),
        (3.0, 5.0),
        (7.0, 10.0),
        (0.03, 0.05),
        (120.0, 200.0),
        (0.0, 1.0),
        (-3.0, 1.0),
        (math.nan, 1.0),
        (math.inf, 1.0),
    ],
)
def test_a_step_is_one_two_or_five_times_a_power_of_ten(raw: float, step: float) -> None:
    assert nice_step(raw) == pytest.approx(step)


@settings(max_examples=300, deadline=None)
@given(
    low=st.floats(min_value=-1e9, max_value=1e9),
    span=st.floats(min_value=1e-6, max_value=1e9),
    target=st.integers(min_value=2, max_value=10),
)
def test_ticks_are_round_ordered_evenly_spaced_and_cover_the_range(
    low: float, span: float, target: int
) -> None:
    # below a relative span of 1e-6 a double cannot hold distinct, evenly spaced round values at
    # all (a range of 0.06 at 134 million): that is the float's limit, not the chart's
    assume(span >= 1e-6 * abs(low))
    high = low + span
    ticks = nice_ticks(low, high, target)
    scale = max(abs(low), abs(high), span)
    assert len(ticks) >= 2
    assert all(b > a for a, b in zip(ticks, ticks[1:], strict=False))
    assert ticks[0] <= low + 1e-9 * scale and ticks[-1] >= high - 1e-9 * scale
    steps = [b - a for a, b in zip(ticks, ticks[1:], strict=False)]
    assert max(steps) - min(steps) <= 1e-6 * max(steps)
    mantissa = steps[0] / 10 ** math.floor(math.log10(steps[0]))
    assert min(abs(mantissa - m) for m in (1.0, 2.0, 5.0, 10.0)) < 1e-6
    assert len(ticks) <= 3 * target + 3


def test_degenerate_ranges_still_give_usable_ticks() -> None:
    assert len(nice_ticks(5.0, 5.0)) >= 2
    assert nice_ticks(0.0, 0.0)[0] < 0.0 < nice_ticks(0.0, 0.0)[-1]
    assert nice_ticks(10.0, 0.0) == nice_ticks(0.0, 10.0)
    assert nice_ticks(math.nan, 1.0) == [0.0, 1.0]
    assert 0.0 in nice_ticks(-3.0, 8.0), "a range that crosses zero has a tick exactly on it"
    assert nice_ticks(0.0, 0.3) == pytest.approx(
        [0.0, 0.1, 0.2, 0.3, 0.4][: len(nice_ticks(0.0, 0.3))]
    )


@settings(max_examples=200, deadline=None)
@given(low=st.floats(min_value=-1e6, max_value=1e6), span=st.floats(min_value=1e-3, max_value=1e6))
def test_axis_ticks_for_the_datas_own_range_stay_inside_it(low: float, span: float) -> None:
    high = low + span
    ticks = ticks_within(low, high)
    assert len(ticks) >= 2
    assert all(low - 1e-9 * span <= t <= high + 1e-9 * span for t in ticks)


@pytest.mark.parametrize(
    ("ticks", "labels"),
    [
        ([0, 1000, 2000], ["0", "1,000", "2,000"]),
        ([0, 10_000, 20_000], ["0", "10K", "20K"]),
        ([0, 2_500_000, 5_000_000], ["0", "2.5M", "5.0M"]),
        ([0, 0.5, 1.0], ["0.0", "0.5", "1.0"]),
        ([0, 0.25, 0.5], ["0.00", "0.25", "0.50"]),
        ([-10, 0, 10], ["-10", "0", "10"]),
        ([0, 1e-5, 2e-5], ["0.0e+00", "1.0e-05", "2.0e-05"]),
        ([0, 3e9, 6e9], ["0", "3B", "6B"]),
        ([], []),
    ],
)
def test_one_axis_is_labelled_in_one_style(ticks: list[float], labels: list[str]) -> None:
    assert format_ticks(ticks) == labels


# ------------------------------------------------------------------ the bar geometry


def test_bars_are_ranked_largest_first_from_one_baseline_and_never_thicker_than_24px() -> None:
    rows = [("a", 1.0), ("b", 4.0), ("c", None), ("d", 2.5)]
    laid = bar_layout(rows, width=600, label_width=100, value_width=60)
    assert [r.label for r in laid] == ["b", "d", "a", "c"], "ranked; the missing value last"
    drawn = [r for r in laid if r.rect is not None]
    assert len({round(r.rect.left(), 6) for r in drawn if r.rect}) == 1, "one shared baseline"
    assert all(r.rect.height() <= BAR_MAX_THICKNESS for r in drawn if r.rect)
    widths = [r.rect.width() for r in drawn if r.rect]
    assert widths == sorted(widths, reverse=True)
    assert laid[-1].rect is None, "no value: a label and a dash, never a zero-length bar"
    assert all(r.rect.right() <= 600 - 60 for r in drawn if r.rect), "room for the value at the tip"


def test_a_negative_value_extends_to_the_left_of_the_baseline() -> None:
    laid = {
        r.label: r
        for r in bar_layout(
            [("up", 3.0), ("down", -2.0)], width=600, label_width=80, value_width=50
        )
    }
    up, down = laid["up"].rect, laid["down"].rect
    assert up is not None and down is not None
    assert down.right() == pytest.approx(up.left()), "both meet at the zero baseline"
    assert down.left() < up.left()


@pytest.mark.parametrize("values", [[0.0, 0.0], [5.0, 5.0], [-1.0, -1.0]])
def test_equal_or_zero_values_still_produce_visible_bars(values: list[float]) -> None:
    laid = bar_layout(
        [(f"r{i}", v) for i, v in enumerate(values)], width=500, label_width=60, value_width=40
    )
    assert all(r.rect is not None and r.rect.width() >= 1.0 for r in laid)


def test_no_rows_is_an_empty_layout() -> None:
    assert bar_layout([], width=400, label_width=50, value_width=40) == []


# ------------------------------------------------------------------ the line chart


def chart(*lines: Line, **extra: Any) -> Chart:
    return Chart("A chart", "Step", tuple(lines), **extra)


def ramp(name: str, scale: float, n: int = 20, *, series: str = "") -> Line:
    return Line(
        name,
        tuple(scale * i for i in range(n)),
        tuple(float(i) for i in range(n)),
        series=series,
    )


@pytest.fixture
def line_chart(qapp: Any, theme_dark: Any) -> LineChart:
    widget = LineChart()
    widget.resize(640, 320)
    widget.show()
    support.settle()
    return widget


def test_distinct_series_take_the_palette_in_its_fixed_order(line_chart: LineChart) -> None:
    line_chart.set_chart(chart(ramp("first", 1.0), ramp("second", 2.0), ramp("third", 3.0)))
    palette = theme.current()
    entries = line_chart.legend_entries()
    assert [name for name, _ in entries] == ["first", "second", "third"]
    assert [color.name().lower() for _, color in entries] == [c.lower() for c in palette.series[:3]]


def test_a_single_series_is_the_first_hue(line_chart: LineChart) -> None:
    line_chart.set_chart(chart(ramp("only", 1.0)))
    assert line_chart.legend_entries()[0][1].name().lower() == theme.current().series[0].lower()


def test_a_series_keeps_its_colour_when_the_other_column_is_chosen(line_chart: LineChart) -> None:
    lines = (
        ramp("Seed 0", 1.0, series="Reward"),
        ramp("Seed 1", 2.0, series="Reward"),
        ramp("Seed 0", 5.0, series="Loss"),
        ramp("Seed 1", 6.0, series="Loss"),
    )
    selectable = chart(*lines, selectable=True)
    line_chart.set_chart(selectable, "Reward")
    first = dict((n, c.name()) for n, c in line_chart.legend_entries())
    line_chart.set_chart(selectable, "Loss")
    second = dict((n, c.name()) for n, c in line_chart.legend_entries())
    assert first == second and first["Seed 0"] != first["Seed 1"], "colour follows the entity"


def test_an_uncertainty_band_is_one_hue_and_needs_no_legend(line_chart: LineChart) -> None:
    low = Line("5th percentile", (1.0, 1.0, 1.0), (0.0, 1.0, 2.0))
    mid = Line("Median", (2.0, 2.0, 2.0), (0.0, 1.0, 2.0))
    high = Line("95th percentile", (3.0, 3.5, 4.0), (0.0, 1.0, 2.0))
    line_chart.set_chart(chart(low, mid, high, band=("5th percentile", "95th percentile")))
    assert line_chart.legend_entries() == []
    assert line_chart.direct_labels_shown() == ["95th percentile", "Median", "5th percentile"]
    readout = line_chart.readout(1)
    assert {row.color.name() for row in readout.rows} == {theme.current().series[0].lower()}


def test_the_readout_lists_every_series_at_the_position(line_chart: LineChart) -> None:
    line_chart.set_chart(chart(ramp("slow", 1.0), ramp("fast", 10.0)))
    readout = line_chart.readout(3)
    assert (readout.x_label, readout.x_value) == ("Step", "3")
    assert [(r.name, r.value) for r in readout.rows] == [("slow", "3"), ("fast", "30")]


def test_the_cursor_is_clamped_to_the_data(line_chart: LineChart) -> None:
    line_chart.set_chart(chart(ramp("a", 1.0, n=10)))
    line_chart.set_cursor(-5)
    assert line_chart.cursor_index == 0
    line_chart.set_cursor(500)
    assert line_chart.cursor_index == 9
    line_chart.set_cursor(None)
    assert line_chart.cursor_index is None


def test_a_pixel_maps_to_the_nearest_data_position(line_chart: LineChart) -> None:
    line_chart.set_chart(chart(ramp("a", 1.0, n=11)))
    geometry = line_chart._geometry
    assert geometry is not None
    left, right = geometry.plot.left(), geometry.plot.right()
    assert line_chart.index_for_pixel(left - 20) == 0
    assert line_chart.index_for_pixel(right + 20) == 10
    assert line_chart.index_for_pixel((left + right) / 2) == 5
    quarter = left + (right - left) * 0.26
    assert line_chart.index_for_pixel(quarter) in (2, 3)


def test_the_pointer_moves_the_crosshair(line_chart: LineChart) -> None:
    line_chart.set_chart(chart(ramp("a", 1.0, n=11)))
    geometry = line_chart._geometry
    assert geometry is not None
    middle = int((geometry.plot.left() + geometry.plot.right()) / 2)
    QTest.mouseMove(line_chart, QPoint(middle, int(geometry.plot.center().y())))
    support.settle()
    assert line_chart.cursor_index == 5


def test_the_arrow_keys_do_what_the_pointer_does(line_chart: LineChart) -> None:
    line_chart.set_chart(chart(ramp("a", 1.0, n=30)))
    support.focus(line_chart)
    assert line_chart.cursor_index == 29, "focusing starts at the newest point"
    QTest.keyClick(line_chart, Qt.Key.Key_Left)
    assert line_chart.cursor_index == 28
    QTest.keyClick(line_chart, Qt.Key.Key_Left, Qt.KeyboardModifier.ShiftModifier)
    assert line_chart.cursor_index == 18
    QTest.keyClick(line_chart, Qt.Key.Key_Home)
    assert line_chart.cursor_index == 0
    QTest.keyClick(line_chart, Qt.Key.Key_Right)
    assert line_chart.cursor_index == 1
    QTest.keyClick(line_chart, Qt.Key.Key_End)
    assert line_chart.cursor_index == 29
    QTest.keyClick(line_chart, Qt.Key.Key_Escape)
    assert line_chart.cursor_index is None
    assert line_chart.readout(0).rows, "the keyboard shows the same readout as the pointer"


def test_end_labels_that_would_collide_are_not_drawn(line_chart: LineChart) -> None:
    line_chart.set_chart(chart(ramp("close", 1.0), ramp("also close", 1.001)))
    assert line_chart.direct_labels_shown() == [], "the legend and the tooltip carry the names"
    line_chart.set_chart(chart(ramp("low", 1.0), ramp("high", 30.0)))
    assert line_chart.direct_labels_shown() == ["high", "low"]
    line_chart.set_chart(chart(ramp("only", 1.0)))
    assert line_chart.direct_labels_shown() == [], "one series is named by the title"


def test_more_than_four_series_get_no_end_labels(line_chart: LineChart) -> None:
    line_chart.set_chart(chart(*[ramp(f"s{i}", 10.0 * i + 1) for i in range(5)]))
    assert line_chart.direct_labels_shown() == []


def test_a_ninth_series_is_left_out_not_given_a_generated_colour(line_chart: LineChart) -> None:
    line_chart.set_chart(chart(*[ramp(f"s{i}", float(i + 1)) for i in range(11)]))
    assert len(line_chart.lines) == MAX_SERIES and line_chart.skipped_series == 3
    colors = [c.name() for _, c in line_chart.legend_entries()]
    assert len(set(colors)) == MAX_SERIES, "eight distinct hues, none cycled"


def test_the_description_names_what_is_plotted_and_where_the_numbers_are(
    line_chart: LineChart,
) -> None:
    line_chart.set_chart(chart(ramp("alpha", 1.0), ramp("beta", 2.0)))
    text = line_chart.accessibleDescription()
    assert "2 series" in text and "alpha" in text and "beta" in text and "table view" in text
    assert line_chart.accessibleName() == "A chart"


def test_an_empty_chart_says_so_instead_of_drawing_nothing(line_chart: LineChart) -> None:
    line_chart.set_chart(chart())
    assert line_chart.description() == "Empty chart"
    assert support.distinct_colors(support.grab_pixels(line_chart)) >= 2


def test_something_real_is_painted_and_it_follows_the_theme(
    qapp: Any, line_chart: LineChart
) -> None:
    line_chart.set_chart(chart(ramp("a", 1.0), ramp("b", 4.0)))
    dark = support.grab_pixels(line_chart)
    assert support.distinct_colors(dark) > 6
    theme.apply_theme(qapp, "light")
    try:
        line_chart.set_chart(chart(ramp("a", 1.0), ramp("b", 4.0)))
        light = support.grab_pixels(line_chart)
        assert light != dark
        assert theme.current().name == "light"
        assert {c.name().lower() for _, c in line_chart.legend_entries()} == {
            theme.LIGHT.series[0].lower(),
            theme.LIGHT.series[1].lower(),
        }
    finally:
        theme.apply_theme(qapp, "dark")


def test_the_crosshair_and_tooltip_change_what_is_painted(line_chart: LineChart) -> None:
    line_chart.set_chart(chart(ramp("a", 1.0), ramp("b", 4.0)))
    plain = support.grab_pixels(line_chart)
    line_chart.set_cursor(10)
    assert support.grab_pixels(line_chart) != plain


def test_a_long_series_draws_without_trouble(line_chart: LineChart) -> None:
    n = 2001
    big = [
        Line(
            f"s{i}",
            tuple(math.sin(j / 50 + i) for j in range(n)),
            tuple(float(j) for j in range(n)),
        )
        for i in range(8)
    ]
    line_chart.set_chart(chart(*big))
    line_chart.set_cursor(1000)
    assert support.distinct_colors(support.grab_pixels(line_chart)) > 10


def test_a_chart_with_a_negative_range_and_a_flat_line_is_drawn(line_chart: LineChart) -> None:
    flat = Line("flat", (-2.0,) * 5, tuple(float(i) for i in range(5)))
    line_chart.set_chart(chart(flat))
    assert line_chart.readout(2).rows[0].value == "-2"
    assert support.distinct_colors(support.grab_pixels(line_chart)) > 3


# ------------------------------------------------------------------ the bar chart


@pytest.fixture
def bar_chart(qapp: Any, theme_dark: Any) -> BarChart:
    widget = BarChart()
    widget.resize(560, 200)
    widget.show()
    support.settle()
    return widget


def test_the_bar_chart_ranks_its_rows_and_describes_itself(bar_chart: BarChart) -> None:
    bar_chart.set_data("Models", [("gru", 3.5), ("naive", 0.31), ("mlp", 1.9)], "MAE")
    assert [label for label, _ in bar_chart.ranked_rows()] == ["gru", "mlp", "naive"]
    text = bar_chart.accessibleDescription()
    assert "MAE" in text and "gru 3.5" in text and "naive 0.31" in text and "largest first" in text
    assert bar_chart.height() >= 3 * 30


def test_hover_lifts_a_bar_and_the_keyboard_walks_the_rows(bar_chart: BarChart) -> None:
    bar_chart.set_data("Models", [("a", 3.0), ("b", 2.0), ("c", 1.0)], "MAE")
    plain = support.grab_pixels(bar_chart)
    bar_chart.set_hover(1)
    assert bar_chart.hovered == 1 and support.grab_pixels(bar_chart) != plain
    bar_chart.set_hover(None)
    support.focus(bar_chart)
    assert bar_chart.hovered == 0
    QTest.keyClick(bar_chart, Qt.Key.Key_Down)
    QTest.keyClick(bar_chart, Qt.Key.Key_Down)
    assert bar_chart.hovered == 2
    QTest.keyClick(bar_chart, Qt.Key.Key_Down)
    assert bar_chart.hovered == 2, "clamped at the last row"
    QTest.keyClick(bar_chart, Qt.Key.Key_Home)
    assert bar_chart.hovered == 0
    QTest.keyClick(bar_chart, Qt.Key.Key_End)
    assert bar_chart.hovered == 2
    QTest.keyClick(bar_chart, Qt.Key.Key_Up)
    assert bar_chart.hovered == 1
    QTest.keyClick(bar_chart, Qt.Key.Key_Escape)
    assert bar_chart.hovered is None


def test_the_pointer_finds_the_row_under_it(bar_chart: BarChart) -> None:
    bar_chart.set_data("Models", [("a", 3.0), ("b", 2.0), ("c", 1.0)], "MAE")
    support.settle()  # the native window takes its new fixed height before the pointer is placed
    QTest.mouseMove(bar_chart, QPoint(300, 6 + 34 + 10))
    support.settle()
    assert bar_chart.hovered == 1
    assert bar_chart.row_at(QPoint(300, 5000).toPointF()) is None


def test_a_row_without_a_value_is_listed_without_a_bar(bar_chart: BarChart) -> None:
    bar_chart.set_data("Models", [("a", 3.0), ("none", None)], "MAE")
    assert bar_chart.bars[-1].rect is None and bar_chart.bars[-1].label == "none"
    assert support.distinct_colors(support.grab_pixels(bar_chart)) > 3
    assert "none" not in bar_chart.accessibleDescription().split("largest first:")[1]


def test_the_bar_chart_follows_the_theme(qapp: Any, bar_chart: BarChart) -> None:
    bar_chart.set_data("Models", [("a", 3.0), ("b", 2.0)], "MAE")
    dark = support.grab_pixels(bar_chart)
    theme.apply_theme(qapp, "light")
    try:
        assert support.grab_pixels(bar_chart) != dark
    finally:
        theme.apply_theme(qapp, "dark")
