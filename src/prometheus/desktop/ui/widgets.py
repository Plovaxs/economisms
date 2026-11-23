"""The window's building blocks: cards, status badges, metric tiles, tables, a lazy JSON tree, and
the chart card that puts a table view behind every chart.

Two rules shape everything here. A status is never colour alone: a badge always carries a glyph
and a word. And a number that a chart shows is always reachable another way: the chart card's
table view lists exactly the points drawn, and every table can be copied or exported.
"""

from __future__ import annotations

import csv
import html
import io
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from PySide6.QtCore import QPointF, QRectF, QSize, Qt
from PySide6.QtGui import (
    QColor,
    QFontMetricsF,
    QGuiApplication,
    QKeyEvent,
    QKeySequence,
    QPainter,
    QPaintEvent,
    QPen,
)
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLayout,
    QScrollArea,
    QSizePolicy,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QToolButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from prometheus.desktop.results import Chart, Comparison, Table, format_value
from prometheus.desktop.ui import theme
from prometheus.desktop.ui.charts import BarChart, LineChart, _precise

STATUS_TONES: dict[str, tuple[str, str]] = {
    "ok": ("good", "✓"),
    "good": ("good", "✓"),
    "succeeded": ("good", "✓"),
    "warn": ("warn", "!"),
    "timed_out": ("warn", "!"),
    "fail": ("bad", "✕"),
    "bad": ("bad", "✕"),
    "failed": ("bad", "✕"),
    "skip": ("neutral", "–"),
    "cancelled": ("neutral", "–"),
    "queued": ("neutral", "…"),
    "running": ("accent", "●"),
    "neutral": ("neutral", "•"),
    "accent": ("accent", "◆"),
}
MAX_COLUMN_WIDTH = 360
ROW_HEIGHT = 28
TILE_LARGE_CHARS = 20


def plain_tooltip(text: str) -> str:
    """A tooltip that shows `text` exactly. Qt renders a tooltip as rich text when it looks like
    HTML, and a clipped table cell is data (it can hold `<img ...>`), so it is escaped."""
    return "<p style='white-space:pre-wrap'>" + html.escape(text) + "</p>"


def repolish(widget: QWidget) -> None:
    """Re-apply the style sheet after a dynamic property (a tone, an error flag) changed."""
    style = widget.style()
    style.unpolish(widget)
    style.polish(widget)
    widget.update()


def make_label(
    text: str = "", role: str | None = None, *, wrap: bool = True, selectable: bool = False
) -> QLabel:
    label = QLabel(text)
    # A label's default is "auto": text that merely looks like HTML is rendered as HTML. Result
    # payloads, model names and dataset strings are data, not markup, so they are shown as typed.
    label.setTextFormat(Qt.TextFormat.PlainText)
    label.setWordWrap(wrap)
    if role:
        label.setProperty("role", role)
    if selectable:
        label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
    return label


class ElidedLabel(QLabel):
    """One line of plain text that gives way when there is no room, instead of forcing its
    neighbours smaller (a button squeezed to "eset to defaul"). The whole text stays in the
    tooltip and the accessible name."""

    def __init__(self, text: str = "", role: str | None = None, parent: QWidget | None = None):
        super().__init__(parent)
        self.setTextFormat(Qt.TextFormat.PlainText)
        if role:
            self.setProperty("role", role)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self._full = ""
        self.setText(text)

    def full_text(self) -> str:
        return self._full

    def setText(self, text: str) -> None:  # noqa: N802 -- Qt's name
        self._full = text
        self.setAccessibleName(text)
        self._refresh()

    def minimumSizeHint(self) -> QSize:  # noqa: N802
        return QSize(24, super().minimumSizeHint().height())

    def resizeEvent(self, event: Any) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._refresh()

    def _refresh(self) -> None:
        shown = self.fontMetrics().elidedText(
            self._full, Qt.TextElideMode.ElideRight, max(self.width(), 0)
        )
        super().setText(shown if self.width() > 0 else self._full)
        self.setToolTip(plain_tooltip(self._full) if shown != self._full else "")


def scrollable(widget: QWidget) -> QScrollArea:
    area = QScrollArea()
    area.setWidgetResizable(True)
    area.setFrameShape(QFrame.Shape.NoFrame)
    area.setWidget(widget)
    return area


def clear_layout(layout: QLayout) -> None:
    """Remove and delete everything in `layout`, nested layouts included."""
    while layout.count():
        item = layout.takeAt(0)
        if item is None:
            break
        widget = item.widget()
        if widget is not None:
            widget.setParent(None)
            widget.deleteLater()
        child = item.layout()
        if child is not None:
            clear_layout(child)
            child.deleteLater()


def horizontal_rule() -> QFrame:
    rule = QFrame()
    rule.setObjectName("rule")
    rule.setFrameShape(QFrame.Shape.HLine)
    return rule


class Card(QFrame):
    """A raised surface with a hairline border: the unit the pages are built from."""

    def __init__(self, parent: QWidget | None = None, *, margins: int = 16) -> None:
        super().__init__(parent)
        self.setObjectName("card")
        self.body = QVBoxLayout(self)
        self.body.setContentsMargins(margins, margins - 2, margins, margins - 2)
        self.body.setSpacing(10)


class Badge(QLabel):
    """A status pill. The glyph and the word carry the meaning; the tint only reinforces it."""

    _word: str = ""

    def __init__(
        self, text: str = "", status: str = "neutral", parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self.setTextFormat(Qt.TextFormat.PlainText)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
        self.status = status
        self.set_status(status, text)

    def set_status(self, status: str, text: str | None = None) -> None:
        tone, glyph = STATUS_TONES.get(status, STATUS_TONES["neutral"])
        word = text if text is not None else self._word
        self._word = word
        self.status = status
        self.setProperty("tone", tone)
        self.setText(f"{glyph}  {word}" if word else glyph)
        self.setAccessibleName(f"{status}: {word}" if word else status)
        repolish(self)


class MetricTile(QFrame):
    """One headline number: a small label above a large value."""

    def __init__(self, label: str, value: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("tile")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 10, 14, 12)
        layout.setSpacing(2)
        self._label = make_label(label, "caption")
        self._value = make_label("", "metric", selectable=True)
        layout.addWidget(self._label)
        layout.addWidget(self._value)
        self.label_text = label
        self._raw = value
        self.setMinimumHeight(74)
        self.set_value(value)

    def set_value(self, value: str) -> None:
        self._raw = value
        # a zero-width space after each underscore, hyphen and slash lets a long identifier wrap
        # instead of running out of its tile
        shown = value.replace("_", "_\u200b").replace("-", "-\u200b").replace("/", "/\u200b")
        self._value.setText(shown)
        self._value.setProperty("role", "metric" if len(value) <= TILE_LARGE_CHARS else "h3")
        repolish(self._value)
        self.setAccessibleName(f"{self.label_text}: {value}")

    @property
    def value_text(self) -> str:
        return self._raw


class Legend(QWidget):
    """Line keys (a short stroke in the series colour) beside names in text colour.

    Mirrors the mark: a stroke for lines. It wraps to the width it is given.
    """

    PAD = 14.0

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._entries: list[tuple[str, QColor]] = []
        sizing = QSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        sizing.setHeightForWidth(True)
        self.setSizePolicy(sizing)

    def set_entries(self, entries: Sequence[tuple[str, QColor]]) -> None:
        self._entries = list(entries)
        self.setVisible(len(self._entries) >= 2)
        self.setAccessibleName("Legend: " + ", ".join(name for name, _ in self._entries))
        self.updateGeometry()
        self.update()

    @property
    def entries(self) -> list[tuple[str, QColor]]:
        return list(self._entries)

    def _flow(self, width: float) -> tuple[list[tuple[float, float, str, QColor]], float]:
        metrics = QFontMetricsF(self.font())
        placed: list[tuple[float, float, str, QColor]] = []
        x, y, row_height = 0.0, 0.0, 22.0
        for name, color in self._entries:
            need = 18 + 8 + metrics.horizontalAdvance(name) + self.PAD
            if x > 0 and x + need > width:
                x, y = 0.0, y + row_height
            placed.append((x, y, name, color))
            x += need
        return placed, y + row_height

    def hasHeightForWidth(self) -> bool:
        return True

    def heightForWidth(self, width: int) -> int:
        return int(self._flow(float(width))[1]) + 2

    def sizeHint(self) -> QSize:
        return QSize(300, self.heightForWidth(300))

    def paintEvent(self, event: QPaintEvent) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        palette = theme.current()
        placed, _ = self._flow(float(self.width()))
        for x, y, name, color in placed:
            middle = y + 11
            painter.setPen(QPen(color, 2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            painter.drawLine(QPointF(x + 1, middle), QPointF(x + 17, middle))
            painter.setPen(palette.color(palette.ink2))
            painter.drawText(
                QRectF(x + 26, y, self.width() - x - 26, 22),
                int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft),
                name,
            )


# ---------------------------------------------------------------------------------- tables


def parse_number(text: str) -> float | None:
    cleaned = text.replace(",", "").replace(" ", "").strip()
    try:
        return float(cleaned)
    except ValueError:
        return None


class _SortableItem(QTableWidgetItem):
    """Sorts numbers as numbers (`10` after `9`), text as text."""

    def __lt__(self, other: QTableWidgetItem) -> bool:
        mine, theirs = parse_number(self.text()), parse_number(other.text())
        if mine is not None and theirs is not None:
            return mine < theirs
        return self.text() < other.text()


class DataTable(QTableWidget):
    """A read-only grid: numbers right-aligned and sortable, Ctrl+C copies the selection as
    tab-separated text (it pastes into a spreadsheet), and the whole table can be exported."""

    def __init__(self, name: str = "Table", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setAccessibleName(name)
        self.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.setAlternatingRowColors(True)
        self.setWordWrap(False)
        self.setTextElideMode(Qt.TextElideMode.ElideRight)
        self.verticalHeader().hide()
        self.verticalHeader().setDefaultSectionSize(ROW_HEIGHT)
        self.horizontalHeader().setStretchLastSection(True)
        self.horizontalHeader().setHighlightSections(False)
        self.horizontalHeader().setDefaultAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        )
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.truncated = 0

    def set_rows(
        self,
        columns: Sequence[str],
        rows: Sequence[Sequence[str]],
        numeric: Sequence[bool] | None = None,
        *,
        sortable: bool = True,
    ) -> None:
        self.setSortingEnabled(False)
        self.clear()
        self.setColumnCount(len(columns))
        self.setRowCount(len(rows))
        self.setHorizontalHeaderLabels(list(columns))
        flags = numeric if numeric is not None else [False] * len(columns)
        for r, row in enumerate(rows):
            for c, text in enumerate(row):
                item = _SortableItem(text)
                align = Qt.AlignmentFlag.AlignVCenter | (
                    Qt.AlignmentFlag.AlignRight if flags[c] else Qt.AlignmentFlag.AlignLeft
                )
                item.setTextAlignment(align)
                item.setToolTip(plain_tooltip(text) if len(text) > 40 else "")
                self.setItem(r, c, item)
        self.resizeColumnsToContents()
        for c in range(len(columns)):
            self.setColumnWidth(c, min(max(self.columnWidth(c) + 12, 70), MAX_COLUMN_WIDTH))
        if sortable:  # keep the order given until a header is clicked
            self.horizontalHeader().setSortIndicator(-1, Qt.SortOrder.AscendingOrder)
        self.setSortingEnabled(sortable)
        visible = min(max(len(rows), 1), 12)
        self.setMinimumHeight(visible * ROW_HEIGHT + 36)

    def set_table(self, table: Table) -> None:
        self.truncated = table.truncated
        self.set_rows(table.columns, table.rows, table.numeric)

    def headers(self) -> list[str]:
        names: list[str] = []
        for column in range(self.columnCount()):
            item = self.horizontalHeaderItem(column)
            names.append(item.text() if item is not None else "")
        return names

    def cell(self, row: int, column: int) -> str:
        item = self.item(row, column)
        return item.text() if item else ""

    def to_text(self, delimiter: str = "\t", *, selection_only: bool = False) -> str:
        stream = io.StringIO()
        writer = csv.writer(stream, delimiter=delimiter, lineterminator="\n")
        if selection_only:
            ranges = self.selectedRanges()
            if not ranges:
                return ""
            top, bottom = min(r.topRow() for r in ranges), max(r.bottomRow() for r in ranges)
            left, right = min(r.leftColumn() for r in ranges), max(r.rightColumn() for r in ranges)
        else:
            writer.writerow(self.headers())
            top, bottom, left, right = 0, self.rowCount() - 1, 0, self.columnCount() - 1
        for row in range(top, bottom + 1):
            writer.writerow([self.cell(row, c) for c in range(left, right + 1)])
        return stream.getvalue()

    def to_csv(self) -> str:
        return self.to_text(",")

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.matches(QKeySequence.StandardKey.Copy):
            QGuiApplication.clipboard().setText(self.to_text(selection_only=True))
            return
        super().keyPressEvent(event)


def key_value_table(name: str, items: Sequence[tuple[str, str]]) -> DataTable:
    table = DataTable(name)
    table.set_rows(["Name", "Value"], [(k, v) for k, v in items], [False, False], sortable=False)
    table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
    return table


def save_text(parent: QWidget | None, suggested: str, text: str, filter_: str) -> Path | None:
    """Ask where to save and write `text` there; `None` if the person cancelled."""
    chosen, _ = QFileDialog.getSaveFileName(parent, "Save", suggested, filter_)
    if not chosen:
        return None
    path = Path(chosen)
    path.write_text(text, encoding="utf-8", newline="")
    return path


# ---------------------------------------------------------------------------------- JSON tree

MAX_TREE_CHILDREN = 300


class JsonTree(QTreeWidget):
    """The verified payload itself, so that nothing is hidden by the summary's heuristics.

    Children are created when a node is first opened: a result can be sixteen megabytes.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setAccessibleName("Raw result")
        self.setColumnCount(2)
        self.setHeaderLabels(["Key", "Value"])
        self.setAlternatingRowColors(True)
        self.setUniformRowHeights(True)
        self.itemExpanded.connect(self._expand)
        self._nodes: dict[int, Any] = {}

    def set_payload(self, payload: Any) -> None:
        self.clear()
        self._nodes = {}
        self._populate(self.invisibleRootItem(), payload)
        self.resizeColumnToContents(0)

    @staticmethod
    def _preview(value: Any) -> str:
        if isinstance(value, dict):
            return f"{{{len(value)} keys}}"
        if isinstance(value, list):
            return f"[{len(value)} items]"
        return format_value(value)

    def _populate(self, parent: QTreeWidgetItem, value: Any) -> None:
        if isinstance(value, dict):
            entries = [(str(k), v) for k, v in value.items()]
        elif isinstance(value, list):
            entries = [(f"[{i}]", v) for i, v in enumerate(value)]
        else:
            return
        for key, child in entries[:MAX_TREE_CHILDREN]:
            item = QTreeWidgetItem([key, self._preview(child)])
            if isinstance(child, (dict, list)) and child:
                self._nodes[id(item)] = child
                item.addChild(QTreeWidgetItem(["…", ""]))  # makes the node expandable
            parent.addChild(item)
        if len(entries) > MAX_TREE_CHILDREN:
            parent.addChild(
                QTreeWidgetItem([f"… {len(entries) - MAX_TREE_CHILDREN} more", "not listed here"])
            )

    def _expand(self, item: QTreeWidgetItem) -> None:
        child = self._nodes.pop(id(item), None)
        if child is None:
            return
        item.takeChildren()
        self._populate(item, child)


# ---------------------------------------------------------------------------------- the chart card


class ChartCard(Card):
    """A titled chart with its legend, a choice of series, and a table view of the same data."""

    def __init__(self, title: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.title = title
        header = QHBoxLayout()
        self._heading = make_label(title, "h3", wrap=False)
        header.addWidget(self._heading, 1)
        self._select_label = make_label("Show", "caption", wrap=False)
        self._select_label.setVisible(False)
        header.addWidget(self._select_label)
        self._select = QComboBox()
        self._select.setAccessibleName(f"Choose what {title} shows")
        self._select.setVisible(False)
        header.addWidget(self._select)
        self._toggle = QToolButton()
        self._toggle.setText("Table")
        self._toggle.setCheckable(True)
        self._toggle.setProperty("chip", True)
        self._toggle.setToolTip("Show the numbers behind this chart")
        self._toggle.setAccessibleName(f"Show {title} as a table")
        header.addWidget(self._toggle)
        self.body.addLayout(header)
        self._stack = QStackedWidget()
        chart_page = QWidget()
        page_layout = QVBoxLayout(chart_page)
        page_layout.setContentsMargins(0, 0, 0, 0)
        page_layout.setSpacing(6)
        self.legend = Legend()
        self.line_chart = LineChart()
        self.bar_chart = BarChart()
        page_layout.addWidget(self.legend)
        page_layout.addWidget(self.line_chart)
        page_layout.addWidget(self.bar_chart)
        self.table = DataTable(f"{title} (table)")
        self._stack.addWidget(chart_page)
        self._stack.addWidget(self.table)
        self.body.addWidget(self._stack)
        self._caption = make_label("", "caption")
        self._caption.setVisible(False)
        self.body.addWidget(self._caption)
        self._toggle.toggled.connect(self._flip)
        self._chart: Chart | None = None
        self._comparison: Comparison | None = None
        self._select.currentTextChanged.connect(self._reselect)

    # ------------------------------------------------------------------ showing

    def show_chart(self, chart: Chart) -> None:
        self._chart, self._comparison = chart, None
        self.bar_chart.setVisible(False)
        self.line_chart.setVisible(True)
        choices = chart.choices
        self._select.blockSignals(True)
        self._select.clear()
        self._select.addItems(list(choices))
        self._select.blockSignals(False)
        self._select.setVisible(len(choices) > 1)
        self._select_label.setText("Show")
        self._select_label.setVisible(len(choices) > 1)
        self.line_chart.set_chart(chart, choices[0] if choices else None)
        self._refresh_views()

    def show_comparison(self, comparison: Comparison) -> None:
        self._comparison, self._chart = comparison, None
        self.line_chart.setVisible(False)
        self.bar_chart.setVisible(True)
        self.legend.set_entries([])
        self._select.blockSignals(True)
        self._select.clear()
        self._select.addItems(list(comparison.columns))
        self._select.blockSignals(False)
        self._select.setVisible(len(comparison.columns) > 1)
        self._select_label.setText("Compare by")
        self._select_label.setVisible(len(comparison.columns) > 1)
        self._refresh_views()

    @property
    def choice(self) -> str | None:
        return self._select.currentText() or None

    def select(self, choice: str) -> None:
        self._select.setCurrentText(choice)

    def _reselect(self, _: str) -> None:
        if self._chart is not None:
            self.line_chart.set_chart(self._chart, self.choice)
        self._refresh_views()

    def _flip(self, table_shown: bool) -> None:
        self._stack.setCurrentIndex(1 if table_shown else 0)
        self._toggle.setText("Chart" if table_shown else "Table")
        self._toggle.setAccessibleName(
            f"Show {self.title} as a {'chart' if table_shown else 'table'}"
        )

    def retheme(self) -> None:
        """The palette changed: lines take their colours when a chart is set, so set it again."""
        if self._chart is not None:
            self.line_chart.set_chart(self._chart, self.choice)
            self.legend.set_entries(self.line_chart.legend_entries())
        self.update()

    def table_shown(self) -> bool:
        return self._stack.currentIndex() == 1

    def set_table_shown(self, shown: bool) -> None:
        self._toggle.setChecked(shown)

    # ------------------------------------------------------------------ the views behind the chart

    def _refresh_views(self) -> None:
        notes: list[str] = []
        if self._chart is not None:
            self.legend.set_entries(self.line_chart.legend_entries())
            lines = self.line_chart.lines
            if lines:
                x = (
                    lines[0].x
                    if lines[0].x is not None
                    else tuple(float(i) for i in range(len(lines[0].y)))
                )
                columns = [self._chart.x_label, *[line.name for line in lines]]
                rows = [
                    [
                        _precise(x[i]),
                        *[_precise(line.y[i]) if i < len(line.y) else "" for line in lines],
                    ]
                    for i in range(len(x))
                ]
                self.table.set_rows(columns, rows, [True] * len(columns))
            drawn = len(lines[0].y) if lines else 0
            if self._chart.original_points > drawn > 0:
                notes.append(
                    f"Thinned for display: {drawn:,} of {self._chart.original_points:,} points are "
                    "drawn, and the table lists exactly those."
                )
            if self.line_chart.skipped_series:
                notes.append(
                    f"Showing the first 8 series; {self.line_chart.skipped_series} more are "
                    "left out (eight is the most the palette can tell apart)."
                )
        elif self._comparison is not None:
            column = self.choice or (
                self._comparison.columns[0] if self._comparison.columns else ""
            )
            position = (
                self._comparison.columns.index(column) if column in self._comparison.columns else 0
            )
            bars = [
                (name, values[position] if values else None)
                for name, values in self._comparison.rows
            ]
            self.bar_chart.set_data(self.title, bars, column)
            columns = ["Name", *self._comparison.columns]
            table_rows = [
                [name, *[format_value(v) for v in values]] for name, values in self._comparison.rows
            ]
            self.table.set_rows(
                columns, table_rows, [False, *[True] * len(self._comparison.columns)]
            )
        self._caption.setText("  ".join(notes))
        self._caption.setVisible(bool(notes))
