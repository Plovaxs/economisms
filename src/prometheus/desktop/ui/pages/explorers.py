"""The explorers: the dashboard's views as direct, quick computations.

Each press of Compute starts the calculation in a child process (`explorer_runner`) and the page
polls it a few times a second, so the window never freezes and a calculation can be cancelled. The
first time an explorer is opened it computes with its default parameters, so the page is never an
empty form.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QHBoxLayout,
    QListWidget,
    QListWidgetItem,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from prometheus.desktop import explorers
from prometheus.desktop.explorer_runner import ExplorerTask
from prometheus.desktop.results import analyze_payload
from prometheus.desktop.ui.formview import FormView
from prometheus.desktop.ui.pages.base import PageBase
from prometheus.desktop.ui.resultview import ResultWidget
from prometheus.desktop.ui.widgets import Badge, Card, make_label, scrollable
from prometheus.evidence.constants import SIMULATION_DISCLAIMER

POLL_MS = 80


class ExplorersPage(PageBase):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(
            "Explorers",
            "The research dashboard's views, computed on this machine in a child process. "
            "Everything here is simulated and labelled as such.",
            parent,
        )
        self.current = ""
        self._forms: dict[str, FormView] = {}
        self._computed: set[str] = set()
        self._task: ExplorerTask | None = None
        self._task_name = ""

        body = QHBoxLayout()
        body.setSpacing(16)
        self.list = QListWidget()
        self.list.setObjectName("list")
        self.list.setAccessibleName("Explorers")
        for entry in explorers.EXPLORERS:
            item = QListWidgetItem(entry.title)
            item.setData(Qt.ItemDataRole.UserRole, entry.name)
            item.setToolTip(entry.summary)
            self.list.addItem(item)
        self.list.setFixedHeight(len(explorers.EXPLORERS) * 34 + 12)

        self.controls = Card()
        row = QHBoxLayout()
        self.compute_button = QPushButton("Compute")
        self.compute_button.setProperty("primary", True)
        self.compute_button.setAccessibleName("Compute this explorer")
        self.compute_button.setShortcut("Ctrl+Return")
        self.reset_button = QPushButton("Reset")
        self.reset_button.setToolTip("Reset to the default parameters")
        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.setProperty("danger", True)
        self.cancel_button.setVisible(False)
        row.addWidget(self.compute_button)
        row.addWidget(self.reset_button)
        row.addWidget(self.cancel_button)
        row.addStretch(1)
        self.controls.body.addLayout(row)  # the actions come first: they must never scroll away
        self.status = make_label("", "caption")
        self.controls.body.addWidget(self.status)
        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.setTextVisible(False)
        self.progress.setVisible(False)
        self.controls.body.addWidget(self.progress)
        self.form_holder = QVBoxLayout()
        self.controls.body.addLayout(self.form_holder)

        left_column = QWidget()
        left_column.setProperty("page", True)
        left_layout = QVBoxLayout(left_column)
        left_layout.setContentsMargins(0, 0, 8, 8)
        left_layout.setSpacing(12)
        left_layout.addWidget(self.list)
        left_layout.addWidget(self.controls)
        left_layout.addStretch(1)
        left = scrollable(left_column)
        left.setFixedWidth(330)
        body.addWidget(left)

        right = QVBoxLayout()
        right.setSpacing(10)
        title_row = QHBoxLayout()
        self.title = make_label("", "h2", wrap=False)
        self.synthetic = Badge("simulated data", "warn")
        title_row.addWidget(self.title)
        title_row.addWidget(self.synthetic)
        title_row.addStretch(1)
        right.addLayout(title_row)
        self.summary = make_label("", "secondary")
        right.addWidget(self.summary)
        self.result = ResultWidget()
        self.result.setVisible(False)
        self.empty = make_label("", "secondary")
        right.addWidget(self.empty)
        right.addWidget(self.result, 1)
        body.addLayout(right, 1)
        self.content.addLayout(body, 1)

        self._poll = QTimer(self)
        self._poll.setInterval(POLL_MS)
        self._poll.timeout.connect(self._check_task)
        self.list.currentItemChanged.connect(self._on_item)
        self.compute_button.clicked.connect(self.compute)
        self.cancel_button.clicked.connect(self.cancel)
        self.reset_button.clicked.connect(self._reset)
        self._started = False  # the first explorer is computed when the page is first shown

    # ------------------------------------------------------------------ choosing

    def _on_item(self, current: QListWidgetItem | None, _: QListWidgetItem | None) -> None:
        name = current.data(Qt.ItemDataRole.UserRole) if current else None
        if name and name != self.current:
            self.select(str(name))

    def names(self) -> list[str]:
        return [
            str(self.list.item(i).data(Qt.ItemDataRole.UserRole)) for i in range(self.list.count())
        ]

    def form(self, name: str | None = None) -> FormView:
        chosen = name or self.current
        if chosen not in self._forms:
            view = FormView(explorers.explorer(chosen).fields, columns=1)
            self._forms[chosen] = view
            self.form_holder.addWidget(view)
            view.setVisible(False)
        return self._forms[chosen]

    def activated(self) -> None:
        """Open the first explorer (and compute it, with its defaults) the first time the page is
        shown, not when the window is built: a calculation nobody asked for is a process
        started for nothing."""
        if not self._started:
            self.select(explorers.EXPLORERS[0].name)

    def select(self, name: str) -> None:
        self._started = True
        chosen = explorers.explorer(name)
        self.current = name
        for row in range(self.list.count()):
            if self.list.item(row).data(Qt.ItemDataRole.UserRole) == name:
                self.list.blockSignals(True)
                self.list.setCurrentRow(row)
                self.list.blockSignals(False)
        for view in self._forms.values():
            view.setVisible(False)
        view = self.form(name)
        view.setVisible(bool(chosen.fields))
        self.title.setText(chosen.title)
        self.summary.setText(chosen.summary)
        self.synthetic.setVisible(name not in ("experiments", "validation_issues"))
        self.reset_button.setVisible(bool(chosen.fields))
        self.result.clear()
        self.result.setVisible(False)
        self.empty.setText("")
        if name not in self._computed:
            self.compute()

    # ------------------------------------------------------------------ computing

    def _reset(self) -> None:
        self.form().reset()

    def compute(self) -> bool:
        """Validate the parameters and start the calculation; False if they were refused."""
        name = self.current
        view = self.form(name)
        params, errors = explorers.validate(name, view.values())
        view.set_errors(errors)
        if errors:
            self.status.setText(f"✕  {len(errors)} parameter(s) need attention.")
            return False
        self.cancel()
        self._task = ExplorerTask(name, params)
        self._task_name = name
        self._task.start()
        self._computed.add(name)
        self.status.setText("Computing…")
        self.progress.setVisible(True)
        self.cancel_button.setVisible(True)
        self.compute_button.setEnabled(False)
        self._poll.start()
        return True

    def cancel(self) -> None:
        if self._task is not None and not self._task.done:
            self._task.cancel()

    def busy(self) -> bool:
        return self._task is not None and not self._task.done

    def _check_task(self) -> None:
        task = self._task
        if task is None:
            self._poll.stop()
            return
        if not task.done:
            self.status.setText(f"Computing…  {task.elapsed:0.1f} s")
            return
        self._poll.stop()
        self.progress.setVisible(False)
        self.cancel_button.setVisible(False)
        self.compute_button.setEnabled(True)
        self._task = None
        if self._task_name != self.current:
            return  # the person moved on; the result belongs to another explorer
        if task.error is not None or task.payload is None:
            self.result.setVisible(False)
            self.empty.setText(f"✕  {task.error or 'The calculation returned nothing.'}")
            self.status.setText("")
            return
        title = explorers.explorer(task.name).title
        view = analyze_payload(
            task.payload, kind=task.name, title=title, disclaimer=SIMULATION_DISCLAIMER
        )
        self.empty.setText("")
        self.result.set_view(view)
        self.result.set_actions(rerun=False, export=False)
        self.result.setVisible(True)
        self.status.setText(f"Computed in {task.elapsed:0.1f} s.")

    def shutdown(self) -> None:
        """Stop polling and any calculation in flight (the window is closing)."""
        self._poll.stop()
        self.cancel()
