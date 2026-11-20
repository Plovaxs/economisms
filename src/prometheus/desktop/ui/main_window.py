"""The window: a permanent statement of what this is, a sidebar, the pages, and a status bar.

Two things are on screen on every page and cannot be hidden. The banner across the top says
*simulated data, research only* and shows the gate decision (NO-GO); and the status bar shows
whatever job is running, with a way to cancel it. The window polls the job queue a few times a
second (every 300 ms while something is queued or running, once a second when idle) and hands the
same snapshot to every page that cares, so two pages never disagree about a job's state.

Closing the window while a job is running asks first, because it will cancel the job: the child
process does not outlive the window.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QCloseEvent, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from prometheus.desktop import health
from prometheus.desktop.findings import FindingsDocument
from prometheus.desktop.runner import WorkerLoop
from prometheus.desktop.session import JobSummary, LocalSession
from prometheus.desktop.ui import theme
from prometheus.desktop.ui.pages.base import PageBase
from prometheus.desktop.ui.pages.explorers import ExplorersPage
from prometheus.desktop.ui.pages.findings import FindingsPage
from prometheus.desktop.ui.pages.history import HistoryPage
from prometheus.desktop.ui.pages.labs import LabsPage, format_elapsed
from prometheus.desktop.ui.pages.overview import OverviewPage
from prometheus.desktop.ui.pages.system import SystemPage
from prometheus.desktop.ui.widgets import Badge, ChartCard, make_label

PAGES = (
    ("overview", "Overview"),
    ("labs", "Labs"),
    ("explorers", "Explorers"),
    ("findings", "Findings"),
    ("history", "History"),
    ("system", "System"),
)
BUSY_MS = 300
IDLE_MS = 1000


class MainWindow(QMainWindow):
    def __init__(
        self,
        session: LocalSession,
        *,
        state_dir: Path,
        runner: WorkerLoop | None = None,
        theme_mode: str = "system",
        confirm_close: bool = True,
        findings_document: FindingsDocument | None = None,
    ) -> None:
        super().__init__()
        self.session, self.runner = session, runner
        self.theme_mode = theme_mode
        self._confirm_close = confirm_close
        self._summaries: tuple[JobSummary, ...] = ()
        self._closed = False
        self.setWindowTitle("ECONOSIM")
        self.setAccessibleName("ECONOSIM")
        root = QWidget()
        root.setObjectName("root")
        self.setCentralWidget(root)
        column = QVBoxLayout(root)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(0)
        column.addWidget(self._banner())
        middle = QHBoxLayout()
        middle.setContentsMargins(0, 0, 0, 0)
        middle.setSpacing(0)
        middle.addWidget(self._sidebar())

        self.pages: dict[str, PageBase] = {}
        self.stack = QStackedWidget()
        self.overview = OverviewPage(session)
        self.labs = LabsPage(session)
        self.explorers = ExplorersPage()
        self.findings = FindingsPage(findings_document)
        self.history = HistoryPage(session)
        self.system = SystemPage(session, state_dir)
        for key, page in (
            ("overview", self.overview),
            ("labs", self.labs),
            ("explorers", self.explorers),
            ("findings", self.findings),
            ("history", self.history),
            ("system", self.system),
        ):
            self.pages[key] = page
            self.stack.addWidget(page)
        middle.addWidget(self.stack, 1)
        column.addLayout(middle, 1)
        column.addWidget(self._status_bar())

        self.overview.navigate.connect(self.show_page)
        self.overview.openResult.connect(self.open_result)
        self.history.openResult.connect(self.open_result)
        self.history.rerun.connect(self.rerun)
        self.system.themeRequested.connect(self.set_theme)
        self.system.set_theme_selection(theme_mode)
        self.nav.currentRowChanged.connect(self._nav_changed)
        for number, (key, _) in enumerate(PAGES, start=1):
            shortcut = QShortcut(QKeySequence(f"Ctrl+{number}"), self)
            shortcut.activated.connect(lambda k=key: self.show_page(k))

        self.timer = QTimer(self)
        self.timer.setInterval(IDLE_MS)
        self.timer.timeout.connect(self.tick)
        self.timer.start()
        self.show_page("overview")

    # ------------------------------------------------------------------ the chrome

    def _banner(self) -> QFrame:
        frame = QFrame()
        frame.setObjectName("banner")
        row = QHBoxLayout(frame)
        row.setContentsMargins(16, 8, 16, 8)
        row.setSpacing(12)
        row.addWidget(Badge("research only", "warn"))
        self.banner_text = make_label(
            "Simulated data. Not financial advice and not a trading system.",
            "secondary",
            wrap=False,
        )
        row.addWidget(self.banner_text, 1)
        gate = health.gate_summary()
        self.gate_badge = Badge(f"{gate.decision}  ·  gate {gate.gate}", "bad")
        row.addWidget(self.gate_badge)
        details = QPushButton("Details")
        details.setProperty("ghost", True)
        details.setAccessibleName("Read the full statement of what this may be used for")
        details.clicked.connect(lambda: self.show_page("system"))
        row.addWidget(details)
        return frame

    def _sidebar(self) -> QFrame:
        frame = QFrame()
        frame.setObjectName("sidebar")
        frame.setFixedWidth(210)
        column = QVBoxLayout(frame)
        column.setContentsMargins(0, 16, 0, 12)
        column.setSpacing(2)
        brand = make_label("ECONOSIM", "brand", wrap=False)
        brand.setContentsMargins(18, 0, 0, 0)
        column.addWidget(brand)
        version = make_label(f"PROMETHEUS-X  ·  {health.app_version()}", "caption", wrap=False)
        version.setContentsMargins(18, 0, 0, 10)
        column.addWidget(version)
        self.nav = QListWidget()
        self.nav.setObjectName("nav")
        self.nav.setAccessibleName("Pages")
        self.nav.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        for number, (_, title) in enumerate(PAGES, start=1):
            item = QListWidgetItem(title)
            item.setToolTip(f"{title}  (Ctrl+{number})")
            self.nav.addItem(item)
        column.addWidget(self.nav, 1)
        return frame

    def _status_bar(self) -> QFrame:
        frame = QFrame()
        frame.setObjectName("statusbar")
        row = QHBoxLayout(frame)
        row.setContentsMargins(16, 6, 16, 6)
        row.setSpacing(12)
        self.job_label = make_label("No job running", "secondary", wrap=False)
        self.job_progress = QProgressBar()
        self.job_progress.setRange(0, 0)
        self.job_progress.setTextVisible(False)
        self.job_progress.setFixedWidth(120)
        self.job_progress.setVisible(False)
        self.job_cancel = QPushButton("Cancel job")
        self.job_cancel.setProperty("danger", True)
        self.job_cancel.setVisible(False)
        self.job_cancel.clicked.connect(self._cancel_live)
        self.worker_error = make_label("", "error", wrap=False)
        row.addWidget(self.job_label)
        row.addWidget(self.job_progress)
        row.addWidget(self.job_cancel)
        row.addStretch(1)
        row.addWidget(self.worker_error)
        return frame

    # ------------------------------------------------------------------ navigation

    def _nav_changed(self, row: int) -> None:
        if 0 <= row < len(PAGES):
            self.show_page(PAGES[row][0])

    def show_page(self, key: str) -> None:
        index = [k for k, _ in PAGES].index(key)
        self.nav.blockSignals(True)
        self.nav.setCurrentRow(index)
        self.nav.blockSignals(False)
        self.stack.setCurrentIndex(index)
        self.setWindowTitle(f"{PAGES[index][1]}  —  ECONOSIM")
        self.pages[key].activated()

    @property
    def current_page(self) -> str:
        return PAGES[self.stack.currentIndex()][0]

    def open_result(self, job_id: str) -> None:
        self.labs.open_job(job_id)
        self.show_page("labs")

    def rerun(self, job_id: str) -> None:
        self.labs.load_settings(job_id)
        self.show_page("labs")

    # ------------------------------------------------------------------ following the queue

    def live_jobs(self) -> list[JobSummary]:
        return [s for s in self._summaries if s.status in ("queued", "running")]

    def tick(self) -> None:
        """Take one look at the queue and tell every page about it."""
        if self._closed:
            return
        summaries: Sequence[JobSummary] = self.session.summaries(100)
        self._summaries = tuple(summaries)
        live = self.live_jobs()
        self.timer.setInterval(BUSY_MS if live or self.explorers.busy() else IDLE_MS)
        running = next((s for s in live if s.status == "running"), None)
        shown = running or (live[0] if live else None)
        if shown is None:
            self.job_label.setText("No job running")
        else:
            waiting = len(live) - 1
            more = f"  ·  {waiting} more waiting" if waiting else ""
            state = "running" if shown.status == "running" else "waiting for the worker"
            self.job_label.setText(
                f"{shown.title} {state}  ·  {format_elapsed(shown.elapsed_seconds)}{more}"
            )
        self.job_progress.setVisible(shown is not None)
        self.job_cancel.setVisible(shown is not None)
        self.job_cancel.setEnabled(shown is not None and not shown.cancel_requested)
        error = self.runner.last_error if self.runner is not None else None
        self.worker_error.setText(f"✕  Worker: {error}" if error else "")
        self.labs.update_jobs(summaries)
        self.history.update_jobs(summaries)
        self.overview.update_jobs(summaries)

    def _cancel_live(self) -> None:
        for summary in self.live_jobs():
            if summary.status == "running" or summary is self.live_jobs()[0]:
                self.session.cancel(summary.job_id)
                break

    # ------------------------------------------------------------------ appearance

    def set_theme(self, mode: str) -> None:
        app = QApplication.instance()
        if not isinstance(app, QApplication):
            return
        self.theme_mode = mode
        theme.apply_theme(app, mode)
        for card in self.findChildren(ChartCard):
            card.retheme()
        self.system.set_theme_selection(mode)
        self.update()

    # ------------------------------------------------------------------ closing

    def shutdown(self) -> None:
        """Stop everything that runs behind the window; safe to call more than once."""
        self._closed = True
        self.timer.stop()
        self.explorers.shutdown()
        if self.runner is not None:
            self.runner.stop()

    def closeEvent(self, event: QCloseEvent) -> None:
        if self.live_jobs() and self._confirm_close:
            answer = QMessageBox.question(
                self,
                "A job is still running",
                "Closing the window will cancel the job that is running. Close anyway?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                event.ignore()
                return
        self.shutdown()
        event.accept()
