"""The first page: what this is, what it is not, and where things stand."""

from __future__ import annotations

from collections.abc import Sequence

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QGridLayout,
    QHBoxLayout,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from prometheus.desktop import findings, health
from prometheus.desktop.session import JobSummary, LocalSession
from prometheus.desktop.ui.pages.base import PageBase
from prometheus.desktop.ui.pages.labs import format_elapsed
from prometheus.desktop.ui.widgets import (
    Badge,
    Card,
    MetricTile,
    clear_layout,
    make_label,
    scrollable,
)

RECENT = 5


class OverviewPage(PageBase):
    navigate = Signal(str)
    openResult = Signal(str)

    def __init__(self, session: LocalSession, parent: QWidget | None = None) -> None:
        super().__init__(
            "ECONOSIM / PROMETHEUS-X",
            "Deep learning for quantitative economics and neural finance: classical "
            "econometrics, deep learning and hybrid quantum models benchmarked side by side on "
            "real computed output.",
            parent,
        )
        self.session = session
        holder = QWidget()
        holder.setProperty("page", True)
        column = QVBoxLayout(holder)
        column.setContentsMargins(0, 0, 8, 12)
        column.setSpacing(14)
        self.content.addWidget(scrollable(holder), 1)

        self.gate_card = Card()
        gate_row = QHBoxLayout()
        self.gate_badge = Badge("", "bad")
        gate_row.addWidget(self.gate_badge)
        gate_row.addWidget(make_label("Not for production, trading or advice.", "h3", wrap=False))
        gate_row.addStretch(1)
        self.gate_card.body.addLayout(gate_row)
        self.gate_text = make_label("", "secondary")
        self.gate_card.body.addWidget(self.gate_text)
        read = QPushButton("Read the full statement")
        read.setProperty("ghost", True)
        read.clicked.connect(lambda: self.navigate.emit("system"))
        self.gate_card.body.addWidget(read, 0, Qt.AlignmentFlag.AlignLeft)
        column.addWidget(self.gate_card)

        tiles = QGridLayout()
        tiles.setSpacing(10)
        self.health_tile = MetricTile("This installation", "…")
        self.data_tile = MetricTile("Data snapshots", "…")
        self.jobs_tile = MetricTile("Jobs run here", "…")
        self.findings_tile = MetricTile("Findings recorded", "…")
        for position, tile in enumerate(
            (self.health_tile, self.data_tile, self.jobs_tile, self.findings_tile)
        ):
            tiles.addWidget(tile, 0, position)
            tiles.setColumnStretch(position, 1)
        column.addLayout(tiles)

        actions = Card()
        actions.body.addWidget(make_label("Start here", "h2"))
        row = QHBoxLayout()
        self.action_buttons: dict[str, QPushButton] = {}
        for key, text, hint in (
            ("labs", "Run a lab", "Train and compare models, run simulations and studies."),
            ("explorers", "Open the explorers", "Prices, paths, hedge ratios and portfolio risk."),
            ("findings", "Read the findings", "What was found, including what did not hold up."),
        ):
            box = QVBoxLayout()
            button = QPushButton(text)
            button.setProperty("primary", key == "labs")
            button.clicked.connect(lambda _=False, k=key: self.navigate.emit(k))
            self.action_buttons[key] = button
            box.addWidget(button)
            box.addWidget(make_label(hint, "caption"))
            row.addLayout(box, 1)
        actions.body.addLayout(row)
        column.addWidget(actions)

        self.recent_card = Card()
        self.recent_card.body.addWidget(make_label("Recent runs", "h2"))
        self.recent_box = QVBoxLayout()
        self.recent_box.setSpacing(6)
        self.recent_card.body.addLayout(self.recent_box)
        column.addWidget(self.recent_card)
        column.addStretch(1)
        self._recent_signature: tuple[object, ...] | None = None  # None: nothing drawn yet
        self.refresh()

    # ------------------------------------------------------------------ updating

    def activated(self) -> None:
        self.refresh()

    def refresh(self) -> None:
        report = health.collect_health(state_dir=self.session.root)
        self.gate_badge.set_status("bad", f"{report.gate.decision}  ·  gate {report.gate.gate}")
        self.gate_text.setText(report.disclaimer)
        if report.ok and not report.warnings:
            self.health_tile.set_value("All clear")
        else:
            self.health_tile.set_value(f"{report.failures} failing, {report.warnings} warning(s)")
        verified = sum(1 for f in report.data_files if f.status == "ok")
        self.data_tile.set_value(f"{verified} of {len(report.data_files)} verified")
        document = findings.load()
        self.findings_tile.set_value(str(len(document.findings)) if document.available else "—")
        self.update_jobs(self.session.summaries(RECENT * 4))

    def update_jobs(self, summaries: Sequence[JobSummary]) -> None:
        counts: dict[str, int] = {}
        for summary in summaries:
            counts[summary.status] = counts.get(summary.status, 0) + 1
        live = counts.get("running", 0) + counts.get("queued", 0)
        total = len(summaries)
        self.jobs_tile.set_value(f"{total}" + (f"  ({live} active)" if live else ""))
        recent = list(summaries[:RECENT])
        signature = tuple((s.job_id, s.status, s.has_result) for s in recent)
        if signature == self._recent_signature:
            return
        self._recent_signature = signature
        clear_layout(self.recent_box)
        if not recent:
            self.recent_box.addWidget(
                make_label("Nothing has been run yet. Open a lab and press Run.", "secondary")
            )
            return
        for summary in recent:
            row = QHBoxLayout()
            row.addWidget(Badge(summary.status.replace("_", " "), summary.status))
            row.addWidget(make_label(summary.title, "h3", wrap=False))
            row.addWidget(
                make_label(
                    f"{summary.created:%Y-%m-%d %H:%M}  ·  "
                    f"{format_elapsed(summary.elapsed_seconds)}",
                    "secondary",
                    wrap=False,
                )
            )
            row.addStretch(1)
            if summary.has_result:
                open_button = QPushButton("Open result")
                open_button.setProperty("ghost", True)
                open_button.clicked.connect(
                    lambda _=False, job=summary.job_id: self.openResult.emit(job)
                )
                row.addWidget(open_button)
            self.recent_box.addLayout(row)
