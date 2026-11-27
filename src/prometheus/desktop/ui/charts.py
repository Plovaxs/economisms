"""Charts drawn with QPainter: a line chart and a ranked bar chart. No charting dependency.

They follow the project's data-visualisation method, which is mostly a list of things *not* to do:

- **Marks are thin.** Lines are 2 px with round joins; bars are at most 24 px thick, square at the
  baseline with a 4 px rounded data end; gridlines and axes are solid one-pixel hairlines a step
  off the surface, never dashed; an area is a wash at about 10-12% opacity, never a block.
- **Dots carry a 2 px ring in the surface colour** so they stay legible where they cross a line.
  Nothing is separated by a drawn border.
- **Colour has one job.** Distinct entities take the categorical hues in their fixed order (and
  never a ninth: past eight the caller folds or facets); a single series is the first hue; an
  uncertainty band is one series' range, so it is one hue and a wash, not three colours.
- **Text wears text tokens**, never a series colour; identity comes from the short coloured stroke
  beside it. End labels are drawn only when they do not collide -- stacking them apart detaches
  them from their lines -- and otherwise the legend and the tooltip carry the names.
- **The tooltip enhances and never gates.** A crosshair snaps to the nearest data position and one
  readout lists every series there, values first and names second; the same readout appears when
  the chart has keyboard focus and the arrow keys move along the data. Every value is also in the
  table view that sits behind each chart (see `widgets.ChartCard`).

The geometry and the number formatting are plain functions (`nice_ticks`, `format_ticks`,
`bar_layout`) so they are tested without a pixel being drawn.
"""

from __future__ import annotations

import bisect
import math
from collections.abc import Sequence
from dataclasses import dataclass

from PySide6.QtCore import QEvent, QPointF, QRectF, QSize, Qt
from PySide6.QtGui import (
    QColor,
    QFocusEvent,
    QFont,
    QFontMetricsF,
    QKeyEvent,
    QMouseEvent,
    QPainter,
    QPainterPath,
    QPaintEvent,
    QPen,
    QPolygonF,
    QResizeEvent,
)
from PySide6.QtWidgets import QSizePolicy, QWidget

from prometheus.desktop.results import Chart, Line, format_value
from prometheus.desktop.ui import theme

MAX_SERIES = 8
BAND_ALPHA = 0.12
LINE_WIDTH = 2.0
DOT_RADIUS = 4.0
RING = 2.0
MAX_DIRECT_LABELS = 4
MIN_LABEL_GAP = 15.0
BAR_MAX_THICKNESS = 24.0
BAR_ROW_HEIGHT = 34.0

# ---------------------------------------------------------------------------------- numbers


def nice_step(raw: float) -> float:
    """The smallest of 1, 2, 5 x 10^n that is at least `raw`."""
    if not math.isfinite(raw) or raw <= 0:
        return 1.0
    scale = 10.0 ** math.floor(math.log10(raw))
    fraction = raw / scale
    for candidate in (1.0, 2.0, 5.0):
        if fraction <= candidate + 1e-12:
            return candidate * scale
    return 10.0 * scale


def tick_decimals(step: float) -> int:
    if step <= 0 or not math.isfinite(step):
        return 0
    return max(0, -math.floor(math.log10(step) + 1e-9))


def nice_ticks(low: float, high: float, target: int = 5) -> list[float]:
    """Round tick values covering `[low, high]` (extending to the next round values)."""
    if not (math.isfinite(low) and math.isfinite(high)):
        return [0.0, 1.0]
    if high < low:
        low, high = high, low
    if high == low:
        pad = abs(low) * 0.1 or 1.0
        low, high = low - pad, high + pad
    step = nice_step((high - low) / max(1, target))
    first = math.floor(low / step + 1e-9)
    last = math.ceil(high / step - 1e-9)
    decimals = tick_decimals(step) + 2
    return [round(i * step, decimals) for i in range(first, last + 1)]


def ticks_within(low: float, high: float, target: int = 6) -> list[float]:
    """Round ticks that lie inside `[low, high]` (for an axis whose range is the data's own)."""
    span = high - low
    inside = [
        t for t in nice_ticks(low, high, target) if low - 1e-9 * span <= t <= high + 1e-9 * span
    ]
    return inside if len(inside) >= 2 else [low, high]


def _decimals_needed(values: Sequence[float]) -> int:
    """The fewest decimals that show every value exactly (so 0.25 is not shown as 0.2)."""
    for decimals in range(9):
        if all(abs(round(v, decimals) - v) <= 1e-9 * max(1.0, abs(v)) for v in values):
            return decimals
    return 8


def format_ticks(ticks: Sequence[float]) -> list[str]:
    """Labels for one axis, in one style: full numbers under 10,000, compact (10K, 2.5M) once the
    axis reaches it, scientific when the values are tiny or enormous. One style means one number
    of decimals for the whole axis (0, 2.5M, 5.0M), enough to show every tick exactly."""
    if not ticks:
        return []
    biggest = max(abs(t) for t in ticks)
    if biggest and (biggest < 1e-3 or biggest >= 1e15):
        return [f"{t:.1e}" for t in ticks]
    if biggest >= 10_000:
        scale, suffix = next(
            (s, name)
            for s, name in ((1e12, "T"), (1e9, "B"), (1e6, "M"), (1e3, "K"))
            if biggest >= s
        )
        decimals = _decimals_needed([t / scale for t in ticks])
        return [f"{t / scale:.{decimals}f}{suffix}" if t else "0" for t in ticks]
    decimals = _decimals_needed(ticks)
    return [f"{t:,.{decimals}f}" for t in ticks]


def _precise(value: float) -> str:
    magnitude = abs(value)
    if magnitude != 0 and (magnitude < 1e-3 or magnitude >= 1e9):
        return f"{value:.4e}"
    if magnitude >= 1000:
        return f"{value:,.2f}"
    return f"{value:.4g}"


# ---------------------------------------------------------------------------------- bar layout


@dataclass(frozen=True, slots=True)
class BarRow:
    label: str
    value: float | None
    rect: QRectF | None
    """`None` for a row with no value: it gets a label and an em dash, never a zero-length bar."""


def bar_layout(
    rows: Sequence[tuple[str, float | None]],
    *,
    width: float,
    label_width: float,
    value_width: float,
    row_height: float = BAR_ROW_HEIGHT,
    top: float = 6.0,
) -> list[BarRow]:
    """Where each bar goes: ranked largest first, all from one baseline, thickness capped at 24 px.

    The baseline is the value zero: a bar for a negative value extends to its left. Rows without a
    value keep their place at the end with no bar.
    """
    ranked = sorted(rows, key=lambda item: (item[1] is None, -(item[1] or 0.0)))
    values = [v for _, v in ranked if v is not None]
    low, high = min([0.0, *values]), max([0.0, *values])
    if high == low:
        high = low + 1.0
    plot_left = label_width + 12.0
    plot_right = max(plot_left + 10.0, width - value_width - 8.0)
    scale = (plot_right - plot_left) / (high - low)
    zero_x = plot_left + (0.0 - low) * scale
    thickness = min(BAR_MAX_THICKNESS, row_height - 10.0)
    result: list[BarRow] = []
    for position, (label, value) in enumerate(ranked):
        center = top + position * row_height + row_height / 2
        if value is None:
            result.append(BarRow(label, None, None))
            continue
        end = zero_x + value * scale
        left, right = min(zero_x, end), max(zero_x, end)
        rect = QRectF(left, center - thickness / 2, max(right - left, 1.0), thickness)
        result.append(BarRow(label, value, rect))
    return result


# ---------------------------------------------------------------------------------- the line chart


@dataclass(frozen=True, slots=True)
class ReadoutRow:
    name: str
    value: str
    color: QColor


@dataclass(frozen=True, slots=True)
class Readout:
    x_label: str
    x_value: str
    rows: tuple[ReadoutRow, ...]


class _ChartBase(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

    def _small_font(self, pixels: int = 11, *, bold: bool = False) -> QFont:
        font = QFont(self.font())
        font.setPixelSize(max(1, round(pixels * theme.text_scale())))
        font.setBold(bold)
        return font

    def _draw_focus(self, painter: QPainter) -> None:
        if self.hasFocus():
            palette = theme.current()
            painter.setPen(QPen(palette.color(palette.accent), 2))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRoundedRect(QRectF(self.rect()).adjusted(1, 1, -1, -1), 6, 6)

    def _paint_tooltip(
        self, painter: QPainter, anchor: QPointF, header: str, rows: Sequence[ReadoutRow]
    ) -> None:
        palette = theme.current()
        value_font, name_font = self._small_font(13, bold=True), self._small_font(12)
        value_metrics, name_metrics = QFontMetricsF(value_font), QFontMetricsF(name_font)
        header_metrics = QFontMetricsF(name_font)
        key, pad, gap = 16.0, 10.0, 8.0
        width = (
            max(
                [header_metrics.horizontalAdvance(header)]
                + [
                    key
                    + gap
                    + value_metrics.horizontalAdvance(r.value)
                    + gap
                    + name_metrics.horizontalAdvance(r.name)
                    for r in rows
                ]
            )
            + 2 * pad
        )
        row_height = 20.0
        height = 2 * pad + 18.0 + row_height * len(rows)
        x = anchor.x() + 14
        if x + width > self.width() - 4:
            x = anchor.x() - 14 - width
        x = max(4.0, x)
        y = min(max(4.0, anchor.y() - height / 2), max(4.0, self.height() - height - 4))
        box = QRectF(x, y, width, height)
        painter.setPen(QPen(palette.color(palette.baseline), 1))
        painter.setBrush(palette.color(palette.surface))
        painter.drawRoundedRect(box, 6, 6)
        painter.setFont(name_font)
        painter.setPen(palette.color(palette.ink2))
        painter.drawText(
            QRectF(x + pad, y + pad - 2, width - 2 * pad, 18),
            int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft),
            header,
        )
        top = y + pad + 18
        for position, row in enumerate(rows):
            middle = top + position * row_height + row_height / 2
            painter.setPen(QPen(row.color, 2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            painter.drawLine(QPointF(x + pad, middle), QPointF(x + pad + key, middle))
            painter.setFont(value_font)
            painter.setPen(palette.color(palette.ink))
            value_x = x + pad + key + gap
            painter.drawText(
                QRectF(value_x, middle - 10, value_metrics.horizontalAdvance(row.value) + 2, 20),
                int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft),
                row.value,
            )
            painter.setFont(name_font)
            painter.setPen(palette.color(palette.ink2))
            painter.drawText(
                QRectF(
                    value_x + value_metrics.horizontalAdvance(row.value) + gap,
                    middle - 10,
                    name_metrics.horizontalAdvance(row.name) + 2,
                    20,
                ),
                int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft),
                row.name,
            )


@dataclass(slots=True)
class _LineGeometry:
    plot: QRectF
    x_low: float
    x_high: float
    y_low: float
    y_high: float
    y_ticks: list[float]
    y_labels: list[str]
    x_ticks: list[float]
    x_labels: list[str]
    paths: list[QPainterPath]
    points: list[list[QPointF]]
    label_positions: list[tuple[float, str]]


class LineChart(_ChartBase):
    """One or more lines against a shared horizontal axis."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._chart: Chart | None = None
        self._lines: tuple[Line, ...] = ()
        self._colors: list[QColor] = []
        self._skipped = 0
        self._cursor: int | None = None
        self._geometry: _LineGeometry | None = None
        self._reference: list[float] = []
        self.setMinimumHeight(240)

    # ------------------------------------------------------------------ data

    def set_chart(self, chart: Chart, choice: str | None = None) -> None:
        self._chart = chart
        visible = chart.visible(choice)
        self._skipped = max(0, len(visible) - MAX_SERIES)
        self._lines = visible[:MAX_SERIES]
        everyone = list(dict.fromkeys(line.name for line in chart.lines))
        palette = theme.current()
        if chart.band is not None:
            self._colors = [palette.series_color(0)] * len(self._lines)
        elif len(self._lines) == 1:
            self._colors = [palette.series_color(0)]
        else:
            self._colors = [palette.series_color(everyone.index(line.name)) for line in self._lines]
        first = self._lines[0] if self._lines else None
        self._reference = (
            list(first.x)
            if first is not None and first.x is not None
            else [float(i) for i in range(len(first.y))]
            if first is not None
            else []
        )
        self._cursor = None
        self.setAccessibleName(chart.title)
        self.setAccessibleDescription(self.description())
        self._relayout()
        self.update()

    @property
    def lines(self) -> tuple[Line, ...]:
        return self._lines

    @property
    def skipped_series(self) -> int:
        """Lines beyond the eighth, which is the most the palette can tell apart."""
        return self._skipped

    @property
    def cursor_index(self) -> int | None:
        return self._cursor

    def legend_entries(self) -> list[tuple[str, QColor]]:
        """One entry per distinct entity, in colour order (for a band, the one series)."""
        if self._chart is None or self._chart.band is not None:
            return []
        seen: dict[str, QColor] = {}
        for line, color in zip(self._lines, self._colors, strict=True):
            seen.setdefault(line.name, color)
        return list(seen.items())

    def description(self) -> str:
        if self._chart is None or not self._lines:
            return "Empty chart"
        values = [v for line in self._lines for v in line.y]
        names = ", ".join(line.name for line in self._lines)
        return (
            f"Line chart, {len(self._lines)} series ({names}), {len(self._reference)} points "
            f"along {self._chart.x_label}; values from {_precise(min(values))} to "
            f"{_precise(max(values))}. The same numbers are in the table view."
        )

    # ------------------------------------------------------------------ readout

    def _value_at(self, line: Line, x: float) -> float:
        if line.x is None:
            index = min(max(round(x), 0), len(line.y) - 1)
        else:
            index = bisect.bisect_left(line.x, x)
            if index > 0 and (
                index == len(line.x) or abs(line.x[index - 1] - x) <= abs(line.x[index] - x)
            ):
                index -= 1
            index = min(index, len(line.y) - 1)
        return line.y[index]

    def readout(self, index: int) -> Readout:
        """The tooltip's content for data position `index` -- also the keyboard readout."""
        x = self._reference[index]
        rows = tuple(
            ReadoutRow(line.name, _precise(self._value_at(line, x)), color)
            for line, color in zip(self._lines, self._colors, strict=True)
        )
        label = self._chart.x_label if self._chart else ""
        return Readout(label, _precise(x), rows)

    def set_cursor(self, index: int | None) -> None:
        if index is not None and not self._reference:
            index = None
        if index is not None:
            index = min(max(index, 0), len(self._reference) - 1)
        if index != self._cursor:
            self._cursor = index
            self.update()

    def index_for_pixel(self, pixel_x: float) -> int | None:
        geometry = self._geometry
        if geometry is None or not self._reference:
            return None
        span = geometry.x_high - geometry.x_low or 1.0
        x = geometry.x_low + (pixel_x - geometry.plot.left()) / geometry.plot.width() * span
        index = bisect.bisect_left(self._reference, x)
        if index > 0 and (
            index == len(self._reference)
            or abs(self._reference[index - 1] - x) <= abs(self._reference[index] - x)
        ):
            index -= 1
        return min(index, len(self._reference) - 1)

    # ------------------------------------------------------------------ geometry

    def _relayout(self) -> None:
        if not self._lines or self.width() < 40 or self.height() < 40:
            self._geometry = None
            return
        small = QFontMetricsF(self._small_font())
        ys = [v for line in self._lines for v in line.y]
        y_ticks = nice_ticks(min(ys), max(ys), 5)
        y_labels = format_ticks(y_ticks)
        x_values = [
            x
            for line in self._lines
            for x in (line.x if line.x is not None else range(len(line.y)))
        ]
        x_low, x_high = float(min(x_values)), float(max(x_values))
        if x_low == x_high:
            x_low, x_high = x_low - 0.5, x_high + 0.5
        x_ticks = ticks_within(x_low, x_high, 6)
        x_labels = format_ticks(x_ticks)
        left = max(small.horizontalAdvance(t) for t in y_labels) + 16
        direct = self._direct_label_width(small)
        right = 14.0 + direct
        top, bottom = 12.0, small.height() * 2 + 16
        plot = QRectF(
            left,
            top,
            max(20.0, self.width() - left - right),
            max(20.0, self.height() - top - bottom),
        )
        y_low, y_high = y_ticks[0], y_ticks[-1]

        def px(x: float) -> float:
            return plot.left() + (x - x_low) / (x_high - x_low) * plot.width()

        def py(y: float) -> float:
            return plot.bottom() - (y - y_low) / ((y_high - y_low) or 1.0) * plot.height()

        paths: list[QPainterPath] = []
        points: list[list[QPointF]] = []
        for line in self._lines:
            xs = line.x if line.x is not None else tuple(float(i) for i in range(len(line.y)))
            pts = [QPointF(px(x), py(y)) for x, y in zip(xs, line.y, strict=True)]
            path = QPainterPath(pts[0])
            for point in pts[1:]:
                path.lineTo(point)
            paths.append(path)
            points.append(pts)
        labels: list[tuple[float, str]] = []
        if 2 <= len(self._lines) <= MAX_DIRECT_LABELS:
            ends = sorted(
                ((pts[-1].y(), line.name) for pts, line in zip(points, self._lines, strict=True)),
                key=lambda item: item[0],
            )
            if all(b[0] - a[0] >= MIN_LABEL_GAP for a, b in zip(ends, ends[1:], strict=False)):
                labels = ends
        self._geometry = _LineGeometry(
            plot,
            x_low,
            x_high,
            y_low,
            y_high,
            y_ticks,
            y_labels,
            x_ticks,
            x_labels,
            paths,
            points,
            labels,
        )

    def _direct_label_width(self, metrics: QFontMetricsF) -> float:
        if not 2 <= len(self._lines) <= MAX_DIRECT_LABELS:
            return 0.0
        return min(
            150.0,
            max((metrics.horizontalAdvance(line.name) for line in self._lines), default=0.0) + 12,
        )

    def direct_labels_shown(self) -> list[str]:
        """The end labels drawn (empty when they would collide: the legend carries the names)."""
        return [name for _, name in self._geometry.label_positions] if self._geometry else []

    def resizeEvent(self, event: QResizeEvent) -> None:
        self._relayout()
        super().resizeEvent(event)

    # ------------------------------------------------------------------ interaction

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        self.set_cursor(self.index_for_pixel(event.position().x()))

    def leaveEvent(self, event: QEvent) -> None:
        if not self.hasFocus():
            self.set_cursor(None)

    def focusInEvent(self, event: QFocusEvent) -> None:
        if self._cursor is None and self._reference:
            self.set_cursor(len(self._reference) - 1)
        super().focusInEvent(event)

    def focusOutEvent(self, event: QFocusEvent) -> None:
        self.set_cursor(None)
        super().focusOutEvent(event)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if not self._reference:
            super().keyPressEvent(event)
            return
        current = self._cursor if self._cursor is not None else len(self._reference) - 1
        steps = {Qt.Key.Key_Left: -1, Qt.Key.Key_Right: 1}
        key = Qt.Key(event.key())
        if key in steps:
            jump = 10 if event.modifiers() & Qt.KeyboardModifier.ShiftModifier else 1
            self.set_cursor(current + steps[key] * jump)
        elif key == Qt.Key.Key_Home:
            self.set_cursor(0)
        elif key == Qt.Key.Key_End:
            self.set_cursor(len(self._reference) - 1)
        elif key == Qt.Key.Key_Escape:
            self.set_cursor(None)
        else:
            super().keyPressEvent(event)

    def sizeHint(self) -> QSize:
        return QSize(560, 300)

    # ------------------------------------------------------------------ painting

    def paintEvent(self, event: QPaintEvent) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        palette = theme.current()
        geometry = self._geometry
        if geometry is None or self._chart is None:
            painter.setPen(palette.color(palette.ink2))
            painter.drawText(self.rect(), int(Qt.AlignmentFlag.AlignCenter), "No data to plot")
            self._draw_focus(painter)
            return
        plot = geometry.plot
        tick_font = self._small_font()
        metrics = QFontMetricsF(tick_font)
        painter.setFont(tick_font)

        def py(y: float) -> float:
            return (
                plot.bottom()
                - (y - geometry.y_low) / ((geometry.y_high - geometry.y_low) or 1.0) * plot.height()
            )

        # gridlines and y labels: solid hairlines, one step off the surface
        for tick, label in zip(geometry.y_ticks, geometry.y_labels, strict=True):
            y = py(tick)
            painter.setPen(QPen(palette.color(palette.grid), 1))
            painter.drawLine(QPointF(plot.left(), y), QPointF(plot.right(), y))
            painter.setPen(palette.color(palette.ink2))
            painter.drawText(
                QRectF(0, y - 9, plot.left() - 8, 18),
                int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter),
                label,
            )
        if geometry.y_low < 0 < geometry.y_high:
            painter.setPen(QPen(palette.color(palette.baseline), 1))
            painter.drawLine(QPointF(plot.left(), py(0.0)), QPointF(plot.right(), py(0.0)))
        painter.setPen(QPen(palette.color(palette.baseline), 1))
        painter.drawLine(plot.bottomLeft(), plot.bottomRight())
        span = (geometry.x_high - geometry.x_low) or 1.0
        for tick, label in zip(geometry.x_ticks, geometry.x_labels, strict=True):
            x = plot.left() + (tick - geometry.x_low) / span * plot.width()
            painter.setPen(QPen(palette.color(palette.baseline), 1))
            painter.drawLine(QPointF(x, plot.bottom()), QPointF(x, plot.bottom() + 4))
            width = metrics.horizontalAdvance(label)
            painter.setPen(palette.color(palette.ink2))
            painter.drawText(
                QRectF(x - width / 2 - 2, plot.bottom() + 6, width + 4, metrics.height()),
                int(Qt.AlignmentFlag.AlignCenter),
                label,
            )
        painter.setPen(palette.color(palette.ink2))
        painter.drawText(
            QRectF(
                plot.left(), self.height() - metrics.height() - 2, plot.width(), metrics.height()
            ),
            int(Qt.AlignmentFlag.AlignCenter),
            self._chart.x_label,
        )

        band = self._chart.band
        names = [line.name for line in self._lines]
        if band is not None and band[0] in names and band[1] in names:
            lower = geometry.points[names.index(band[0])]
            upper = geometry.points[names.index(band[1])]
            wash = QPolygonF([*lower, *reversed(upper)])
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(palette.color(palette.series[0], BAND_ALPHA))
            painter.drawPolygon(wash)
        for position, (path, color) in enumerate(zip(geometry.paths, self._colors, strict=True)):
            is_edge = band is not None and names[position] in band
            line_color = QColor(color)
            width = LINE_WIDTH
            if is_edge:
                line_color.setAlphaF(0.55)
                width = 1.0
            painter.setPen(
                QPen(
                    line_color,
                    width,
                    Qt.PenStyle.SolidLine,
                    Qt.PenCapStyle.RoundCap,
                    Qt.PenJoinStyle.RoundJoin,
                )
            )
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawPath(path)
        for pts, color in zip(geometry.points, self._colors, strict=True):
            self._dot(painter, pts[-1], color)
        if geometry.label_positions:
            painter.setFont(self._small_font(12))
            painter.setPen(palette.color(palette.ink))
            label_metrics = QFontMetricsF(self._small_font(12))
            room = self.width() - plot.right() - 14
            for y, name in geometry.label_positions:
                text = label_metrics.elidedText(name, Qt.TextElideMode.ElideRight, room)
                painter.drawText(
                    QRectF(plot.right() + 12, y - 9, room, 18),
                    int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft),
                    text,
                )
        if self._cursor is not None:
            self._paint_cursor(painter, geometry)
        self._draw_focus(painter)

    def _dot(self, painter: QPainter, center: QPointF, color: QColor) -> None:
        palette = theme.current()
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(palette.color(palette.surface))
        painter.drawEllipse(center, DOT_RADIUS + RING, DOT_RADIUS + RING)
        painter.setBrush(color)
        painter.drawEllipse(center, DOT_RADIUS, DOT_RADIUS)

    def _paint_cursor(self, painter: QPainter, geometry: _LineGeometry) -> None:
        index = self._cursor
        if index is None:
            return
        palette = theme.current()
        x_value = self._reference[index]
        span = (geometry.x_high - geometry.x_low) or 1.0
        x = geometry.plot.left() + (x_value - geometry.x_low) / span * geometry.plot.width()
        painter.setPen(QPen(palette.color(palette.ink2), 1))
        painter.drawLine(QPointF(x, geometry.plot.top()), QPointF(x, geometry.plot.bottom()))
        anchor_y = geometry.plot.center().y()
        for line, color in zip(self._lines, self._colors, strict=True):
            value = self._value_at(line, x_value)
            y = (
                geometry.plot.bottom()
                - (value - geometry.y_low)
                / ((geometry.y_high - geometry.y_low) or 1.0)
                * geometry.plot.height()
            )
            self._dot(painter, QPointF(x, y), color)
            anchor_y = y
        readout = self.readout(index)
        self._paint_tooltip(
            painter, QPointF(x, anchor_y), f"{readout.x_label}: {readout.x_value}", readout.rows
        )


# ---------------------------------------------------------------------------------- the bar chart


class BarChart(_ChartBase):
    """Named rows compared on one number: ranked horizontal bars from a single baseline.

    The rows are nominal categories, so every bar takes the first hue; a bar's length already says
    how much, and colouring it by value would spend the identity channel twice.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._title = ""
        self._column = ""
        self._rows: list[tuple[str, float | None]] = []
        self._layout: list[BarRow] = []
        self._hover: int | None = None
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def set_data(self, title: str, rows: Sequence[tuple[str, float | None]], column: str) -> None:
        self._title, self._column = title, column
        self._rows = list(rows)
        self._hover = None
        height = int(len(self._rows) * BAR_ROW_HEIGHT + 14)
        self.setFixedHeight(max(60, height))
        self.setAccessibleName(f"{title}: {column}")
        self.setAccessibleDescription(self.description())
        self._relayout()
        self.update()

    def description(self) -> str:
        shown = ", ".join(
            f"{label} {format_value(value)}"
            for label, value in self.ranked_rows()
            if value is not None
        )
        return f"Bar chart of {self._column} for {len(self._rows)} rows, largest first: {shown}."

    def ranked_rows(self) -> list[tuple[str, float | None]]:
        return [(row.label, row.value) for row in self._layout]

    @property
    def bars(self) -> list[BarRow]:
        return self._layout

    @property
    def hovered(self) -> int | None:
        return self._hover

    def _label_width(self) -> float:
        metrics = QFontMetricsF(self._small_font(12))
        widest = max((metrics.horizontalAdvance(label) for label, _ in self._rows), default=0.0)
        return min(widest + 4, self.width() * 0.38)

    def _value_width(self) -> float:
        metrics = QFontMetricsF(self._small_font(12, bold=True))
        return (
            max(
                (
                    metrics.horizontalAdvance(format_value(v))
                    for _, v in self._rows
                    if v is not None
                ),
                default=30.0,
            )
            + 8
        )

    def _relayout(self) -> None:
        if self.width() < 60:
            self._layout = bar_layout(self._rows, width=400, label_width=100, value_width=60)
            return
        self._layout = bar_layout(
            self._rows,
            width=self.width(),
            label_width=self._label_width(),
            value_width=self._value_width(),
        )

    def resizeEvent(self, event: QResizeEvent) -> None:
        self._relayout()
        super().resizeEvent(event)

    def sizeHint(self) -> QSize:
        return QSize(520, int(len(self._rows) * BAR_ROW_HEIGHT + 14))

    def set_hover(self, index: int | None) -> None:
        if index is not None:
            index = min(max(index, 0), len(self._layout) - 1) if self._layout else None
        if index != self._hover:
            self._hover = index
            self.update()

    def row_at(self, point: QPointF) -> int | None:
        top = 6.0
        index = int((point.y() - top) // BAR_ROW_HEIGHT)
        return index if 0 <= index < len(self._layout) else None

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        self.set_hover(self.row_at(event.position()))

    def leaveEvent(self, event: QEvent) -> None:
        if not self.hasFocus():
            self.set_hover(None)

    def focusInEvent(self, event: QFocusEvent) -> None:
        if self._hover is None and self._layout:
            self.set_hover(0)
        super().focusInEvent(event)

    def focusOutEvent(self, event: QFocusEvent) -> None:
        self.set_hover(None)
        super().focusOutEvent(event)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        key = Qt.Key(event.key())
        current = self._hover if self._hover is not None else -1
        if key == Qt.Key.Key_Down:
            self.set_hover(current + 1)
        elif key == Qt.Key.Key_Up:
            self.set_hover(max(0, current - 1))
        elif key == Qt.Key.Key_Home:
            self.set_hover(0)
        elif key == Qt.Key.Key_End:
            self.set_hover(len(self._layout) - 1)
        elif key == Qt.Key.Key_Escape:
            self.set_hover(None)
        else:
            super().keyPressEvent(event)

    def paintEvent(self, event: QPaintEvent) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        palette = theme.current()
        label_font, value_font = self._small_font(12), self._small_font(12, bold=True)
        label_metrics = QFontMetricsF(label_font)
        label_width = self._label_width()
        zero_x = None
        for position, row in enumerate(self._layout):
            center = 6.0 + position * BAR_ROW_HEIGHT + BAR_ROW_HEIGHT / 2
            painter.setFont(label_font)
            painter.setPen(palette.color(palette.ink2))
            painter.drawText(
                QRectF(0, center - 10, label_width, 20),
                int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter),
                label_metrics.elidedText(row.label, Qt.TextElideMode.ElideLeft, label_width),
            )
            if row.rect is None or row.value is None:
                painter.setPen(palette.color(palette.ink2))
                painter.drawText(
                    QRectF(label_width + 12, center - 10, 40, 20),
                    int(Qt.AlignmentFlag.AlignVCenter),
                    "—",
                )
                continue
            lifted = position == self._hover
            color = palette.series_color(0)
            if lifted:
                color = color.lighter(118) if palette.name == "dark" else color.darker(112)
            rect = row.rect
            zero_x = rect.left() if row.value >= 0 else rect.right()
            path = QPainterPath()
            path.addRoundedRect(rect, 4, 4)
            square = QPainterPath()
            edge = min(8.0, rect.width())
            square.addRect(
                QRectF(rect.left(), rect.top(), edge, rect.height())
                if row.value >= 0
                else QRectF(rect.right() - edge, rect.top(), edge, rect.height())
            )
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(color)
            painter.drawPath(path.united(square))
            painter.setFont(value_font)
            painter.setPen(palette.color(palette.ink))
            tip = rect.right() + 8 if row.value >= 0 else rect.left() - 8 - 60
            alignment = (
                Qt.AlignmentFlag.AlignLeft if row.value >= 0 else Qt.AlignmentFlag.AlignRight
            )
            painter.drawText(
                QRectF(
                    tip, center - 10, 60 if row.value < 0 else max(60.0, self.width() - tip), 20
                ),
                int(alignment | Qt.AlignmentFlag.AlignVCenter),
                format_value(row.value),
            )
        if zero_x is not None:
            painter.setPen(QPen(palette.color(palette.baseline), 1))
            painter.drawLine(QPointF(zero_x, 4), QPointF(zero_x, self.height() - 4))
        if self._hover is not None and 0 <= self._hover < len(self._layout):
            row = self._layout[self._hover]
            if row.rect is not None and row.value is not None:
                # beside the value printed at the bar's tip, on the same row, so that it covers
                # empty space and not the neighbouring bars' values
                tip = QFontMetricsF(value_font).horizontalAdvance(format_value(row.value))
                edge = row.rect.right() if row.value >= 0 else row.rect.left()
                self._paint_tooltip(
                    painter,
                    QPointF(edge + tip + 4, row.rect.center().y()),
                    self._column,
                    (ReadoutRow(row.label, format_value(row.value), palette.series_color(0)),),
                )
        self._draw_focus(painter)
