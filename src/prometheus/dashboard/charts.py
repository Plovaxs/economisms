"""Dependency-free inline-SVG chart primitives, with real CSS (not JS)
animation on load -- the SAME "zero JS/HTML build tooling" discipline
`html.py`'s own docstring states: an SVG `<rect>`/`<polyline>` and a
CSS `@keyframes` rule need no framework, no build step, and no new
dependency, so this is the first dashboard module to add genuine
visual motion without breaking that discipline.

Every coordinate here is computed server-side from real caller-
supplied numbers (never a placeholder), so a test can assert on exact
emitted SVG attributes the same way `test_dashboard_*` already asserts
on exact table cells -- there is no client-side state this project
cannot see from source.
"""

from __future__ import annotations

import math
from collections.abc import Sequence

from prometheus.dashboard.html import escape

_PALETTE: tuple[str, ...] = (
    "#8ea0ff", "#4fbf84", "#e0ab4a", "#e06a8a", "#4ac8e0", "#c48ae0",
)


def _scale(value: float, vmin: float, vmax: float, out_min: float, out_max: float) -> float:
    if vmax <= vmin:
        return (out_min + out_max) / 2
    fraction = (value - vmin) / (vmax - vmin)
    return out_min + fraction * (out_max - out_min)


def bar_chart(items: Sequence[tuple[str, float]], *, unit: str = "") -> str:
    """A horizontal bar per (label, value); every bar's final width IS
    `value` (asserted directly by tests, not just "roughly proportional
    to"), animated growing in from zero via a CSS `scaleX` keyframe,
    staggered per bar so the real ranking reads as motion, not a static
    table restated as rectangles."""
    if not items:
        raise ValueError("items must not be empty")
    if any(v < 0 for _, v in items):
        raise ValueError("bar_chart assumes non-negative values (e.g. MAE/RMSE)")
    max_value = max(v for _, v in items) or 1.0
    row_height, bar_height, label_width, chart_width = 32, 16, 180, 360
    width = label_width + chart_width + 70
    height = row_height * len(items) + 10
    bars = []
    for i, (label, value) in enumerate(items):
        y = 10 + i * row_height
        bar_width = _scale(value, 0.0, max_value, 0.0, chart_width)
        color = _PALETTE[i % len(_PALETTE)]
        bars.append(
            f'<text x="{label_width - 8}" y="{y + bar_height - 3}" text-anchor="end" '
            f'fill="#e8e6e0" font-size="13">{escape(label)}</text>'
            f'<rect class="chart-bar-fill" x="{label_width}" y="{y}" '
            f'width="{bar_width:.3f}" height="{bar_height}" fill="{color}" rx="3" '
            f'style="animation-delay:{i * 0.08:.2f}s" '
            f'data-value="{value:.6f}"></rect>'
            f'<text x="{label_width + chart_width + 8}" y="{y + bar_height - 3}" '
            f'fill="#e8e6e0" font-size="13">{value:.3f}{escape(unit)}</text>'
        )
    return (
        f'<svg class="chart" viewBox="0 0 {width} {height}" width="{width}" height="{height}" '
        f'role="img" aria-label="bar chart">{"".join(bars)}</svg>'
    )


def line_chart(
    x_labels: Sequence[str], series: dict[str, Sequence[float]], *, unit: str = ""
) -> str:
    """One animated polyline per named series, sharing a single y-scale
    computed from the real min/max across every series (never per-line
    rescaled, so two lines are honestly comparable on sight). Each
    line's own real pixel arc length drives its `stroke-dashoffset`
    "draw-in" keyframe, computed server-side -- never a guessed
    constant duration that would desync from a line's actual length."""
    if not x_labels:
        raise ValueError("x_labels must not be empty")
    if not series:
        raise ValueError("series must not be empty")
    for name, values in series.items():
        if len(values) != len(x_labels):
            raise ValueError(f"series {name!r} length must match x_labels length")

    all_values = [v for values in series.values() for v in values]
    vmin, vmax = min(all_values), max(all_values)
    pad = (vmax - vmin) * 0.1 or 1.0
    vmin, vmax = vmin - pad, vmax + pad

    width, height, left_pad, bottom_pad, top_pad = 640, 240, 48, 24, 10
    plot_width, plot_height = width - left_pad - 16, height - bottom_pad - top_pad
    n = len(x_labels)

    def point(i: int, value: float) -> tuple[float, float]:
        x = left_pad + (i / (n - 1) if n > 1 else 0.0) * plot_width
        y = top_pad + _scale(value, vmax, vmin, 0.0, plot_height)
        return x, y

    lines = []
    legend = []
    for i, (name, values) in enumerate(series.items()):
        points = [point(j, v) for j, v in enumerate(values)]
        length = sum(
            math.hypot(points[j][0] - points[j - 1][0], points[j][1] - points[j - 1][1])
            for j in range(1, len(points))
        )
        path = " ".join(f"{x:.2f},{y:.2f}" for x, y in points)
        color = _PALETTE[i % len(_PALETTE)]
        lines.append(
            f'<polyline class="chart-line-draw" points="{path}" fill="none" '
            f'stroke="{color}" stroke-width="2.5" '
            f'style="stroke-dasharray:{length:.2f};stroke-dashoffset:{length:.2f};'
            f'animation-delay:{i * 0.15:.2f}s" data-series="{escape(name)}"></polyline>'
        )
        unit_suffix = f" ({escape(unit)})" if unit else ""
        legend.append(
            f'<span class="chart-legend-item" style="color:{color}">&#9632; '
            f"{escape(name)}{unit_suffix}</span>"
        )

    y_axis_labels = "".join(
        f'<text x="4" y="{top_pad + frac * plot_height + 4:.1f}" fill="#9a9890" '
        f'font-size="11">{(vmax - frac * (vmax - vmin)):.2f}</text>'
        for frac in (0.0, 0.5, 1.0)
    )
    svg = (
        f'<svg class="chart" viewBox="0 0 {width} {height}" width="{width}" height="{height}" '
        f'role="img" aria-label="line chart">{y_axis_labels}{"".join(lines)}</svg>'
    )
    return f'<div class="chart-legend">{"".join(legend)}</div>{svg}'


def calibration_indicator(*, passed: bool, label: str, detail: str) -> str:
    """A single pulsing pass/fail dot (CSS-animated, color-coded) next
    to a plain-text verdict -- "indicator" in the literal sense the
    user asked for, driven entirely by a real boolean the caller
    computed from a real statistical test, never a static decoration."""
    css_class = "indicator-pass" if passed else "indicator-fail"
    verdict_text = "PASSES" if passed else "FAILS"
    return (
        f'<p class="indicator-row"><span class="indicator-dot {css_class}" '
        f'data-passed="{str(passed).lower()}"></span> '
        f"<strong>{escape(label)}: {verdict_text}</strong> &mdash; {escape(detail)}</p>"
    )
