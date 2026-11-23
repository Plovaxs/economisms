"""The system page: the standing of the project, the health of this installation, the data.

It answers three questions a reader should be able to ask of any research tool. *What is this
allowed to be used for?* (the gate decision and the disclaimer, stated plainly and unchanged.)
*Is this installation the one the results came from?* (the preflight checks and the verified data
manifest.) *Where does my work live?* (the state directory, and a way to recompute the audit
chain.) It also holds the two small settings the application has: the colour theme and whether it
appears in the application menu.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QComboBox,
    QGridLayout,
    QHBoxLayout,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from prometheus.desktop import health, launcher
from prometheus.desktop.session import LocalSession
from prometheus.desktop.ui.pages.base import PageBase
from prometheus.desktop.ui.theme import MODES
from prometheus.desktop.ui.widgets import (
    Badge,
    Card,
    DataTable,
    clear_layout,
    key_value_table,
    make_label,
    scrollable,
)


def _megabytes(size: int) -> str:
    return f"{size / 1_000_000:.2f} MB" if size >= 1000 else f"{size} B"


class SystemPage(PageBase):
    themeRequested = Signal(str)

    def __init__(
        self, session: LocalSession, state_dir: Path, parent: QWidget | None = None
    ) -> None:
        super().__init__(
            "System",
            "What this is allowed to be used for, whether this installation matches the one the "
            "results came from, and where your work is kept.",
            parent,
        )
        self.session = session
        self.state_dir = state_dir
        self.report: health.HealthReport | None = None
        holder = QWidget()
        holder.setProperty("page", True)
        self.column = QVBoxLayout(holder)
        self.column.setContentsMargins(0, 0, 8, 12)
        self.column.setSpacing(14)
        self.content.addWidget(scrollable(holder), 1)
        self.cards: dict[str, Card] = {}
        self.refresh()

    def activated(self) -> None:
        self.refresh()

    # ------------------------------------------------------------------ building

    def _clear(self) -> None:
        clear_layout(self.column)
        self.cards = {}

    def _card(self, key: str, title: str) -> Card:
        card = Card()
        card.body.addWidget(make_label(title, "h2"))
        self.cards[key] = card
        self.column.addWidget(card)
        return card

    def refresh(self) -> None:
        report = health.collect_health(state_dir=self.state_dir)
        self.report = report
        self._clear()
        self._gate(report)
        self._checks(report)
        self._data(report)
        self._storage()
        self._settings(report)
        self.column.addStretch(1)

    def _gate(self, report: health.HealthReport) -> None:
        card = self._card("gate", "Standing of the project")
        row = QHBoxLayout()
        self.gate_badge = Badge(f"{report.gate.decision}  ·  gate {report.gate.gate}", "bad")
        row.addWidget(self.gate_badge)
        row.addWidget(make_label(f"decided {report.gate.decided_at}", "secondary", wrap=False))
        row.addStretch(1)
        card.body.addLayout(row)
        card.body.addWidget(make_label(report.disclaimer, "secondary", selectable=True))
        card.body.addWidget(make_label("Not part of this project, by decision", "h3"))
        for item in report.gate.scope_prohibited:
            card.body.addWidget(make_label(f"•  {item}", "secondary", selectable=True))
        card.body.addWidget(make_label("Open findings against the gate", "h3"))
        for item in report.gate.open_findings:
            card.body.addWidget(make_label(f"•  {item}", "secondary", selectable=True))

    def _checks(self, report: health.HealthReport) -> None:
        card = self._card("checks", "Preflight checks")
        summary = (
            "All clear."
            if report.ok and not report.warnings
            else f"{report.failures} failing, {report.warnings} warning(s)."
        )
        card.body.addWidget(make_label(summary, "secondary"))
        grid = QGridLayout()
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(8)
        for row, check in enumerate(report.checks):
            grid.addWidget(Badge(check.status, check.status), row, 0)
            grid.addWidget(make_label(check.name.replace("_", " "), "h3", wrap=False), row, 1)
            grid.addWidget(make_label(check.detail, "secondary", selectable=True), row, 2)
        grid.setColumnStretch(2, 1)
        card.body.addLayout(grid)

    def _data(self, report: health.HealthReport) -> None:
        card = self._card("data", f"Data snapshots ({len(report.data_files)} files)")
        table = DataTable("Data snapshots")
        table.set_rows(
            ["File", "Size", "Status", "SHA-256"],
            [
                [f.name, _megabytes(f.size), f.status, f.sha256[:16] + "…" if f.sha256 else "—"]
                for f in report.data_files
            ],
            [False, True, False, False],
        )
        card.body.addWidget(table)
        self.data_table = table

    def _storage(self) -> None:
        card = self._card("storage", "Where your work is kept")
        counts = self.session.counts()
        jobs = ", ".join(f"{n} {status.replace('_', ' ')}" for status, n in sorted(counts.items()))
        items = [
            ("State directory", str(self.session.root)),
            ("Job database", str(self.session.root / "jobs.sqlite3")),
            ("Results stored", _megabytes(self.session.storage_bytes())),
            ("Jobs", jobs or "none yet"),
            ("Isolated job worker", "available" if self.session.can_run_jobs else "needs Linux"),
        ]
        card.body.addWidget(key_value_table("Storage", items))

    def _settings(self, report: health.HealthReport) -> None:
        card = self._card("settings", "Settings and environment")
        row = QHBoxLayout()
        row.addWidget(make_label("Colour theme", "h3", wrap=False))
        self.theme_box = QComboBox()
        self.theme_box.addItems([mode.capitalize() for mode in MODES])
        self.theme_box.setAccessibleName("Colour theme")
        self.theme_box.currentTextChanged.connect(self._theme_chosen)
        row.addWidget(self.theme_box)
        row.addSpacing(24)
        self.install_button = QPushButton("Add to the application menu")
        self.remove_button = QPushButton("Remove from the menu")
        self.install_button.clicked.connect(self._install)
        self.remove_button.clicked.connect(self._remove)
        row.addWidget(self.install_button)
        row.addWidget(self.remove_button)
        row.addStretch(1)
        card.body.addLayout(row)
        self.launcher_text = make_label("", "secondary", selectable=True)
        card.body.addWidget(self.launcher_text)
        card.body.addWidget(key_value_table("Environment", report.environment))

    def set_theme_selection(self, mode: str) -> None:
        self.theme_box.blockSignals(True)
        self.theme_box.setCurrentText(mode.capitalize())
        self.theme_box.blockSignals(False)

    # ------------------------------------------------------------------ the menu entry

    def _theme_chosen(self, text: str) -> None:
        self.themeRequested.emit(text.lower())

    def _install(self) -> None:
        try:
            entry, _ = launcher.install_launcher()
        except OSError as exc:
            self.launcher_text.setText(f"✕  {exc}")
        else:
            self.launcher_text.setText(f"✓  Added: {entry}")

    def _remove(self) -> None:
        removed = launcher.uninstall_launcher()
        self.launcher_text.setText(
            "✓  Removed: " + ", ".join(str(p) for p in removed) if removed else "Nothing to remove."
        )
