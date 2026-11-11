from __future__ import annotations

import re

import pytest

from prometheus.dashboard.charts import bar_chart, calibration_indicator, line_chart


def test_bar_chart_rejects_empty_items() -> None:
    with pytest.raises(ValueError, match="empty"):
        bar_chart([])


def test_bar_chart_rejects_negative_values() -> None:
    with pytest.raises(ValueError, match="non-negative"):
        bar_chart([("a", -1.0)])


def test_bar_chart_the_largest_value_fills_the_full_chart_width() -> None:
    html = bar_chart([("alpha", 2.0), ("beta", 4.0)])
    widths = [float(w) for w in re.findall(r'<rect[^>]*width="([\d.]+)"', html)]
    assert max(widths) == pytest.approx(360.0)
    assert widths[0] == pytest.approx(180.0)  # alpha is half of beta's value


def test_bar_chart_embeds_each_real_value_as_a_data_attribute() -> None:
    html = bar_chart([("alpha", 1.5)])
    assert 'data-value="1.500000"' in html


def test_bar_chart_escapes_a_hostile_label() -> None:
    html = bar_chart([("<script>alert(1)</script>", 1.0)])
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;" in html


def test_bar_chart_stagggers_animation_delay_per_bar() -> None:
    html = bar_chart([("a", 1.0), ("b", 1.0), ("c", 1.0)])
    delays = re.findall(r"animation-delay:([\d.]+)s", html)
    assert delays == ["0.00", "0.08", "0.16"]


def test_line_chart_rejects_empty_x_labels() -> None:
    with pytest.raises(ValueError, match="x_labels"):
        line_chart([], {"a": []})


def test_line_chart_rejects_empty_series() -> None:
    with pytest.raises(ValueError, match="series"):
        line_chart(["1", "2"], {})


def test_line_chart_rejects_a_series_with_mismatched_length() -> None:
    with pytest.raises(ValueError, match="length"):
        line_chart(["1", "2", "3"], {"a": [1.0, 2.0]})


def test_line_chart_draws_one_polyline_per_series() -> None:
    html = line_chart(["1", "2", "3"], {"a": [1.0, 2.0, 3.0], "b": [3.0, 2.0, 1.0]})
    assert html.count("<polyline") == 2
    assert 'data-series="a"' in html
    assert 'data-series="b"' in html


def test_line_chart_sets_a_real_nonzero_stroke_dash_length_for_a_varying_series() -> None:
    html = line_chart(["1", "2", "3"], {"a": [1.0, 5.0, 1.0]})
    lengths = [float(m) for m in re.findall(r"stroke-dasharray:([\d.]+)", html)]
    assert lengths[0] > 0.0


def test_line_chart_includes_a_legend_entry_per_series_with_the_unit() -> None:
    html = line_chart(["1", "2"], {"actual": [1.0, 2.0]}, unit="%")
    assert "actual" in html
    assert "(%)" in html


def test_calibration_indicator_marks_a_pass_with_the_pass_class() -> None:
    html = calibration_indicator(passed=True, label="coverage", detail="looks fine")
    assert "indicator-pass" in html
    assert "PASSES" in html
    assert 'data-passed="true"' in html


def test_calibration_indicator_marks_a_failure_with_the_fail_class() -> None:
    html = calibration_indicator(passed=False, label="coverage", detail="badly miscalibrated")
    assert "indicator-fail" in html
    assert "FAILS" in html
    assert 'data-passed="false"' in html


def test_calibration_indicator_escapes_hostile_detail_text() -> None:
    html = calibration_indicator(passed=True, label="x", detail="<img src=x onerror=alert(1)>")
    assert "<img" not in html
