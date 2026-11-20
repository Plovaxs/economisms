"""What every page shares: a title, a one-line purpose, and two hooks the window calls."""

from __future__ import annotations

from collections.abc import Sequence

from PySide6.QtWidgets import QVBoxLayout, QWidget

from prometheus.desktop.session import JobSummary
from prometheus.desktop.ui.widgets import make_label


class PageBase(QWidget):
    def __init__(self, title: str, subtitle: str = "", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setProperty("page", True)
        self.setAccessibleName(title)
        self.page_title = title
        outer = QVBoxLayout(self)
        outer.setContentsMargins(28, 22, 28, 16)
        outer.setSpacing(12)
        self.heading = make_label(title, "h1", wrap=False)
        self.subheading = make_label(subtitle, "secondary")
        outer.addWidget(self.heading)
        outer.addWidget(self.subheading)
        self.content = QVBoxLayout()
        self.content.setSpacing(14)
        outer.addLayout(self.content, 1)

    def activated(self) -> None:
        """The window just showed this page: refresh anything that may have gone stale."""

    def update_jobs(self, summaries: Sequence[JobSummary]) -> None:
        """The window's periodic look at the job queue (a few times a second)."""
