"""The Atlas in three dimensions: the model web drawn on spheres, which you can turn.

Models sit on the outer shell grouped by family, baselines on an inner shell near the models they
were judged against, pipelines at the core. Drag to orbit (the camera coasts when you let go), wheel
to zoom, click to select; with the keyboard: arrows rotate, plus and minus zoom, 0 resets, `[` and
`]` choose the previous or next model. It draws what `desktop.orbit3d` computes, the same engine as
the web app's. With motion reduced it never moves by itself, and the flowing dots along the
pipelines are not drawn.
"""

from __future__ import annotations

import math
import time
from typing import Any

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import (
    QColor,
    QFontMetricsF,
    QKeyEvent,
    QMouseEvent,
    QPainter,
    QPaintEvent,
    QPen,
    QPolygonF,
    QWheelEvent,
)
from PySide6.QtWidgets import QSizePolicy, QWidget

from prometheus.desktop import orbit3d as engine
from prometheus.desktop.ui import theme
from prometheus.modelzoo import graph as zoo_graph

EDGE_KINDS = ("baseline_for", "extends", "alternative_to", "uses", "feeds")
FRAME_MS = 16


class Atlas3DView(QWidget):
    selected = Signal(str)

    def __init__(self, graph: zoo_graph.Graph, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setMinimumSize(420, 340)
        self.setAccessibleName("Model web in 3D")
        self.setAccessibleDescription(
            "Drag to rotate, wheel to zoom, arrow keys rotate, plus and minus zoom, "
            "zero resets, left and right bracket choose a model."
        )
        layout = engine.layout_web3(graph.nodes, graph.edges)
        by_id = {n["id"]: n for n in graph.nodes}
        self.ids = sorted(layout, key=lambda i: (by_id[i]["kind"], by_id[i]["family"], i))
        self.nodes = {i: by_id[i] for i in self.ids}
        self.positions = layout
        self.edges = [
            e
            for e in graph.edges
            if e["kind"] in EDGE_KINDS and e["source"] in layout and e["target"] in layout
        ]
        self.families: list[tuple[str, engine.Vec3]] = []
        for family in sorted({n["family"] for n in self.nodes.values() if n["kind"] == "model"}):
            pts = [
                layout[i]
                for i, n in self.nodes.items()
                if n["kind"] == "model" and n["family"] == family
            ]
            total: engine.Vec3 = (0.0, 0.0, 0.0)
            for p in pts:
                total = engine.add(total, p)
            self.families.append((family, engine.scale(total, 1.2 / len(pts))))
        self.orbit = engine.Orbit()
        self.current: str | None = None
        self.hover: str | None = None
        self.auto_rotate = True
        self.reduce_motion = False
        self.labels = "selected"
        self.hidden_families: set[str] = set()
        self._dragging = False
        self._last = QPointF()
        self._moved = 0.0
        self._last_time = time.monotonic()
        self._frame_time = self._last_time
        self._projected: dict[str, engine.Projected] = {}
        self._radii: dict[str, float] = {}
        self._timer = QTimer(self)
        self._timer.setInterval(FRAME_MS)
        self._timer.timeout.connect(self._tick)

    # ----- configuration -----------------------------------------------------------------------

    def configure(self, *, auto_rotate: bool, reduce_motion: bool, labels: str) -> None:
        self.auto_rotate, self.reduce_motion, self.labels = auto_rotate, reduce_motion, labels
        self._sync_timer()
        self.update()

    def animating(self) -> bool:
        moving = self.orbit.yaw_velocity != 0 or self.orbit.pitch_velocity != 0
        rotating = self.auto_rotate and not self.reduce_motion
        return rotating or moving or self._dragging

    def _sync_timer(self) -> None:
        wanted = self.isVisible() and (self.animating() or not self.reduce_motion)
        if wanted and not self._timer.isActive():
            self._timer.start()
        elif not wanted and self._timer.isActive():
            self._timer.stop()

    def showEvent(self, event: Any) -> None:
        super().showEvent(event)
        self._frame_time = time.monotonic()
        self._sync_timer()

    def hideEvent(self, event: Any) -> None:
        super().hideEvent(event)
        self._timer.stop()

    def _tick(self) -> None:
        now = time.monotonic()
        dt = min(now - self._frame_time, 0.1)
        self._frame_time = now
        rotating = self.auto_rotate and not self.reduce_motion
        if self.animating():
            self.orbit = engine.step_orbit(
                self.orbit, dt, dragging=self._dragging, auto_rotate=rotating
            )
        self.update()
        if self.reduce_motion and not self.animating():
            self._timer.stop()  # nothing moves on its own: redraw only on input

    # ----- selection ---------------------------------------------------------------------------

    def select(self, node_id: str | None) -> None:
        if node_id is not None and node_id not in self.nodes:
            node_id = None
        self.current = node_id
        if node_id is not None:
            node = self.nodes[node_id]
            self.setAccessibleDescription(f"Selected {node['label']}, {node['kind']}")
            self.selected.emit(node_id)
        self.update()

    def visible_ids(self) -> list[str]:
        return [
            i
            for i in self.ids
            if self.nodes[i]["kind"] != "model"
            or self.nodes[i]["family"] not in self.hidden_families
        ]

    def neighbours(self, node_id: str) -> set[str]:
        out: set[str] = set()
        for e in self.edges:
            if e["source"] == node_id:
                out.add(e["target"])
            elif e["target"] == node_id:
                out.add(e["source"])
        return out

    def step(self, delta: int) -> None:
        ids = self.visible_ids()
        if not ids:
            return
        at = ids.index(self.current) if self.current in ids else -1
        self.select(ids[(at + delta) % len(ids)])

    def reset_view(self) -> None:
        self.orbit = engine.Orbit()
        self.update()

    def zoom(self, factor: float) -> None:
        self.orbit = engine.zoom_orbit(self.orbit, factor)
        self.update()

    # ----- projection --------------------------------------------------------------------------

    def project_all(self) -> None:
        width, height = float(self.width()), float(self.height())
        self._projected = {
            i: engine.project(self.positions[i], self.orbit, width, height) for i in self.ids
        }
        self._radii = {
            i: (0.034 if self.nodes[i]["kind"] == "pipeline" else 0.026) * p.scale + 5
            for i, p in self._projected.items()
        }

    def node_at(self, x: float, y: float) -> str | None:
        self.project_all()
        visible = self.visible_ids()
        items = [self._projected[i] for i in visible]
        index = engine.pick(items, [self._radii[i] for i in visible], x, y)
        return visible[index] if index >= 0 else None

    # ----- input -------------------------------------------------------------------------------

    def mousePressEvent(self, event: QMouseEvent) -> None:
        self.setFocus()
        self._dragging = True
        self._last = event.position()
        self._moved = 0.0
        self._last_time = time.monotonic()
        self._sync_timer()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        pos = event.position()
        if self._dragging:
            now = time.monotonic()
            dx, dy = pos.x() - self._last.x(), pos.y() - self._last.y()
            self._moved += abs(dx) + abs(dy)
            self.orbit = engine.drag_orbit(self.orbit, dx, dy, max(now - self._last_time, 0.008))
            self._last, self._last_time = pos, now
            self.update()
            return
        hovered = self.node_at(pos.x(), pos.y())
        if hovered != self.hover:
            self.hover = hovered
            self.update()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        self._dragging = False
        if self._moved < 6:
            hit = self.node_at(event.position().x(), event.position().y())
            if hit is not None:
                self.select(hit)
        self._sync_timer()
        self.update()

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:
        del event
        self.reset_view()

    def wheelEvent(self, event: QWheelEvent) -> None:
        self.zoom(math.exp(-event.angleDelta().y() * 0.0012))
        event.accept()

    def leaveEvent(self, event: Any) -> None:
        del event
        if self.hover is not None:
            self.hover = None
            self.update()

    def keyPressEvent(self, event: QKeyEvent) -> None:
        key = Qt.Key(event.key())
        nudge = {
            Qt.Key.Key_Left: (-1.4, 0.0),
            Qt.Key.Key_Right: (1.4, 0.0),
            Qt.Key.Key_Up: (0.0, -1.1),
            Qt.Key.Key_Down: (0.0, 1.1),
        }.get(key)
        if nudge is not None:
            from dataclasses import replace

            self.orbit = replace(self.orbit, yaw_velocity=nudge[0], pitch_velocity=nudge[1])
            self._sync_timer()
            self._timer.start()
            self.update()
        elif key in (Qt.Key.Key_Plus, Qt.Key.Key_Equal):
            self.zoom(0.85)
        elif key in (Qt.Key.Key_Minus, Qt.Key.Key_Underscore):
            self.zoom(1.18)
        elif key == Qt.Key.Key_0:
            self.reset_view()
        elif key == Qt.Key.Key_BracketRight:
            self.step(1)
        elif key == Qt.Key.Key_BracketLeft:
            self.step(-1)
        else:
            super().keyPressEvent(event)

    # ----- drawing -----------------------------------------------------------------------------

    def paintEvent(self, event: QPaintEvent) -> None:
        del event
        palette = theme.current()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), palette.color(palette.surface))
        self.project_all()
        near, far = self.orbit.distance - 1.1, self.orbit.distance + 1.1
        shown = set(self.visible_ids())
        selected = self.current
        neighbours = self.neighbours(selected) if selected else set()
        ink, muted = palette.color(palette.ink), palette.color(palette.muted)
        accent, accent2 = palette.color(palette.accent), palette.color(palette.series[1])
        flow = palette.color(palette.series[2])
        self._draw_guides(painter, muted)
        now = time.monotonic()
        for e in self.edges:
            a, b = e["source"], e["target"]
            if a not in shown or b not in shown:
                continue
            qa, qb = self._projected[a], self._projected[b]
            if not (qa.visible and qb.visible):
                continue
            touches = selected in (a, b)
            fade = engine.depth_alpha((qa.depth + qb.depth) / 2, near, far, 0.3)
            colour = QColor(accent if touches else flow if e["kind"] == "feeds" else muted)
            colour.setAlphaF(0.95 if touches else 0.30 * fade)
            pen = QPen(colour, 2.6 if e["kind"] == "feeds" else 2.0 if touches else 1.0)
            pen.setStyle(
                Qt.PenStyle.DotLine
                if e["kind"] == "baseline_for"
                else Qt.PenStyle.DashLine
                if e["kind"] == "alternative_to"
                else Qt.PenStyle.SolidLine
            )
            painter.setPen(pen)
            painter.drawLine(QPointF(qa.x, qa.y), QPointF(qb.x, qb.y))
            if e["kind"] == "feeds" and not self.reduce_motion:
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(accent2)
                for k in range(3):
                    w = engine.along(self.positions[a], self.positions[b], now * 0.35 + k / 3)
                    q = engine.project(w, self.orbit, float(self.width()), float(self.height()))
                    painter.drawEllipse(QPointF(q.x, q.y), 2.6, 2.6)
        labelled: list[tuple[str, bool]] = []
        for order_index in engine.depth_order([self._projected[i] for i in self.ids]):
            node_id = self.ids[order_index]
            q = self._projected[node_id]
            if not q.visible or node_id not in shown:
                continue
            self._draw_node(painter, node_id, q, node_id == selected, near, far, palette)
            if node_id == selected or node_id == self.hover or node_id in neighbours:
                labelled.append((node_id, True))
            elif self.labels == "all" and q.depth < self.orbit.distance:
                labelled.append((node_id, False))
        if self.labels != "none":
            self._draw_families(painter, muted, near, far)
        for node_id, strong in labelled:
            q = self._projected[node_id]
            alpha = 1.0 if strong else 0.7 * engine.depth_alpha(q.depth, near, far, 0.3)
            self._draw_label(
                painter,
                self.nodes[node_id]["label"],
                q,
                self._radii[node_id],
                alpha,
                ink if strong else muted,
                palette,
            )
        if self.hasFocus():
            painter.setPen(QPen(accent, 2))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRoundedRect(QRectF(self.rect()).adjusted(1, 1, -1, -1), 6, 6)

    def _draw_guides(self, painter: QPainter, colour: QColor) -> None:
        guide = QColor(colour)
        guide.setAlphaF(0.12)
        painter.setPen(QPen(guide, 1))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        for axis in (0, 1, 2):
            points = []
            for k in range(73):
                t = k / 72 * 2 * math.pi
                c, s = math.cos(t), math.sin(t)
                p: engine.Vec3 = (
                    (0.0, c, s) if axis == 0 else (c, 0.0, s) if axis == 1 else (c, s, 0.0)
                )
                q = engine.project(p, self.orbit, float(self.width()), float(self.height()))
                points.append(QPointF(q.x, q.y))
            painter.drawPolyline(QPolygonF(points))

    def _draw_node(
        self,
        painter: QPainter,
        node_id: str,
        q: engine.Projected,
        is_selected: bool,
        near: float,
        far: float,
        palette: theme.Palette,
    ) -> None:
        node = self.nodes[node_id]
        r = self._radii[node_id] - 5
        painter.setOpacity(1.0 if is_selected else engine.depth_alpha(q.depth, near, far, 0.32))
        outline = QPen(
            palette.color(palette.series[1] if is_selected else palette.ink),
            3 if is_selected else 1.5,
        )
        painter.setPen(outline)
        filled = node["kind"] == "model" and node["status"] == "implemented"
        painter.setBrush(
            palette.color(palette.accent_fill) if filled else palette.color(palette.raised)
        )
        centre = QPointF(q.x, q.y)
        if node["kind"] == "baseline":
            s = r * 1.2
            painter.drawPolygon(
                QPolygonF(
                    [
                        QPointF(q.x, q.y - s),
                        QPointF(q.x + s, q.y),
                        QPointF(q.x, q.y + s),
                        QPointF(q.x - s, q.y),
                    ]
                )
            )
        elif node["kind"] == "pipeline":
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawEllipse(centre, r * 1.35, r * 1.35)
        elif node["status"] == "existing":
            painter.drawRect(QRectF(q.x - r, q.y - r, 2 * r, 2 * r))
        else:
            painter.drawEllipse(centre, r, r)
        painter.setOpacity(1.0)

    def _draw_families(self, painter: QPainter, colour: QColor, near: float, far: float) -> None:
        font = painter.font()
        font.setBold(True)
        font.setPixelSize(max(9, round(10 * theme.text_scale())))
        painter.setFont(font)
        for family, position in self.families:
            if family in self.hidden_families:
                continue
            q = engine.project(position, self.orbit, float(self.width()), float(self.height()))
            if not q.visible:
                continue
            painter.setOpacity(0.55 * engine.depth_alpha(q.depth, near, far, 0.35))
            painter.setPen(colour)
            painter.drawText(
                QRectF(q.x - 60, q.y - 8, 120, 16),
                int(Qt.AlignmentFlag.AlignCenter),
                family.upper(),
            )
        painter.setOpacity(1.0)
        font.setBold(False)
        painter.setFont(font)

    def _draw_label(
        self,
        painter: QPainter,
        text: str,
        q: engine.Projected,
        radius: float,
        alpha: float,
        colour: QColor,
        palette: theme.Palette,
    ) -> None:
        font = painter.font()
        font.setPixelSize(max(9, round(12 * theme.text_scale())))
        painter.setFont(font)
        metrics = QFontMetricsF(font)
        shown = text if len(text) <= 34 else text[:33] + "…"
        width = metrics.horizontalAdvance(shown) + 12
        right = q.x + radius + 4
        x = right if right + width <= self.width() - 4 else q.x - radius - 4 - width
        box = QRectF(max(4.0, x), min(max(4.0, q.y - 10), self.height() - 24.0), width, 20)
        painter.setOpacity(alpha)
        background = palette.color(palette.page, 0.88)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(background)
        painter.drawRoundedRect(box, 4, 4)
        painter.setPen(colour)
        painter.drawText(box, int(Qt.AlignmentFlag.AlignCenter), shown)
        painter.setOpacity(1.0)
