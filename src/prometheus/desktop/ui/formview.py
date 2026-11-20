"""A form built from `FieldSpec`s: the editing half of `desktop.forms`.

`forms` decides *what* can be edited and parses what was typed; this module only gives each kind
of field a widget and reads the text back. Numbers, fractions, lists and text are plain line edits
on purpose: a spin box cannot hold a 32-bit seed, rounds a float to its own idea of a decimal
place, and hides the characters a person actually typed, which is what the error message needs to
talk about. Every editor reports problems next to itself, with a glyph and words (never a red
border alone).

Nested objects (a Money amount, a policy block) are collapsible sections, closed by default, and a
section that contains an error opens by itself.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from typing import Any

from PySide6.QtCore import QDate, Qt, Signal
from PySide6.QtGui import QFontDatabase
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDateEdit,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLineEdit,
    QPlainTextEdit,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from prometheus.desktop.forms import FieldSpec, Path, initial_values
from prometheus.desktop.ui.widgets import make_label, repolish

COLUMNS = 3
DATE_FORMAT = "yyyy-MM-dd"


class _Editor:
    """One field's widget, how to read it, how to set it, and where its error shows."""

    def __init__(
        self,
        spec: FieldSpec,
        widget: QWidget,
        read: Callable[[], Any],
        write: Callable[[Any], None],
        signal_connect: Connect,
        error_label: Any,
        gate: QCheckBox | None,
    ) -> None:
        self.spec, self.widget, self._read, self._write = spec, widget, read, write
        self.connect_changed = signal_connect
        self.error_label, self.gate = error_label, gate

    def value(self) -> Any:
        if self.gate is not None and not self.gate.isChecked():
            return None
        return self._read()

    def set_value(self, value: Any) -> None:
        if self.gate is not None:
            self.gate.setChecked(value is not None)
            self.widget.setEnabled(value is not None)
            if value is None:
                self._write(self.spec.fallback)
                return
        self._write(value)

    def show_error(self, message: str | None) -> None:
        invalid = message is not None
        self.widget.setProperty("invalid", invalid)
        repolish(self.widget)
        self.error_label.setText(f"✕  {self.spec.label} {message}" if message else "")
        self.error_label.setVisible(invalid)


def _text(value: Any) -> str:
    return "" if value is None else str(value)


Connect = Callable[[Callable[..., None]], None]
Built = tuple[QWidget, Callable[[], Any], Callable[[Any], None], Connect]


def _build_bool(spec: FieldSpec) -> Built:
    check = QCheckBox("on")

    def write(value: Any) -> None:
        check.setChecked(bool(value))

    def connect(slot: Callable[..., None]) -> None:
        check.toggled.connect(slot)

    return check, check.isChecked, write, connect


def _build_choice(spec: FieldSpec) -> Built:
    combo = QComboBox()
    combo.addItems(list(spec.choices))

    def write(value: Any) -> None:
        combo.setCurrentText(_text(value))

    def connect(slot: Callable[..., None]) -> None:
        combo.currentTextChanged.connect(slot)

    return combo, combo.currentText, write, connect


def _build_date(spec: FieldSpec) -> Built:
    date = QDateEdit()
    date.setCalendarPopup(True)
    date.setDisplayFormat(DATE_FORMAT)
    date.setDateRange(QDate(1800, 1, 1), QDate(2200, 12, 31))

    def read() -> str:
        return date.date().toString(DATE_FORMAT)

    def write(value: Any) -> None:
        date.setDate(QDate.fromString(_text(value), DATE_FORMAT))

    def connect(slot: Callable[..., None]) -> None:
        date.dateChanged.connect(slot)

    return date, read, write, connect


def _build_json(spec: FieldSpec) -> Built:
    box = QPlainTextEdit()
    box.setFont(QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont))
    box.setMinimumHeight(110)
    box.setTabChangesFocus(True)

    def write(value: Any) -> None:
        box.setPlainText(_text(value))

    def connect(slot: Callable[..., None]) -> None:
        box.textChanged.connect(slot)

    return box, box.toPlainText, write, connect


def _build_line(spec: FieldSpec) -> Built:
    line = QLineEdit()
    if spec.kind in ("int", "float"):
        line.setAlignment(Qt.AlignmentFlag.AlignRight)

    def write(value: Any) -> None:
        line.setText(_text(value))

    def connect(slot: Callable[..., None]) -> None:
        line.textChanged.connect(slot)

    return line, line.text, write, connect


_BUILDERS: dict[str, Callable[[FieldSpec], Built]] = {
    "bool": _build_bool,
    "choice": _build_choice,
    "date": _build_date,
    "json": _build_json,
}


def _limits_hint(spec: FieldSpec) -> str:
    low = (
        "" if spec.minimum is None else f"{'>' if spec.exclusive_minimum else '≥'} {spec.minimum:g}"
    )
    high = "" if spec.maximum is None else f"≤ {spec.maximum:g}"
    return " and ".join(part for part in (low, high) if part)


class Section(QFrame):
    """A collapsible group of fields."""

    def __init__(self, title: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        self.toggle = QToolButton()
        self.toggle.setProperty("section", True)
        self.toggle.setCheckable(True)
        self.toggle.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
        self.toggle.setAccessibleName(f"Show or hide {title}")
        self._title = title
        self.toggle.toggled.connect(self._set_open)
        layout.addWidget(self.toggle)
        self.content = QWidget()
        self.grid = QGridLayout(self.content)
        self.grid.setContentsMargins(16, 0, 0, 0)
        self.grid.setHorizontalSpacing(14)
        self.grid.setVerticalSpacing(10)
        layout.addWidget(self.content)
        self._set_open(False)

    def _set_open(self, opened: bool) -> None:
        self.content.setVisible(opened)
        self.toggle.setText(f"{'▾' if opened else '▸'}  {self._title}")

    def open(self) -> None:
        self.toggle.setChecked(True)

    @property
    def is_open(self) -> bool:
        return self.toggle.isChecked()


class FormView(QWidget):
    """Editors for `specs`; `values()` returns what `forms.assemble` wants."""

    changed = Signal()

    def __init__(
        self, specs: Sequence[FieldSpec], parent: QWidget | None = None, *, columns: int = COLUMNS
    ) -> None:
        super().__init__(parent)
        self._columns = columns
        self._specs = tuple(specs)
        self._editors: dict[Path, _Editor] = {}
        self._sections: dict[Path, Section] = {}
        self._general_error = make_label("", "error")
        self._general_error.setVisible(False)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(12)
        outer.addWidget(self._general_error)
        scalars = [s for s in self._specs if s.kind != "group"]
        groups = [s for s in self._specs if s.kind == "group"]
        if scalars:
            holder = QWidget()
            grid = QGridLayout(holder)
            grid.setContentsMargins(0, 0, 0, 0)
            grid.setHorizontalSpacing(14)
            grid.setVerticalSpacing(10)
            for column in range(self._columns):
                grid.setColumnStretch(column, 1)
            self._fill_grid(grid, scalars)
            outer.addWidget(holder)
        for spec in groups:
            outer.addWidget(self._section(spec))
        outer.addStretch(1)

    # ------------------------------------------------------------------ building

    def _fill_grid(self, grid: QGridLayout, specs: Sequence[FieldSpec]) -> None:
        row = column = 0
        for spec in specs:
            wide = spec.kind == "json"
            if wide and column != 0:
                row, column = row + 1, 0
            cell = self._cell(spec)
            grid.addWidget(cell, row, column, 1, self._columns if wide else 1)
            column += self._columns if wide else 1
            if column >= self._columns:
                row, column = row + 1, 0

    def _section(self, spec: FieldSpec) -> Section:
        section = Section(spec.label)
        self._sections[spec.path] = section
        scalars = [child for child in spec.children if child.kind != "group"]
        for column in range(self._columns):
            section.grid.setColumnStretch(column, 1)
        self._fill_grid(section.grid, scalars)
        nested_row = section.grid.rowCount()
        for child in spec.children:
            if child.kind == "group":
                section.grid.addWidget(self._section(child), nested_row, 0, 1, self._columns)
                nested_row += 1
        return section

    def _cell(self, spec: FieldSpec) -> QWidget:
        cell = QWidget()
        layout = QVBoxLayout(cell)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(3)
        caption = make_label(spec.label, "caption", wrap=False)
        layout.addWidget(caption)
        editor = self._editor(spec)
        self._editors[spec.path] = editor
        if editor.gate is not None:
            row = QHBoxLayout()
            row.setSpacing(8)
            row.addWidget(editor.gate)
            row.addWidget(editor.widget, 1)
            layout.addLayout(row)
        else:
            layout.addWidget(editor.widget)
        layout.addWidget(editor.error_label)
        editor.connect_changed(self._notify)
        return cell

    def _editor(self, spec: FieldSpec) -> _Editor:
        error = make_label("", "error")
        error.setVisible(False)
        widget, read, write, connect = _BUILDERS.get(spec.kind, _build_line)(spec)
        widget.setAccessibleName(spec.label)
        hint = _limits_hint(spec)
        if hint:
            widget.setToolTip(f"{spec.label}: {hint}")
        gate: QCheckBox | None = None
        if spec.optional:
            gate = QCheckBox("set")
            gate.setAccessibleName(f"Use a value for {spec.label}")
            gate.toggled.connect(widget.setEnabled)
            gate.toggled.connect(self._notify)
        editor = _Editor(spec, widget, read, write, connect, error, gate)
        editor.set_value(spec.default)
        return editor

    def _notify(self, *_: object) -> None:
        self.changed.emit()

    # ------------------------------------------------------------------ using

    def paths(self) -> list[Path]:
        return list(self._editors)

    def editor_widget(self, path: Path) -> QWidget:
        return self._editors[path].widget

    def gate(self, path: Path) -> QCheckBox | None:
        return self._editors[path].gate

    def section(self, path: Path) -> Section:
        return self._sections[path]

    def values(self) -> dict[Path, Any]:
        return {path: editor.value() for path, editor in self._editors.items()}

    def set_values(self, values: Mapping[Path, Any]) -> None:
        for path, value in values.items():
            if path in self._editors:
                self._editors[path].set_value(value)
        self.set_errors({})

    def reset(self) -> None:
        self.set_values(initial_values(self._specs))

    def set_errors(self, errors: Mapping[Path, str]) -> None:
        for path, editor in self._editors.items():
            editor.show_error(errors.get(path))
        general = errors.get(())
        self._general_error.setText(f"✕  {general}" if general else "")
        self._general_error.setVisible(bool(general))
        for path in errors:
            for depth in range(1, len(path)):
                section = self._sections.get(path[:depth])
                if section is not None:
                    section.open()

    def error_texts(self) -> dict[Path, str]:
        return {
            path: editor.error_label.text()
            for path, editor in self._editors.items()
            if not editor.error_label.isHidden()
        }
