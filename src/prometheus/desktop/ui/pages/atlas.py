"""The Atlas: the model zoo as a web you can walk.

Models sit on an outer ring grouped by family, the classical baselines they were judged against on
an inner ring, and the pipelines in the middle. A line is an edge of `modelzoo.graph`, which is
validated against the code and the recorded studies, so every line is a fact about this repository:
a dotted line joins a baseline to the model it was judged against, a solid one is a relation between
models, a heavy arrow means the output of one is the input of the next in a pipeline.

Shapes carry the meaning (a colour is never the only signal): a filled circle is a model written in
the zoo, a square one that was already in the repository, a diamond a baseline, a ring a pipeline.
The models that were deliberately not built are listed on the left with their reason and are not
drawn. Everything shown is read from the registry and the stored records; text is shown as text.
"""

from __future__ import annotations

import math
from typing import Any

from PySide6.QtCore import QEvent, QPointF, QRectF, Qt, Signal
from PySide6.QtGui import (
    QColor,
    QFontMetricsF,
    QKeyEvent,
    QMouseEvent,
    QPainter,
    QPaintEvent,
    QPen,
    QPolygonF,
)
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from prometheus.desktop.ui import theme
from prometheus.desktop.ui.pages.base import PageBase
from prometheus.desktop.ui.pages.findings import SafeBrowser
from prometheus.desktop.ui.widgets import make_label, plain_tooltip
from prometheus.modelzoo import graph as zoo_graph
from prometheus.modelzoo.registry import ENTRIES, PIPELINES, Entry

NODE_RADIUS = 7.0
EDGE_STYLES = {
    "baseline_for": Qt.PenStyle.DotLine,
    "extends": Qt.PenStyle.SolidLine,
    "alternative_to": Qt.PenStyle.DashLine,
    "uses": Qt.PenStyle.SolidLine,
    "feeds": Qt.PenStyle.SolidLine,
}
VERDICT_MARK = {
    "SUPPORTED": "supported",
    "INCONCLUSIVE": "inconclusive",
    "CONTRADICTED": "contradicted",
}


class AtlasView(QWidget):
    """The drawing. It owns the layout, the hit test and the keyboard; the page owns the text."""

    selected = Signal(str)

    def __init__(self, graph: zoo_graph.Graph, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setMinimumSize(380, 320)
        self.setAccessibleName("Model web")
        self.nodes = [
            n
            for n in graph.nodes
            if n["kind"] in ("model", "baseline", "pipeline") and n["status"] != "not_built"
        ]
        self.by_id = {n["id"]: n for n in self.nodes}
        self.edges = [
            e
            for e in graph.edges
            if e["source"] in self.by_id and e["target"] in self.by_id and e["kind"] in EDGE_STYLES
        ]
        self.order = self._ordered_ids()
        self.current: str | None = None
        self.hover: str | None = None
        self._family_angle: dict[str, float] = {}
        self._positions: dict[str, QPointF] = {}

    def _ordered_ids(self) -> list[str]:
        models = sorted(
            (n for n in self.nodes if n["kind"] == "model"), key=lambda n: (n["family"], n["id"])
        )
        baselines = sorted(
            (n for n in self.nodes if n["kind"] == "baseline"), key=lambda n: (n["family"], n["id"])
        )
        pipelines = [n for n in self.nodes if n["kind"] == "pipeline"]
        return [n["id"] for n in models + baselines + pipelines]

    # ----- layout --------------------------------------------------------------------------------

    def positions(self) -> dict[str, QPointF]:
        """Node centres: models on the outer ring, baselines inside, pipelines in the middle."""
        width, height = float(self.width()), float(self.height())
        centre = QPointF(width / 2, height / 2)
        outer = max(40.0, min(width, height) / 2 - 46.0)
        rings = {"model": outer, "baseline": 0.58 * outer, "pipeline": 0.16 * outer}
        out: dict[str, QPointF] = {}
        sums: dict[str, list[float]] = {}
        for kind, radius in rings.items():
            ids = [i for i in self.order if self.by_id[i]["kind"] == kind]
            for index, node_id in enumerate(ids):
                shift = 0.5 if kind == "baseline" else 0.0
                angle = -math.pi / 2 + 2 * math.pi * (index + shift) / max(len(ids), 1)
                if kind == "pipeline" and len(ids) == 1:
                    angle = -math.pi / 2
                out[node_id] = QPointF(
                    centre.x() + radius * math.cos(angle), centre.y() + radius * math.sin(angle)
                )
                if kind == "model":
                    sums.setdefault(self.by_id[node_id]["family"], []).append(angle)
        self._family_angle = {f: sum(a) / len(a) for f, a in sums.items()}
        self._positions = out
        return out

    def node_at(self, point: QPointF) -> str | None:
        best: tuple[float, str] | None = None
        for node_id, pos in self.positions().items():
            distance = math.hypot(point.x() - pos.x(), point.y() - pos.y())
            if distance <= NODE_RADIUS + 5 and (best is None or distance < best[0]):
                best = (distance, node_id)
        return None if best is None else best[1]

    # ----- selection -----------------------------------------------------------------------------

    def select(self, node_id: str | None) -> None:
        if node_id is not None and node_id not in self.by_id:
            node_id = None
        self.current = node_id
        if node_id is not None:
            node = self.by_id[node_id]
            self.setAccessibleDescription(f"Selected {node['label']}, {node['kind']}")
            self.selected.emit(node_id)
        self.update()

    def neighbours(self, node_id: str) -> set[str]:
        out: set[str] = set()
        for e in self.edges:
            if e["source"] == node_id:
                out.add(e["target"])
            elif e["target"] == node_id:
                out.add(e["source"])
        return out

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        hovered = self.node_at(event.position())
        if hovered != self.hover:
            self.hover = hovered
            self.update()

    def leaveEvent(self, event: QEvent) -> None:
        del event
        if self.hover is not None:
            self.hover = None
            self.update()

    def mousePressEvent(self, event: QMouseEvent) -> None:
        self.setFocus()
        self.select(self.node_at(event.position()))

    def keyPressEvent(self, event: QKeyEvent) -> None:
        step = {
            Qt.Key.Key_Right: 1,
            Qt.Key.Key_Down: 1,
            Qt.Key.Key_Left: -1,
            Qt.Key.Key_Up: -1,
        }.get(Qt.Key(event.key()))
        if step is None or not self.order:
            super().keyPressEvent(event)
            return
        index = (
            self.order.index(self.current)
            if self.current in self.order
            else (-1 if step > 0 else 0)
        )
        self.select(self.order[(index + step) % len(self.order)])

    # ----- drawing -------------------------------------------------------------------------------

    def paintEvent(self, event: QPaintEvent) -> None:
        del event
        palette = theme.current()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), palette.color(palette.surface))
        positions = self.positions()
        near = self.neighbours(self.current) if self.current else set()
        ink, muted, accent = (
            palette.color(palette.ink),
            palette.color(palette.muted),
            palette.color(palette.accent),
        )
        faded = QColor(muted)
        faded.setAlpha(70)
        for e in self.edges:
            a, b = positions[e["source"]], positions[e["target"]]
            touches = self.current in (e["source"], e["target"])
            colour = accent if touches else faded
            width = 2.6 if e["kind"] == "feeds" else 1.8 if touches else 1.0
            pen = QPen(colour, width)
            pen.setStyle(EDGE_STYLES[e["kind"]])
            painter.setPen(pen)
            painter.drawLine(a, b)
            if e["kind"] == "feeds":
                self._arrow(painter, a, b, colour)
        label_font = painter.font()
        label_font.setPixelSize(11)
        painter.setFont(label_font)
        for node_id in self.order:
            node, pos = self.by_id[node_id], positions[node_id]
            focused = node_id == self.current or node_id in near
            outline = QPen(
                accent if node_id == self.current else ink, 2.5 if node_id == self.current else 1.4
            )
            painter.setPen(outline)
            fill = (
                accent
                if node["kind"] == "model" and node["status"] == "implemented"
                else palette.color(palette.raised)
            )
            painter.setBrush(fill)
            self._draw_node(painter, node, pos)
            if focused or node_id == self.hover:
                self._draw_label(painter, node, pos, ink, palette)
        self._draw_family_labels(painter, muted)
        if self.hasFocus():
            painter.setPen(QPen(accent, 2))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRoundedRect(QRectF(self.rect()).adjusted(1, 1, -1, -1), 6, 6)

    def _draw_node(self, painter: QPainter, node: dict[str, Any], pos: QPointF) -> None:
        r = NODE_RADIUS
        if node["kind"] == "baseline":
            painter.drawPolygon(
                QPolygonF(
                    [
                        QPointF(pos.x(), pos.y() - r - 1),
                        QPointF(pos.x() + r + 1, pos.y()),
                        QPointF(pos.x(), pos.y() + r + 1),
                        QPointF(pos.x() - r - 1, pos.y()),
                    ]
                )
            )
        elif node["kind"] == "pipeline":
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawEllipse(pos, r + 3, r + 3)
        elif node["status"] == "existing":
            painter.drawRect(QRectF(pos.x() - r, pos.y() - r, 2 * r, 2 * r))
        else:
            painter.drawEllipse(pos, r, r)

    def _draw_label(
        self,
        painter: QPainter,
        node: dict[str, Any],
        pos: QPointF,
        colour: QColor,
        palette: theme.Palette,
    ) -> None:
        text = node["label"] if len(node["label"]) <= 34 else node["label"][:33] + "…"
        metrics = QFontMetricsF(painter.font())
        width = metrics.horizontalAdvance(text) + 12
        right_side = pos.x() >= self.width() / 2
        x = pos.x() + 11 if right_side else pos.x() - 11 - width
        x = max(4.0, min(x, self.width() - width - 4.0))
        y = max(4.0, min(pos.y() - 10, self.height() - 24.0))
        box = QRectF(x, y, width, 20)
        background = palette.color(palette.page)
        background.setAlpha(225)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(background)
        painter.drawRoundedRect(box, 4, 4)
        painter.setPen(colour)
        painter.drawText(box, int(Qt.AlignmentFlag.AlignCenter), text)

    def _draw_family_labels(self, painter: QPainter, colour: QColor) -> None:
        font = painter.font()
        font.setBold(True)
        painter.setFont(font)
        painter.setPen(colour)
        centre = QPointF(self.width() / 2, self.height() / 2)
        radius = max(40.0, min(self.width(), self.height()) / 2 - 46.0) + 30.0
        for family, angle in self._family_angle.items():
            point = QPointF(
                centre.x() + radius * math.cos(angle), centre.y() + radius * math.sin(angle)
            )
            painter.drawText(
                QRectF(point.x() - 60, point.y() - 8, 120, 16),
                int(Qt.AlignmentFlag.AlignCenter),
                family,
            )
        font.setBold(False)
        painter.setFont(font)

    def _arrow(self, painter: QPainter, a: QPointF, b: QPointF, colour: QColor) -> None:
        angle = math.atan2(b.y() - a.y(), b.x() - a.x())
        tip = QPointF(
            b.x() - (NODE_RADIUS + 4) * math.cos(angle), b.y() - (NODE_RADIUS + 4) * math.sin(angle)
        )
        wing = 8.0
        left = QPointF(
            tip.x() - wing * math.cos(angle - 0.45), tip.y() - wing * math.sin(angle - 0.45)
        )
        right = QPointF(
            tip.x() - wing * math.cos(angle + 0.45), tip.y() - wing * math.sin(angle + 0.45)
        )
        painter.setBrush(colour)
        painter.drawPolygon(QPolygonF([tip, left, right]))


class AtlasPage(PageBase):
    def __init__(self, graph: zoo_graph.Graph | None = None, parent: QWidget | None = None) -> None:
        super().__init__(
            "Atlas",
            "The model zoo as a web. Every line is an edge of a graph checked against the code and "
            "the recorded studies. Select a model to see what it was judged against.",
            parent,
        )
        self.graph = graph if graph is not None else zoo_graph.build_graph()
        self.verdicts = zoo_graph.recorded_verdicts()
        self.entries = {e.id: e for e in ENTRIES}
        self.view = AtlasView(self.graph)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search the models")
        self.search.setClearButtonEnabled(True)
        self.search.setAccessibleName("Search the models")
        self.status = QComboBox()
        self.status.setAccessibleName("Filter by status")
        for label, value in (
            ("All requested models", ""),
            ("Written in the zoo", "implemented"),
            ("Already in the repository", "existing"),
            ("Not built", "not_built"),
        ):
            self.status.addItem(label, value)
        self.list = QListWidget()
        self.list.setObjectName("list")
        self.list.setAccessibleName("Models")
        self.count = make_label("", "caption")
        self.card = SafeBrowser()
        self.card.setAccessibleName("Model card")
        self.card.setOpenLinks(False)
        self.card.setOpenExternalLinks(False)
        left = QVBoxLayout()
        left.setContentsMargins(0, 0, 0, 0)
        left.addWidget(self.search)
        left.addWidget(self.status)
        left.addWidget(self.list, 1)
        left.addWidget(self.count)
        holder = QWidget()
        holder.setFixedWidth(300)
        holder.setLayout(left)
        middle = QVBoxLayout()
        middle.addWidget(self.view, 6)
        middle.addWidget(make_label(self._legend(), "caption"))
        self.card.setMinimumHeight(110)
        middle.addWidget(self.card, 2)
        row = QHBoxLayout()
        row.setSpacing(16)
        row.addWidget(holder)
        row.addLayout(middle, 1)
        self.content.addLayout(row, 1)
        self._fill_list()
        self.search.textChanged.connect(self._fill_list)
        self.status.currentIndexChanged.connect(self._fill_list)
        self.list.currentItemChanged.connect(self._list_changed)
        self.view.selected.connect(self._view_selected)
        self.card.setMarkdown(self.summary_text())

    def summary_text(self) -> str:
        c = zoo_graph.coverage()
        by, hyp = c["by_status"], c["hypotheses"]
        return (
            f"**{c['requested']} models were requested.** "
            f"{by.get('implemented', 0)} are written in "
            f"the zoo, {by.get('existing', 0)} were already in this repository and "
            f"{by.get('not_built', 0)} are deliberately not built, each with its reason. "
            f"{sum(hyp.values())} hypotheses were recorded ({hyp.get('SUPPORTED', 0)} supported, "
            f"{hyp.get('INCONCLUSIVE', 0)} inconclusive, "
            f"{hyp.get('CONTRADICTED', 0)} contradicted)."
        )

    @staticmethod
    def _legend() -> str:
        return (
            "Circle: written in the zoo.  Square: already in the repository.  Diamond: baseline.  "
            "Ring: pipeline.  Dotted: judged against.  Heavy arrow: feeds."
        )

    def _fill_list(self) -> None:
        needle = self.search.text().strip().lower()
        status = str(self.status.currentData() or "")
        self.list.blockSignals(True)
        self.list.clear()
        shown = 0
        for e in ENTRIES:
            if e.role != "model" or (status and e.status != status):
                continue
            if needle and needle not in f"{e.name} {e.family} {e.id}".lower():
                continue
            mark = {"implemented": "●", "existing": "■", "not_built": "○"}[e.status]
            item = QListWidgetItem(f"{mark}  {e.name}")
            item.setData(Qt.ItemDataRole.UserRole, e.id)
            item.setToolTip(plain_tooltip(f"{e.name}: {e.status.replace('_', ' ')}"))
            self.list.addItem(item)
            shown += 1
        self.list.blockSignals(False)
        self.count.setText(f"{shown} models shown")

    def _list_changed(self, current: QListWidgetItem | None) -> None:
        if current is None:
            return
        entry_id = str(current.data(Qt.ItemDataRole.UserRole))
        self.view.current = entry_id if entry_id in self.view.by_id else None
        self.view.update()
        self._show_card(entry_id)

    def _view_selected(self, node_id: str) -> None:
        self._show_card(node_id)
        for row in range(self.list.count()):
            if self.list.item(row).data(Qt.ItemDataRole.UserRole) == node_id:
                self.list.blockSignals(True)
                self.list.setCurrentRow(row)
                self.list.blockSignals(False)
                return

    def select(self, entry_id: str) -> None:
        """Select a model by id (from outside, and from the tests)."""
        if entry_id in self.view.by_id:
            self.view.select(entry_id)
        else:
            self._show_card(entry_id)

    def _show_card(self, entry_id: str) -> None:
        self.card.setMarkdown(self.card_text(entry_id))

    def card_text(self, entry_id: str) -> str:
        e: Entry | None = self.entries.get(entry_id)
        if e is None:
            pipeline = next((p for p in PIPELINES if f"pipeline:{p.id}" == entry_id), None)
            if pipeline is None:
                return "Nothing selected."
            steps = " → ".join(self.entries[s].name for s in pipeline.steps)
            tests = ", ".join(
                f"{h} ({VERDICT_MARK.get(self.verdicts.get(h, ''), 'unrecorded')})"
                for h in pipeline.hypotheses
            )
            return (
                f"**{pipeline.name}**\n\nPipeline: {steps}.\n\n{pipeline.note}.\n\n"
                f"Tests: {tests}. Finding {pipeline.finding}."
            )
        lines = [
            f"**{e.name}**  ({e.status.replace('_', ' ')}"
            f"{', baseline' if e.role == 'baseline' else ''}; {e.family})"
        ]
        if e.reference:
            lines.append(f"Reference: {e.reference}.")
        if e.status == "not_built":
            lines.append(f"Not built: {e.reason}.")
        else:
            lines.append(f"{e.task}." if e.task else "")
            if e.module:
                lines.append(f"Code: {e.module}.{e.symbol}")
        if e.baselines:
            lines.append(
                "Judged against: " + ", ".join(self.entries[b].name for b in e.baselines) + "."
            )
        if e.data:
            lines.append("Data: " + ", ".join(e.data) + ".")
        if e.hypotheses:
            tests = ", ".join(
                f"{h} ({VERDICT_MARK.get(self.verdicts.get(h, ''), 'unrecorded')})"
                for h in e.hypotheses
            )
            lines.append(
                f"Tests: {tests}." + (f" Reported in Finding {e.finding}." if e.finding else "")
            )
        elif e.status == "implemented" and e.role == "model":
            lines.append("Not compared with a baseline in a recorded study; unit-tested only.")
        links = [
            self.entries[n].name
            for n in sorted(self.view.neighbours(entry_id))
            if n in self.entries
        ]
        if links:
            lines.append("Linked to: " + ", ".join(links) + ".")
        return "\n\n".join(x for x in lines if x)
