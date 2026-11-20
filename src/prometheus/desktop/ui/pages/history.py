"""Every job that has run on this machine, newest first.

A job is never deleted from here: the queue's event log is append-only and hash-chained, and this
page offers to recompute that chain. What a person can do with a row is open its verified result,
load its settings back into the lab to run it again, cancel it if it is still going, or export the
result.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QFileDialog, QHBoxLayout, QPushButton, QWidget

from prometheus.desktop.results import format_value
from prometheus.desktop.session import JobSummary, LocalSession, ResultUnavailableError
from prometheus.desktop.ui.pages.base import PageBase
from prometheus.desktop.ui.pages.labs import format_elapsed
from prometheus.desktop.ui.widgets import Badge, Card, DataTable, make_label

COLUMNS = ["Started", "Lab", "Status", "Duration", "Result"]
GLYPHS = {
    "succeeded": "✓",
    "failed": "✕",
    "running": "●",
    "queued": "…",
    "cancelled": "–",
    "timed_out": "!",
}


class HistoryPage(PageBase):
    openResult = Signal(str)
    rerun = Signal(str)

    def __init__(self, session: LocalSession, parent: QWidget | None = None) -> None:
        super().__init__(
            "History",
            "Every job that has run here, newest first. Results are verified again each time "
            "they are opened.",
            parent,
        )
        self.session = session
        self.selected_id: str | None = None
        self._ids: list[str] = []
        self._signature: tuple[object, ...] = ()
        self._summaries: dict[str, JobSummary] = {}

        top = QHBoxLayout()
        self.audit_button = QPushButton("Verify audit chain")
        self.audit_button.setToolTip(
            "Recompute the hash chain over every job event; a rewritten or removed event breaks it."
        )
        self.audit_text = make_label("", "secondary")
        top.addWidget(self.audit_button)
        top.addWidget(self.audit_text, 1)
        self.content.addLayout(top)
        self.table = DataTable("Job history")
        self.table.setSelectionBehavior(DataTable.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(DataTable.SelectionMode.SingleSelection)
        self.content.addWidget(self.table, 1)
        self.empty = make_label("No jobs yet. Run a lab and it will appear here.", "secondary")
        self.content.addWidget(self.empty)

        self.detail = Card()
        head = QHBoxLayout()
        self.detail_title = make_label("Select a job", "h3", wrap=False)
        self.detail_badge = Badge("", "neutral")
        self.detail_badge.setVisible(False)
        head.addWidget(self.detail_title)
        head.addWidget(self.detail_badge)
        head.addStretch(1)
        self.detail.body.addLayout(head)
        self.detail_text = make_label("", "secondary", selectable=True)
        self.detail.body.addWidget(self.detail_text)
        buttons = QHBoxLayout()
        self.open_button = QPushButton("Open result")
        self.open_button.setProperty("primary", True)
        self.rerun_button = QPushButton("Re-run with these settings")
        self.cancel_button = QPushButton("Cancel job")
        self.cancel_button.setProperty("danger", True)
        self.export_button = QPushButton("Export JSON…")
        for button in (self.open_button, self.rerun_button, self.cancel_button, self.export_button):
            button.setEnabled(False)
            buttons.addWidget(button)
        buttons.addStretch(1)
        self.detail.body.addLayout(buttons)
        self.content.addWidget(self.detail)

        self.table.itemSelectionChanged.connect(self._selection_changed)
        self.table.itemDoubleClicked.connect(lambda _: self._open())
        self.audit_button.clicked.connect(self.verify_audit)
        self.open_button.clicked.connect(self._open)
        self.rerun_button.clicked.connect(self._rerun)
        self.cancel_button.clicked.connect(self._cancel)
        self.export_button.clicked.connect(self._export)
        self.refresh(session.summaries())

    # ------------------------------------------------------------------ the table

    def activated(self) -> None:
        self.refresh(self.session.summaries())

    def update_jobs(self, summaries: Sequence[JobSummary]) -> None:
        if self.isVisible():
            self.refresh(summaries)

    def refresh(self, summaries: Sequence[JobSummary]) -> None:
        self._summaries = {s.job_id: s for s in summaries}
        signature = tuple((s.job_id, s.status, s.has_result, s.cancel_requested) for s in summaries)
        if signature != self._signature:
            self._signature = signature
            self._rebuild(summaries)
        else:
            self._tick(summaries)
        self.empty.setVisible(not summaries)
        self.table.setVisible(bool(summaries))
        self._update_detail()

    def _row(self, s: JobSummary) -> list[str]:
        return [
            s.created.strftime("%Y-%m-%d %H:%M:%S"),
            s.title,
            f"{GLYPHS.get(s.status, '•')}  {s.status.replace('_', ' ')}",
            format_elapsed(s.elapsed_seconds),
            "verified result" if s.has_result else (s.error or "—"),
        ]

    def _rebuild(self, summaries: Sequence[JobSummary]) -> None:
        self.table.blockSignals(True)
        self.table.set_rows(COLUMNS, [self._row(s) for s in summaries], sortable=False)
        self._ids = [s.job_id for s in summaries]
        for row, job_id in enumerate(self._ids):
            item = self.table.item(row, 0)
            if item is not None:
                item.setData(Qt.ItemDataRole.UserRole, job_id)
        self.table.blockSignals(False)
        if self.selected_id in self._ids:
            self.table.selectRow(self._ids.index(self.selected_id))
        else:
            self.selected_id = None

    def _tick(self, summaries: Sequence[JobSummary]) -> None:
        for row, summary in enumerate(summaries):
            if not summary.finished and row < self.table.rowCount():
                item = self.table.item(row, 3)
                if item is not None:
                    item.setText(format_elapsed(summary.elapsed_seconds))

    def job_ids(self) -> list[str]:
        return list(self._ids)

    def select(self, job_id: str) -> None:
        self.table.selectRow(self._ids.index(job_id))

    # ------------------------------------------------------------------ the selected job

    def _selection_changed(self) -> None:
        rows = {index.row() for index in self.table.selectedIndexes()}
        self.selected_id = self._ids[min(rows)] if rows and min(rows) < len(self._ids) else None
        self._update_detail()

    def _update_detail(self) -> None:
        summary = self._summaries.get(self.selected_id or "")
        for button in (self.open_button, self.rerun_button, self.cancel_button, self.export_button):
            button.setEnabled(False)
        if summary is None:
            self.detail_title.setText("Select a job")
            self.detail_badge.setVisible(False)
            self.detail_text.setText("")
            return
        self.detail_title.setText(f"{summary.title}  ·  {summary.short_id}")
        self.detail_badge.set_status(summary.status, summary.status.replace("_", " "))
        self.detail_badge.setVisible(True)
        lines = [
            f"Job {summary.job_id}",
            f"Started {summary.created:%Y-%m-%d %H:%M:%S}  ·  "
            f"{format_elapsed(summary.elapsed_seconds)}  ·  attempt {summary.attempts}",
        ]
        if summary.error:
            lines.append(summary.error)
        self.detail_text.setText("\n".join(lines))
        self.open_button.setEnabled(summary.has_result)
        self.export_button.setEnabled(summary.has_result)
        self.rerun_button.setEnabled(True)
        self.cancel_button.setEnabled(not summary.finished and not summary.cancel_requested)

    def _open(self) -> None:
        if self.selected_id and self._summaries[self.selected_id].has_result:
            self.openResult.emit(self.selected_id)

    def _rerun(self) -> None:
        if self.selected_id:
            self.rerun.emit(self.selected_id)

    def _cancel(self) -> None:
        if self.selected_id:
            self.session.cancel(self.selected_id)

    def _export(self) -> None:
        if not self.selected_id:
            return
        chosen, _ = QFileDialog.getSaveFileName(
            self,
            "Export the verified result",
            f"{self._summaries[self.selected_id].kind}-{self.selected_id[:8]}.json",
            "JSON (*.json)",
        )
        if chosen:
            try:
                self.session.export_result(self.selected_id, Path(chosen))
            except (OSError, ResultUnavailableError) as exc:
                self.audit_text.setText(f"✕  {exc}")
            else:
                self.audit_text.setText(f"✓  Exported to {chosen}")

    def verify_audit(self) -> bool:
        try:
            head = self.session.audit_head()
        except ValueError as exc:
            self.audit_text.setText(f"✕  The audit chain is broken: {exc}")
            return False
        count = len(self._ids)
        self.audit_text.setText(
            f"✓  The audit chain of {format_value(count)} job(s) verifies. Head {head[:16]}…"
        )
        return True
