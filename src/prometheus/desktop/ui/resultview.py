"""One run's result, laid out for reading.

The tabs follow how a result is read: an *Overview* (the headline numbers, any model comparison as
bars, the first charts, the small summary tables), then *Charts* and *Tables* for everything, then
*Details* (the limitations the run itself reported, long descriptive text, the exact configuration
and provenance) and the *Raw* payload. A tab with nothing in it is hidden rather than shown empty.

Three things are never left out. A run that reported itself invalid says so at the top, in words,
with its reasons. The limitations the run listed sit one tab away and are counted on the tab, so
they are not mistaken for decoration. And the disclaimer the artifact itself carries is printed
under the tabs, verbatim.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QGridLayout,
    QHBoxLayout,
    QPushButton,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from prometheus.desktop.results import ResultView, Table
from prometheus.desktop.ui.widgets import (
    Badge,
    Card,
    ChartCard,
    DataTable,
    JsonTree,
    MetricTile,
    key_value_table,
    make_label,
    save_text,
    scrollable,
)

TILE_COLUMNS = 3
OVERVIEW_CHARTS = 2


def _page() -> tuple[QWidget, QVBoxLayout]:
    page = QWidget()
    page.setProperty("page", True)
    layout = QVBoxLayout(page)
    layout.setContentsMargins(0, 14, 6, 14)
    layout.setSpacing(14)
    return page, layout


class ResultWidget(QWidget):
    """Shows a `ResultView`; knows nothing about where it came from."""

    exportRequested = Signal()
    rerunRequested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._view: ResultView | None = None
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(8)
        self._title = make_label("", "h2", wrap=False)  # kept for the accessible name, not shown
        self._title.setVisible(False)
        self.verdict = Badge("", "accent")
        self.verdict.setVisible(False)
        self.rerun_button = QPushButton("Re-run")
        self.rerun_button.setToolTip("Put these settings back in the form to run again")
        self.rerun_button.setAccessibleName("Re-run with these settings")
        self.rerun_button.setProperty("ghost", True)
        self.rerun_button.clicked.connect(self.rerunRequested)
        self.export_button = QPushButton("Export…")
        self.export_button.setToolTip("Save the verified result as a JSON file")
        self.export_button.setAccessibleName("Export the verified result as JSON")
        self.export_button.setProperty("ghost", True)
        self.export_button.clicked.connect(self.exportRequested)
        self.copy_button = QPushButton("Copy hash")
        self.copy_button.setToolTip("Copy this result's hash to the clipboard")
        self.copy_button.setAccessibleName("Copy the result hash")
        self.copy_button.setProperty("ghost", True)
        self.copy_button.clicked.connect(self._copy_hash)
        corner = QWidget()
        corner_row = QHBoxLayout(corner)
        corner_row.setContentsMargins(0, 0, 0, 0)
        corner_row.setSpacing(6)
        corner_row.addWidget(self.verdict)
        for button in (self.rerun_button, self.export_button, self.copy_button):
            corner_row.addWidget(button)
        self.invalid_card = Card()
        self.invalid_card.setProperty("invalid", True)
        self._invalid_text = make_label("", "secondary")
        self.invalid_card.body.addWidget(
            Badge("This run reported its own result as invalid", "fail")
        )
        self.invalid_card.body.addWidget(self._invalid_text)
        self.invalid_card.setVisible(False)
        outer.addWidget(self.invalid_card)
        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        self.tabs.setAccessibleName("Result sections")
        self.tabs.setCornerWidget(corner, Qt.Corner.TopRightCorner)
        outer.addWidget(self.tabs, 1)
        self._disclaimer = make_label("", "caption")
        self._disclaimer.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        outer.addWidget(self._disclaimer)
        self.raw = JsonTree()
        self.chart_cards: list[ChartCard] = []
        self.tables: list[DataTable] = []
        self.tiles: list[MetricTile] = []
        self.set_actions(rerun=False, export=False)

    # ------------------------------------------------------------------ using

    @property
    def view(self) -> ResultView | None:
        return self._view

    def set_actions(self, *, rerun: bool, export: bool) -> None:
        self.rerun_button.setVisible(rerun)
        self.export_button.setVisible(export)

    def clear(self) -> None:
        self._view = None
        self.tabs.clear()
        self.chart_cards, self.tables, self.tiles = [], [], []
        self._title.setText("")
        self.verdict.setVisible(False)
        self.invalid_card.setVisible(False)
        self._disclaimer.setText("")

    def tab_titles(self) -> list[str]:
        return [self.tabs.tabText(i) for i in range(self.tabs.count()) if self.tabs.isTabVisible(i)]

    def _copy_hash(self) -> None:
        if self._view is None:
            return
        facts = dict(self._view.provenance)
        QGuiApplication.clipboard().setText(
            facts.get("Result hash") or facts.get("Artifact SHA-256", "")
        )

    # ------------------------------------------------------------------ building

    def set_view(self, view: ResultView) -> None:
        self.clear()
        self._view = view
        self._title.setText(view.title)
        self._title.setAccessibleName(f"Result: {view.title}")
        if view.verdict:
            self.verdict.set_status("accent", view.verdict.replace("_", " "))
            self.verdict.setVisible(True)
        if view.invalid:
            reasons = [
                reason
                for label, items in view.notes
                if label == "Invalid reasons"
                for reason in items
            ]
            self._invalid_text.setText(
                "; ".join(reasons) if reasons else "The result is kept so you can see why."
            )
            self.invalid_card.setVisible(True)
        self.tabs.addTab(self._overview(view), "Overview")
        self.tabs.addTab(self._charts(view), "Charts")
        self.tabs.addTab(self._tables(view), "Tables")
        limits = sum(len(items) for label, items in view.notes if label == "Limitations")
        self.tabs.addTab(
            self._details(view), f"Details · {limits} limitations" if limits else "Details"
        )
        self.raw.set_payload(view.payload)
        self.tabs.addTab(self.raw, "Raw")
        self.tabs.setTabVisible(1, bool(view.charts))
        self.tabs.setTabVisible(2, bool(view.tables))
        # a result that is mostly a picture (an explorer: no verdict, no model comparison) opens on
        # its charts; one that is a verdict and a comparison opens on its overview
        chart_first = bool(view.charts) and not view.comparisons and not view.verdict
        self.tabs.setCurrentIndex(1 if chart_first else 0)
        self.copy_button.setVisible(bool(view.provenance))
        self._disclaimer.setText(view.disclaimer)
        self._disclaimer.setVisible(bool(view.disclaimer))

    def _overview(self, view: ResultView) -> QWidget:
        page, layout = _page()
        if view.metrics:
            grid = QGridLayout()
            grid.setSpacing(10)
            for column in range(TILE_COLUMNS):
                grid.setColumnStretch(column, 1)
            for position, metric in enumerate(view.metrics):
                tile = MetricTile(metric.label, metric.value)
                self.tiles.append(tile)
                grid.addWidget(tile, position // TILE_COLUMNS, position % TILE_COLUMNS)
            layout.addLayout(grid)
        for comparison in view.comparisons:
            card = ChartCard(comparison.title)
            card.show_comparison(comparison)
            self.chart_cards.append(card)
            layout.addWidget(card)
        for chart in view.charts[:OVERVIEW_CHARTS]:
            card = ChartCard(chart.title)
            card.show_chart(chart)
            self.chart_cards.append(card)
            layout.addWidget(card)
        sections = QGridLayout()
        sections.setSpacing(12)
        sections.setColumnStretch(0, 1)
        sections.setColumnStretch(1, 1)
        for position, section in enumerate(view.sections):
            box = Card()
            box.body.addWidget(make_label(section.title, "h3"))
            table = key_value_table(section.title, section.items)
            table.setMinimumHeight(len(section.items) * 28 + 36)
            table.setMaximumHeight(len(section.items) * 28 + 40)
            box.body.addWidget(table)
            if section.truncated:
                box.body.addWidget(make_label(f"{section.truncated} more not shown.", "caption"))
            sections.addWidget(box, position // 2, position % 2)
        layout.addLayout(sections)
        if not (view.metrics or view.comparisons or view.charts or view.sections):
            layout.addWidget(
                make_label("This result has no headline numbers; see the other tabs.", "secondary")
            )
        layout.addStretch(1)
        return scrollable(page)

    def _charts(self, view: ResultView) -> QWidget:
        page, layout = _page()
        for chart in view.charts:
            card = ChartCard(chart.title)
            card.show_chart(chart)
            self.chart_cards.append(card)
            layout.addWidget(card)
        layout.addStretch(1)
        return scrollable(page)

    def _tables(self, view: ResultView) -> QWidget:
        page, layout = _page()
        for table in view.tables:
            card = Card()
            head = QHBoxLayout()
            head.addWidget(make_label(table.title, "h3", wrap=False), 1)
            export = QPushButton("Export CSV…")
            export.setProperty("ghost", True)
            head.addWidget(export)
            card.body.addLayout(head)
            widget = DataTable(table.title)
            widget.set_table(table)
            self.tables.append(widget)
            export.clicked.connect(lambda _=False, w=widget, t=table: self._export_csv(w, t))
            card.body.addWidget(widget)
            if table.truncated:
                card.body.addWidget(
                    make_label(
                        f"Showing the first {len(table.rows):,} rows; {table.truncated:,} more are "
                        "in the Raw tab.",
                        "caption",
                    )
                )
            layout.addWidget(card)
        layout.addStretch(1)
        return scrollable(page)

    def _export_csv(self, widget: DataTable, table: Table) -> None:
        name = "".join(c if c.isalnum() else "_" for c in table.title.lower()) + ".csv"
        save_text(self, name, widget.to_csv(), "CSV files (*.csv)")

    def _details(self, view: ResultView) -> QWidget:
        page, layout = _page()
        for label, items in view.notes:
            card = Card()
            card.body.addWidget(make_label(label, "h3"))
            for item in items:
                card.body.addWidget(make_label(f"•  {item}", "secondary", selectable=True))
            layout.addWidget(card)
        for label, text in view.details:
            card = Card()
            card.body.addWidget(make_label(label, "h3"))
            card.body.addWidget(make_label(text, "secondary", selectable=True))
            layout.addWidget(card)
        if view.configuration:
            card = Card()
            card.body.addWidget(make_label("Configuration this run used", "h3"))
            table = key_value_table("Configuration", view.configuration)
            table.setMinimumHeight(min(len(view.configuration), 14) * 28 + 36)
            card.body.addWidget(table)
            layout.addWidget(card)
        if view.provenance:
            card = Card()
            card.body.addWidget(
                make_label("Provenance: exactly which run, code and environment", "h3")
            )
            table = key_value_table("Provenance", view.provenance)
            table.setMinimumHeight(min(len(view.provenance), 14) * 28 + 36)
            card.body.addWidget(table)
            layout.addWidget(card)
        layout.addStretch(1)
        return scrollable(page)
