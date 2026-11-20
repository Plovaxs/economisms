"""The labs: pick a runner, set its parameters, run it as an isolated job, read the result.

Everything a lab does goes through `LocalSession`: the form is built from the runner's own config
type, `assemble` and `prepare_recipe` judge it exactly as a submission would be judged, the job runs
in a child process with its limits, and the result is read back through its hash verification. The
page itself only draws state and relays two intentions, run and cancel.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Any

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QListWidget,
    QListWidgetItem,
    QProgressBar,
    QPushButton,
    QStackedWidget,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from prometheus.desktop import catalog, forms
from prometheus.desktop.results import ResultView
from prometheus.desktop.session import (
    JobSummary,
    LocalSession,
    ResultUnavailableError,
    admission_summary,
    summarize,
)
from prometheus.desktop.ui.formview import FormView
from prometheus.desktop.ui.pages.base import PageBase
from prometheus.desktop.ui.resultview import ResultWidget
from prometheus.desktop.ui.widgets import Badge, Card, make_label, scrollable

VALIDATE_DELAY_MS = 350
NO_WORKER = "Running jobs needs Linux process controls; this platform cannot run them."


def format_elapsed(seconds: float) -> str:
    whole = int(seconds)
    return f"{whole // 60:02d}:{whole % 60:02d}"


class LabsPage(PageBase):
    resultOpened = Signal(str)

    def __init__(self, session: LocalSession, parent: QWidget | None = None) -> None:
        super().__init__(
            "Labs",
            "Train and compare models, run simulations and studies. Each run is an isolated job "
            "with hard limits; its result is verified when it is read back.",
            parent,
        )
        self.session = session
        self.current_kind = ""
        self._forms: dict[str, FormView] = {}
        self._job_for_kind: dict[str, str] = {}
        self._views: dict[str, ResultView] = {}
        self._shown: set[str] = set()
        self._latest: dict[str, JobSummary] = {}

        body = QHBoxLayout()
        body.setSpacing(16)
        self.list = QListWidget()
        self.list.setObjectName("list")
        self.list.setAccessibleName("Labs")
        self.list.setFixedWidth(250)
        self.list.setTextElideMode(Qt.TextElideMode.ElideRight)
        body.addWidget(self.list)
        self._populate_list()

        right = QVBoxLayout()
        right.setSpacing(12)
        title_row = QHBoxLayout()
        self.kind_title = make_label("", "h2", wrap=False)
        self.group_badge = Badge("", "neutral")
        self.network_badge = Badge("uses the network", "warn")
        title_row.addWidget(self.kind_title)
        title_row.addWidget(self.group_badge)
        title_row.addWidget(self.network_badge)
        title_row.addStretch(1)
        right.addLayout(title_row)
        self.kind_summary = make_label("", "secondary")
        right.addWidget(self.kind_summary)

        run_card = Card()
        run_row = QHBoxLayout()
        run_row.setSpacing(10)
        self.run_button = QPushButton("Run")
        self.run_button.setProperty("primary", True)
        self.run_button.setAccessibleName("Run this lab")
        self.run_button.setShortcut("Ctrl+Return")
        self.reset_button = QPushButton("Reset to defaults")
        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.setProperty("danger", True)
        self.cancel_button.setVisible(False)
        self.status_badge = Badge("", "neutral")
        self.status_badge.setVisible(False)
        self.status_text = make_label("", "secondary", wrap=False)
        run_row.addWidget(self.run_button)
        run_row.addWidget(self.reset_button)
        run_row.addWidget(self.cancel_button)
        run_row.addSpacing(8)
        run_row.addWidget(self.status_badge)
        run_row.addWidget(self.status_text, 1)
        run_card.body.addLayout(run_row)
        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.setTextVisible(False)
        self.progress.setVisible(False)
        run_card.body.addWidget(self.progress)
        self.admission = make_label("", "secondary")
        right.addWidget(run_card)

        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        self.tabs.setAccessibleName("Parameters and result")
        self.form_stack = QStackedWidget()
        form_holder = QWidget()
        form_holder.setProperty("page", True)
        holder_layout = QVBoxLayout(form_holder)
        holder_layout.setContentsMargins(0, 12, 8, 12)
        holder_layout.setSpacing(12)
        holder_layout.addWidget(self.admission)
        holder_layout.addWidget(self.form_stack)
        self.tabs.addTab(scrollable(form_holder), "Parameters")
        result_holder = QWidget()
        result_layout = QVBoxLayout(result_holder)
        result_layout.setContentsMargins(0, 10, 0, 0)
        self.result_empty = make_label(
            "No result yet. Set the parameters and press Run.", "secondary"
        )
        self.result = ResultWidget()
        self.result.setVisible(False)
        result_layout.addWidget(self.result_empty)
        result_layout.addWidget(self.result, 1)
        self.tabs.addTab(result_holder, "Result")
        right.addWidget(self.tabs, 1)
        body.addLayout(right, 1)
        self.content.addLayout(body, 1)

        self._validate_timer = QTimer(self)
        self._validate_timer.setSingleShot(True)
        self._validate_timer.setInterval(VALIDATE_DELAY_MS)
        self._validate_timer.timeout.connect(self.validate_now)
        self.list.currentItemChanged.connect(self._on_item)
        self.run_button.clicked.connect(self.run)
        self.cancel_button.clicked.connect(self.cancel)
        self.reset_button.clicked.connect(self._reset)
        self.result.exportRequested.connect(self._export)
        self.result.rerunRequested.connect(self._rerun_shown)
        if not session.can_run_jobs:
            self.run_button.setEnabled(False)
        self.select_kind(catalog.KIND_CATALOG[0].kind)

    # ------------------------------------------------------------------ the list

    def _populate_list(self) -> None:
        palette_font = self.list.font()
        for group in catalog.GROUPS:
            header = QListWidgetItem(group.upper())
            header.setFlags(Qt.ItemFlag.NoItemFlags)
            font = palette_font
            font.setBold(True)
            font.setPixelSize(11)
            header.setFont(font)
            self.list.addItem(header)
            for entry in catalog.KIND_CATALOG:
                if entry.group == group:
                    item = QListWidgetItem(entry.title)
                    item.setData(Qt.ItemDataRole.UserRole, entry.kind)
                    item.setToolTip(entry.summary)
                    self.list.addItem(item)

    def _on_item(self, current: QListWidgetItem | None, _: QListWidgetItem | None) -> None:
        kind = current.data(Qt.ItemDataRole.UserRole) if current else None
        if kind and kind != self.current_kind:
            self.select_kind(str(kind))

    def kinds(self) -> list[str]:
        return [
            str(self.list.item(i).data(Qt.ItemDataRole.UserRole))
            for i in range(self.list.count())
            if self.list.item(i).data(Qt.ItemDataRole.UserRole)
        ]

    # ------------------------------------------------------------------ choosing a lab

    def form(self, kind: str | None = None) -> FormView:
        chosen = kind or self.current_kind
        if chosen not in self._forms:
            view = FormView(forms.build_form(chosen))
            view.changed.connect(self._validate_timer.start)
            self._forms[chosen] = view
            self.form_stack.addWidget(view)
        return self._forms[chosen]

    def select_kind(self, kind: str) -> None:
        info = catalog.info(kind)
        self.current_kind = kind
        for row in range(self.list.count()):
            if self.list.item(row).data(Qt.ItemDataRole.UserRole) == kind:
                self.list.blockSignals(True)
                self.list.setCurrentRow(row)
                self.list.blockSignals(False)
        self.kind_title.setText(info.title)
        self.group_badge.set_status("neutral", info.group)
        self.network_badge.setVisible(info.network)
        self.kind_summary.setText(info.summary)
        self.form_stack.setCurrentWidget(self.form(kind))
        self.validate_now()
        known = self._latest.get(self._job_for_kind.get(kind, ""))
        if known is not None:
            self._render(known)
        else:
            self._clear_status()
            self.result.setVisible(False)
            self.result_empty.setVisible(True)

    # ------------------------------------------------------------------ judging the parameters

    def validate_now(self) -> bool:
        """Parse and admit the current values; show the verdict next to the Run button."""
        view = self.form()
        config, errors = forms.assemble(forms.build_form(self.current_kind), view.values())
        view.set_errors(errors)
        valid, message = self._judge(config, errors)
        if not self.session.can_run_jobs:  # never lose this note under a "valid" verdict
            message += f"\n✕  {NO_WORKER}"
        self.admission.setText(message)
        return valid

    def _judge(self, config: dict[str, Any], errors: dict[forms.Path, str]) -> tuple[bool, str]:
        if errors:
            count = len(errors)
            return False, f"✕  {count} parameter{'s need' if count != 1 else ' needs'} attention."
        try:
            prepared = self.session.validate(self.current_kind, config)
        except ValueError as exc:
            return False, f"✕  {exc}"
        limits = self.session.store.limits
        return True, "✓  " + admission_summary(prepared.estimate, limits)

    def _reset(self) -> None:
        self.form().reset()
        self.validate_now()

    # ------------------------------------------------------------------ running

    def run(self) -> str | None:
        """Submit the form's recipe as a job; returns its id, or `None` if it was not accepted."""
        self._validate_timer.stop()
        if not self.validate_now():
            self.tabs.setCurrentIndex(0)  # where the errors are
            return None
        config, _ = forms.assemble(forms.build_form(self.current_kind), self.form().values())
        try:
            job = self.session.submit(self.current_kind, config)
        except ValueError as exc:
            self.admission.setText(f"✕  {exc}")
            return None
        self._job_for_kind[self.current_kind] = job.job_id
        self._views.pop(job.job_id, None)
        self._shown.discard(job.job_id)
        summary = summarize(job)
        self._latest[job.job_id] = summary
        self.tabs.setCurrentIndex(1)
        self._render(summary)
        return job.job_id

    def cancel(self) -> None:
        job_id = self._job_for_kind.get(self.current_kind)
        if job_id:
            self.session.cancel(job_id)

    # ------------------------------------------------------------------ following a job

    def update_jobs(self, summaries: Sequence[JobSummary]) -> None:
        by_id = {s.job_id: s for s in summaries}
        for job_id in list(self._job_for_kind.values()):
            if job_id in by_id:
                self._latest[job_id] = by_id[job_id]
        shown = self._latest.get(self._job_for_kind.get(self.current_kind, ""))
        if shown is not None:
            self._render(shown)

    def _clear_status(self) -> None:
        self.status_badge.setVisible(False)
        self.status_text.setText("")
        self.progress.setVisible(False)
        self.cancel_button.setVisible(False)

    def _render(self, summary: JobSummary) -> None:
        self.status_badge.setVisible(True)
        label = summary.status.replace("_", " ")
        self.status_badge.set_status(summary.status, label)
        live = summary.status in ("queued", "running")
        self.progress.setVisible(live)
        self.cancel_button.setVisible(live)
        self.cancel_button.setEnabled(not summary.cancel_requested)
        self.run_button.setEnabled(self.session.can_run_jobs)
        if live:
            wait = "waiting for the worker" if summary.status == "queued" else "running"
            stopping = "  ·  stopping…" if summary.cancel_requested else ""
            self.status_text.setText(
                f"{summary.title} {wait}  ·  {format_elapsed(summary.elapsed_seconds)}{stopping}"
            )
            return
        took = f"took {format_elapsed(summary.elapsed_seconds)}"
        self.status_text.setText(f"{summary.title} {took}  ·  {summary.error}".rstrip(" ·"))
        if summary.has_result and summary.job_id not in self._shown:
            self._load_result(summary.job_id)
        elif not summary.has_result:
            self.result.setVisible(False)
            self.result_empty.setText(summary.error or f"This job ended: {summary.status}.")
            self.result_empty.setVisible(True)

    def _load_result(self, job_id: str) -> None:
        try:
            view = self._views.get(job_id) or self.session.result(job_id)
        except ResultUnavailableError as exc:
            self.result.setVisible(False)
            self.result_empty.setText(f"✕  {exc}")
            self.result_empty.setVisible(True)
            return
        self._views[job_id] = view
        self._shown.add(job_id)
        self.result.set_view(view)
        self.result.set_actions(rerun=True, export=True)
        self.result.setVisible(True)
        self.result_empty.setVisible(False)

    # ------------------------------------------------------------------ from other pages

    def open_job(self, job_id: str) -> None:
        """Show the result of an existing job (from the history or the overview)."""
        job = self.session.get(job_id)
        self.select_kind(job.kind)
        self._job_for_kind[job.kind] = job_id
        summary = summarize(job)
        self._latest[job_id] = summary
        self._shown.discard(job_id)
        self._render(summary)
        self.tabs.setCurrentIndex(1)
        self.resultOpened.emit(job_id)

    def load_settings(self, job_id: str) -> None:
        """Put a past job's configuration back into the form, ready to run again."""
        job = self.session.get(job_id)
        self.select_kind(job.kind)
        view = self.form(job.kind)
        view.set_values(forms.values_from_config(forms.build_form(job.kind), job.config))
        self.validate_now()
        self.tabs.setCurrentIndex(0)

    def _rerun_shown(self) -> None:
        job_id = self._job_for_kind.get(self.current_kind)
        if job_id:
            self.load_settings(job_id)

    def _export(self) -> None:
        job_id = self._job_for_kind.get(self.current_kind)
        if not job_id:
            return
        chosen, _ = QFileDialog.getSaveFileName(
            self,
            "Export the verified result",
            f"{self.current_kind}-{job_id[:8]}.json",
            "JSON (*.json)",
        )
        if chosen:
            try:
                self.session.export_result(job_id, Path(chosen))
            except (OSError, ResultUnavailableError) as exc:
                self.admission.setText(f"✕  {exc}")
            else:
                self.admission.setText(f"✓  Exported to {chosen}")
