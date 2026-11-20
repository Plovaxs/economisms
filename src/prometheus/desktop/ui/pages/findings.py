"""The findings: what this project actually found, including every time a hypothesis did not hold.

The page does not keep its own copy. It parses `docs/RESULTS_AND_LIMITATIONS.md` (see
`desktop.findings`) and shows each section as the Markdown it was written in. Negative results
appear exactly as prominently as positive ones, because that is the document's rule.
"""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtGui import QTextDocument
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from prometheus.desktop import findings
from prometheus.desktop.findings import FindingsDocument
from prometheus.desktop.ui.pages.base import PageBase
from prometheus.desktop.ui.widgets import make_label, plain_tooltip

GATE_KEY = "gate"
LIMITS_KEY = "limitations"
# GitHub-flavoured Markdown, but a raw `<img>` or `<a>` in the text is text, not markup
MARKDOWN_FEATURES = (
    QTextDocument.MarkdownFeature.MarkdownDialectGitHub
    | QTextDocument.MarkdownFeature.MarkdownNoHTML
)


class SafeBrowser(QTextBrowser):
    """A text view that never loads anything the text points at: no image from a file, no style
    sheet, no network. The findings are prose; they have no reason to reach outside themselves."""

    def loadResource(self, type: int, name: Any) -> Any:  # noqa: A002 - Qt's own signature
        return None


class FindingsPage(PageBase):
    def __init__(
        self, document: FindingsDocument | None = None, parent: QWidget | None = None
    ) -> None:
        super().__init__(
            "Findings",
            "What the comparisons in this repository found, including the negative results. "
            "Read from docs/RESULTS_AND_LIMITATIONS.md, the one place they live.",
            parent,
        )
        self.document = document if document is not None else findings.load()
        self._text: dict[str, str] = {}
        body = QHBoxLayout()
        body.setSpacing(16)
        left = QVBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search the findings")
        self.search.setClearButtonEnabled(True)
        self.search.setAccessibleName("Search the findings")
        self.list = QListWidget()
        self.list.setObjectName("list")
        self.list.setAccessibleName("Findings")
        self.list.setWordWrap(True)
        self.list.setTextElideMode(Qt.TextElideMode.ElideNone)
        self.count = make_label("", "caption")
        left.addWidget(self.search)
        left.addWidget(self.list, 1)
        left.addWidget(self.count)
        holder = QWidget()
        holder.setFixedWidth(380)
        holder.setLayout(left)
        left.setContentsMargins(0, 0, 0, 0)
        body.addWidget(holder)
        right = QVBoxLayout()
        self.browser = SafeBrowser()
        self.browser.setAccessibleName("Finding text")
        self.browser.setOpenLinks(False)
        self.browser.setOpenExternalLinks(False)
        right.addWidget(self.browser, 1)
        self.unavailable = make_label("", "secondary")
        right.addWidget(self.unavailable)
        body.addLayout(right, 1)
        self.content.addLayout(body, 1)

        if not self.document.available:
            self.unavailable.setText(
                "The findings document is part of a checkout of the repository, not of the "
                "installed package, and it was not found next to this one. Nothing is invented in "
                "its place."
            )
            self.browser.setVisible(False)
            self.search.setEnabled(False)
        self._build_entries()
        self.search.textChanged.connect(self._filter)
        self.list.currentItemChanged.connect(self._show)
        if self.list.count():
            self.list.setCurrentRow(0)

    def _add(self, key: str, label: str, markdown: str, title: str) -> None:
        item = QListWidgetItem(label)
        item.setData(Qt.ItemDataRole.UserRole, key)
        item.setToolTip(plain_tooltip(title))
        self.list.addItem(item)
        self._text[key] = markdown

    def _build_entries(self) -> None:
        doc = self.document
        if not doc.available:
            return
        if doc.gate_markdown:
            self._add(
                GATE_KEY,
                f"Gate decision: {doc.gate_decision or '—'}",
                f"## The overall gate decision: {doc.gate_decision}\n\n{doc.gate_markdown}",
                "The overall gate decision",
            )
        for finding in doc.findings:
            self._add(
                f"finding:{finding.number}",
                f"{finding.number}.  {finding.title}",
                f"## Finding {finding.number} ({finding.pr}): {finding.title}"
                f"\n\n{finding.markdown}",
                f"Finding {finding.number} ({finding.pr}): {finding.title}",
            )
        if doc.limitations_markdown:
            self._add(
                LIMITS_KEY,
                "Known limitations",
                f"## Known limitations that are not findings\n\n{doc.limitations_markdown}",
                "Known limitations that are not findings",
            )
        self.count.setText(f"{len(doc.findings)} findings recorded")

    def entries(self) -> list[str]:
        return [
            str(self.list.item(i).data(Qt.ItemDataRole.UserRole)) for i in range(self.list.count())
        ]

    def visible_entries(self) -> list[str]:
        return [
            str(self.list.item(i).data(Qt.ItemDataRole.UserRole))
            for i in range(self.list.count())
            if not self.list.item(i).isHidden()
        ]

    def select(self, key: str) -> None:
        for row in range(self.list.count()):
            if self.list.item(row).data(Qt.ItemDataRole.UserRole) == key:
                self.list.setCurrentRow(row)
                return
        raise KeyError(key)

    def _show(self, current: QListWidgetItem | None, _: QListWidgetItem | None) -> None:
        if current is None:
            return
        key = str(current.data(Qt.ItemDataRole.UserRole))
        self.browser.document().setMarkdown(self._text.get(key, ""), MARKDOWN_FEATURES)

    def _filter(self, needle: str) -> None:
        wanted = needle.strip().lower()
        shown = 0
        for row in range(self.list.count()):
            item = self.list.item(row)
            key = str(item.data(Qt.ItemDataRole.UserRole))
            match = (
                not wanted
                or wanted in self._text.get(key, "").lower()
                or wanted in item.text().lower()
            )
            item.setHidden(not match)
            shown += match
        total = self.list.count()
        self.count.setText(
            f"{len(self.document.findings)} findings recorded"
            if not wanted
            else f"{shown} of {total} sections match"
        )
