"""Settings: how the window looks and moves, kept in a small file in the state directory.

Every control applies at once (nothing to confirm) and is saved. The choices: the colour theme, a
high-contrast variant of it, the text size (the whole application, charts included), reduced
motion (the 3D web stops turning on its own and the flowing dots along pipelines are not drawn),
and how the Atlas opens. The window owns the settings; this page shows them and reports
what the person chose.
"""

from __future__ import annotations

from dataclasses import asdict
from pathlib import Path

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QGridLayout,
    QHBoxLayout,
    QPushButton,
    QRadioButton,
    QVBoxLayout,
    QWidget,
)

from prometheus.desktop import settings as store
from prometheus.desktop.settings import DesktopSettings
from prometheus.desktop.ui.pages.base import PageBase
from prometheus.desktop.ui.widgets import Card, make_label

THEME_LABELS = {"system": "Follow the system", "dark": "Dark", "light": "Light"}
VIEW_LABELS = {"3d": "3D web", "2d": "2D web"}
LABEL_LABELS = {"selected": "Selected only", "all": "All", "none": "None"}


class SettingsPage(PageBase):
    changed = Signal(object)
    """Emitted with a new `DesktopSettings` whenever a control is used."""

    def __init__(
        self, settings: DesktopSettings, state_dir: Path, parent: QWidget | None = None
    ) -> None:
        super().__init__(
            "Settings",
            "Make the window fit how you see and move. Every change applies at once and is saved.",
            parent,
        )
        self.settings = settings
        self.state_dir = state_dir
        self._groups: dict[str, QButtonGroup] = {}
        self._options: dict[str, tuple[object, ...]] = {}
        self._checks: dict[str, QCheckBox] = {}
        self._syncing = False

        grid = QGridLayout()
        grid.setSpacing(14)
        grid.addWidget(
            self._radio_card("theme", "Colour theme", store.THEMES, THEME_LABELS.get), 0, 0
        )
        grid.addWidget(
            self._radio_card(
                "text_scale",
                "Text size",
                store.TEXT_SCALES,
                lambda v: f"{round(float(v) * 100)}%",
            ),
            0,
            1,
        )
        access = self._card("Accessibility")
        access_box = QVBoxLayout()
        self._check(
            access_box,
            "high_contrast",
            "High contrast",
            "Pure black or white, strong lines, a stronger accent.",
        )
        self._check(
            access_box,
            "reduce_motion",
            "Reduce motion",
            "Nothing moves on its own; no flowing dots.",
        )
        access.body.addLayout(access_box)
        access.body.addStretch(1)
        grid.addWidget(access, 1, 0)
        atlas = self._card("Atlas")
        atlas_box = QVBoxLayout()
        self._add_group(atlas_box, "atlas_view", "Opens as", store.ATLAS_VIEWS, VIEW_LABELS.get)
        self._check(
            atlas_box, "auto_rotate", "Turn the 3D web slowly", "Never while motion is reduced."
        )
        self._add_group(atlas_box, "labels_3d", "Labels in 3D", store.LABELS, LABEL_LABELS.get)
        atlas.body.addLayout(atlas_box)
        atlas.body.addStretch(1)
        grid.addWidget(atlas, 1, 1)
        self.content.addLayout(grid)

        footer = QHBoxLayout()
        self.reset_button = QPushButton("Reset everything")
        self.reset_button.clicked.connect(self._reset)
        self.where = make_label("", "caption")
        footer.addWidget(self.reset_button)
        footer.addWidget(self.where, 1)
        self.content.addLayout(footer)
        self.content.addStretch(1)
        self.show_settings(settings)

    # ----- building ----------------------------------------------------------------------------

    @staticmethod
    def _card(title: str) -> Card:
        card = Card()
        card.body.addWidget(make_label(title, "h2"))
        return card

    def _radio_card(self, name: str, title: str, values: tuple[object, ...], label: object) -> Card:
        card = self._card(title)
        box = QVBoxLayout()
        self._add_group(box, name, None, values, label)
        card.body.addLayout(box)
        card.body.addStretch(1)
        return card

    def _add_group(
        self,
        box: QVBoxLayout,
        name: str,
        title: str | None,
        values: tuple[object, ...],
        label: object,
    ) -> None:
        if title:
            box.addWidget(make_label(title, "caption"))
        group = QButtonGroup(self)
        group.setExclusive(True)
        for index, value in enumerate(values):
            text = label(value) if callable(label) else str(value)
            button = QRadioButton(str(text))
            button.setAccessibleName(f"{title or name}: {text}")
            group.addButton(button, index)
            box.addWidget(button)
        group.idClicked.connect(self._radio_clicked)
        self._groups[name] = group
        self._options[name] = values

    def _check(self, box: QVBoxLayout, name: str, text: str, hint: str) -> None:
        check = QCheckBox(text)
        check.setAccessibleName(text)
        check.setAccessibleDescription(hint)
        check.setToolTip(hint)
        check.toggled.connect(self._check_toggled)
        check.setProperty("setting", name)
        self._checks[name] = check
        box.addWidget(check)
        box.addWidget(make_label(hint, "caption"))

    # ----- state -------------------------------------------------------------------------------

    def show_settings(self, settings: DesktopSettings) -> None:
        """Make the controls say what `settings` says (without announcing a change)."""
        self.settings = settings
        self._syncing = True
        try:
            values = asdict(settings)
            for name, group in self._groups.items():
                options = self._options[name]
                button = group.button(options.index(values[name]))
                if button is not None:
                    button.setChecked(True)
            for name, check in self._checks.items():
                check.setChecked(bool(values[name]))
            self.where.setText(f"Saved in {store.settings_path(self.state_dir)}")
        finally:
            self._syncing = False

    def _radio_clicked(self, index: int) -> None:
        if self._syncing:
            return
        sender = self.sender()
        for name, group in self._groups.items():
            if group is sender:
                self._emit(**{name: self._options[name][index]})

    def _check_toggled(self, checked: bool) -> None:
        if self._syncing:
            return
        sender = self.sender()
        name = sender.property("setting") if sender is not None else None
        if isinstance(name, str):
            self._emit(**{name: checked})

    def _emit(self, **change: object) -> None:
        self.settings = self.settings.with_changes(**change)
        self.changed.emit(self.settings)

    def _reset(self) -> None:
        self.settings = store.DEFAULTS
        self.show_settings(self.settings)
        self.changed.emit(self.settings)
