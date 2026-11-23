"""Colours, type and the style sheet.

The palette is the data-visualisation method's reference palette, used unchanged: the chrome
(surfaces, ink, hairlines) and the eight categorical hues in their fixed order, in a light and a
dark set that are each *selected* for their surface rather than inverted. It was run through the
method's validator in both modes (categorical order: worst adjacent colour-blind separation
9.1 light / 8.4 dark in OKLab x100 against a target of 8; worst adjacent normal-vision
separation 19.6 / 19.3 against a floor of 15). In light mode three hues (aqua, yellow, magenta)
sit under 3:1 against the surface, which the method treats as a *relief required* result: every
chart therefore carries a legend, direct labels and a table view, so no value is readable by
colour alone.

Text uses text tokens, never a series colour. `muted` (3.5:1 on the light surface) is used for
nothing a person needs to read; axis labels and captions use the secondary ink (7.7:1).
"""

from __future__ import annotations

import string
from dataclasses import dataclass

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication

MODES = ("system", "dark", "light")


@dataclass(frozen=True, slots=True)
class Palette:
    name: str
    page: str
    sidebar: str
    surface: str
    raised: str
    input_background: str
    hover: str
    ink: str
    ink2: str
    muted: str
    grid: str
    baseline: str
    border: tuple[int, int, int, int]
    border_strong: tuple[int, int, int, int]
    accent: str
    accent_fill: str
    accent_fill_hover: str
    on_accent: str
    series: tuple[str, ...]
    good: str
    warning: str
    serious: str
    critical: str
    good_text: str

    def color(self, value: str, alpha: float = 1.0) -> QColor:
        color = QColor(value)
        color.setAlphaF(alpha)
        return color

    @property
    def border_color(self) -> QColor:
        return QColor(*self.border)

    def series_color(self, index: int) -> QColor:
        """Categorical colour `index`, in the fixed order. There is no ninth: a ninth series is
        folded or faceted by the caller, never given a generated hue."""
        return QColor(self.series[index % len(self.series)])

    def tone(self, tone: str) -> str:
        return {
            "good": self.good,
            "warn": self.warning,
            "serious": self.serious,
            "bad": self.critical,
            "accent": self.accent,
        }.get(tone, self.muted)


LIGHT = Palette(
    name="light",
    page="#f9f9f7",
    sidebar="#f1f1ee",
    surface="#fcfcfb",
    raised="#f3f3f0",
    input_background="#ffffff",
    hover="#ebebe7",
    ink="#0b0b0b",
    ink2="#52514e",
    muted="#898781",
    grid="#e1e0d9",
    baseline="#c3c2b7",
    border=(11, 11, 11, 26),
    border_strong=(11, 11, 11, 64),
    accent="#2a78d6",
    accent_fill="#1c5cab",
    accent_fill_hover="#184f95",
    on_accent="#ffffff",
    series=("#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#6250d6", "#e34948"),
    good="#0ca30c",
    warning="#fab219",
    serious="#ec835a",
    critical="#d03b3b",
    good_text="#006300",
)

DARK = Palette(
    name="dark",
    page="#0d0d0d",
    sidebar="#131312",
    surface="#1a1a19",
    raised="#242422",
    input_background="#121211",
    hover="#2c2c2a",
    ink="#f0efec",
    ink2="#c3c2b7",
    muted="#898781",
    grid="#2c2c2a",
    baseline="#383835",
    border=(255, 255, 255, 26),
    border_strong=(255, 255, 255, 56),
    accent="#3987e5",
    accent_fill="#256abf",
    accent_fill_hover="#1c5cab",
    on_accent="#ffffff",
    series=("#3987e5", "#d95926", "#199e70", "#c98500", "#d55181", "#008300", "#9085e9", "#e66767"),
    good="#0ca30c",
    warning="#fab219",
    serious="#ec835a",
    critical="#d03b3b",
    good_text="#0ca30c",
)

_current = DARK


def current() -> Palette:
    """The palette in force; custom-painted widgets read it each time they paint."""
    return _current


def palette_for(mode: str, app: QApplication | None = None) -> Palette:
    if mode == "dark":
        return DARK
    if mode == "light":
        return LIGHT
    scheme = (app or QApplication.instance()).styleHints().colorScheme()  # type: ignore[union-attr]
    return LIGHT if scheme == Qt.ColorScheme.Light else DARK


def _rgba(value: tuple[int, int, int, int]) -> str:
    r, g, b, a = value
    return f"rgba({r},{g},{b},{a / 255:.3f})"


_STYLE = string.Template(
    """
QWidget { color: $ink; font-size: 13px; }
QMainWindow, QWidget#root, QWidget[page="true"] { background: $page; }
QToolTip { background: $surface; color: $ink; border: 1px solid $baseline; padding: 4px 6px; }

QFrame#card { background: $surface; border: 1px solid $border; border-radius: 10px; }
QFrame#banner { background: $raised; border-bottom: 1px solid $border; }
QFrame#sidebar { background: $sidebar; border-right: 1px solid $border; }
QFrame#statusbar { background: $sidebar; border-top: 1px solid $border; }
QFrame#tile { background: $raised; border: 1px solid $border; border-radius: 8px; }
QToolButton[section="true"] { font-weight: 600; color: $ink; padding: 6px 4px; }
QToolButton[section="true"]:hover { background: transparent; color: $accent; }
QFrame#rule { background: $border; max-height: 1px; min-height: 1px; border: none; }

QLabel { background: transparent; }
QLabel[role="h1"] { font-size: 24px; font-weight: 600; }
QLabel[role="h2"] { font-size: 16px; font-weight: 600; }
QLabel[role="h3"] { font-size: 13px; font-weight: 600; }
QLabel[role="secondary"] { color: $ink2; }
QLabel[role="caption"] { color: $ink2; font-size: 12px; }
QLabel[role="metric"] { font-size: 22px; font-weight: 600; }
QLabel[role="hero"] { font-size: 40px; font-weight: 700; }
QLabel[role="error"] { color: $critical_text; font-size: 12px; }
QLabel[role="brand"] { font-size: 15px; font-weight: 700; letter-spacing: 1px; }

QLabel[tone] { border-radius: 10px; padding: 2px 10px; font-weight: 600; }
QLabel[tone="neutral"] { background: $wash_neutral; }
QLabel[tone="accent"] { background: $wash_accent; }
QLabel[tone="good"] { background: $wash_good; }
QLabel[tone="warn"] { background: $wash_warn; }
QLabel[tone="serious"] { background: $wash_serious; }
QLabel[tone="bad"] { background: $wash_bad; }

QPushButton { background: $raised; border: 1px solid $border_strong; border-radius: 6px;
  padding: 6px 14px; }
QPushButton:hover { background: $hover; }
QPushButton:pressed { background: $baseline; }
QPushButton:disabled { color: $muted; background: transparent; }
QPushButton:focus { border: 2px solid $accent; padding: 5px 13px; }
QPushButton[primary="true"] { background: $accent_fill; color: $on_accent;
  border: 1px solid $accent_fill; font-weight: 600; padding: 7px 18px; }
QPushButton[primary="true"]:hover { background: $accent_fill_hover; }
QPushButton[primary="true"]:disabled { background: $raised; color: $muted;
  border: 1px solid $border; }
QPushButton[danger="true"] { color: $critical_text; }
QPushButton[ghost="true"] { background: transparent; border: 1px solid transparent; color: $ink2; }
QPushButton[ghost="true"]:hover { background: $hover; }
QToolButton { background: transparent; border: 1px solid transparent; border-radius: 6px;
  padding: 4px 8px; color: $ink2; }
QToolButton[chip="true"] { border: 1px solid $border_strong; padding: 4px 12px; }
QToolButton:hover { background: $hover; }
QToolButton:checked { background: $wash_accent; color: $ink; border: 1px solid $accent; }
QToolButton:focus { border: 2px solid $accent; }

QLineEdit, QPlainTextEdit, QTextEdit, QDateEdit, QComboBox, QSpinBox {
  background: $input_background; border: 1px solid $border_strong; border-radius: 6px;
  padding: 5px 8px; selection-background-color: $accent_fill; selection-color: $on_accent; }
QLineEdit:focus, QPlainTextEdit:focus, QDateEdit:focus, QComboBox:focus { border: 2px solid $accent;
  padding: 4px 7px; }
QLineEdit:disabled, QDateEdit:disabled, QComboBox:disabled { color: $muted; background: $raised; }
QLineEdit[invalid="true"], QPlainTextEdit[invalid="true"], QDateEdit[invalid="true"] {
  border: 2px solid $critical; padding: 4px 7px; }
QComboBox::drop-down { border: none; width: 22px; }
QComboBox QAbstractItemView { background: $surface; color: $ink; border: 1px solid $baseline;
  selection-background-color: $accent_fill; selection-color: $on_accent; outline: none; }
QCheckBox { spacing: 8px; }
QCheckBox::indicator { width: 16px; height: 16px; border: 1px solid $border_strong;
  border-radius: 4px; background: $input_background; }
QCheckBox::indicator:checked { background: $accent_fill; border: 1px solid $accent_fill; }
QCheckBox:focus { color: $ink; }

QTabWidget::pane { border: none; border-top: 1px solid $border; }
QTabBar { background: transparent; }
QTabBar::tab { padding: 9px 16px; border: none; color: $ink2; background: transparent;
  border-bottom: 2px solid transparent; font-weight: 600; }
QTabBar::tab:hover { color: $ink; }
QTabBar::tab:selected { color: $ink; border-bottom: 2px solid $accent; }
QTabBar::tab:focus { color: $ink; }

QTableWidget, QTreeWidget, QListWidget, QTextBrowser { background: $surface;
  border: 1px solid $border; border-radius: 8px; gridline-color: $grid;
  alternate-background-color: $page; selection-background-color: $wash_accent;
  selection-color: $ink; outline: none; }
QTableWidget::item, QTreeWidget::item { padding: 3px 6px; }
QTableWidget::item:selected, QTreeWidget::item:selected { background: $wash_accent; color: $ink; }
QHeaderView { background: transparent; }
QHeaderView::section { background: $raised; color: $ink2; border: none;
  border-bottom: 1px solid $baseline; padding: 6px 8px; font-weight: 600; }
QTableCornerButton::section { background: $raised; border: none; }

QListWidget#nav { background: transparent; border: none; padding: 4px 0; }
QListWidget#nav::item { padding: 9px 14px; margin: 1px 10px; border-radius: 6px; color: $ink2;
  font-weight: 600; }
QListWidget#nav::item:hover { background: $hover; color: $ink; }
QListWidget#nav::item:selected { background: $wash_accent; color: $ink; }
QListWidget#list { padding: 4px; }
QListWidget#list::item { padding: 7px 10px; border-radius: 6px; }
QListWidget#list::item:hover { background: $hover; }
QListWidget#list::item:selected { background: $wash_accent; color: $ink; }

QScrollArea { background: transparent; border: none; }
QScrollBar:vertical { background: transparent; width: 12px; margin: 2px; }
QScrollBar::handle:vertical { background: $baseline; border-radius: 4px; min-height: 28px; }
QScrollBar::handle:vertical:hover { background: $muted; }
QScrollBar:horizontal { background: transparent; height: 12px; margin: 2px; }
QScrollBar::handle:horizontal { background: $baseline; border-radius: 4px; min-width: 28px; }
QScrollBar::add-line, QScrollBar::sub-line { width: 0; height: 0; }
QScrollBar::add-page, QScrollBar::sub-page { background: transparent; }

QProgressBar { background: $raised; border: none; border-radius: 4px; max-height: 8px;
  min-height: 8px; }
QProgressBar::chunk { background: $accent; border-radius: 4px; }
QSplitter::handle { background: transparent; }
QGroupBox { border: 1px solid $border; border-radius: 8px; margin-top: 10px; padding-top: 10px; }
QGroupBox::title { subcontrol-origin: margin; left: 12px; padding: 0 6px; color: $ink2;
  font-weight: 600; }
QMessageBox { background: $surface; }

QMenuBar { background: $sidebar; border-bottom: 1px solid $border; }
QMenuBar::item { background: transparent; padding: 4px 10px; }
QMenuBar::item:selected, QMenuBar::item:pressed { background: $hover; }
QMenu { background: $surface; border: 1px solid $border_strong; padding: 4px 0; }
QMenu::item { padding: 6px 24px 6px 28px; }
QMenu::item:selected { background: $accent_fill; color: $on_accent; }
QMenu::item:disabled { color: $muted; }
QMenu::separator { height: 1px; background: $border; margin: 4px 8px; }
QMenu::indicator { left: 8px; width: 14px; height: 14px; }
"""
)


def stylesheet(palette: Palette) -> str:
    wash = {
        "neutral": palette.color(palette.ink2, 0.14),
        "accent": palette.color(palette.accent, 0.20),
        "good": palette.color(palette.good, 0.20),
        "warn": palette.color(palette.warning, 0.24),
        "serious": palette.color(palette.serious, 0.22),
        "bad": palette.color(palette.critical, 0.20),
    }

    def css(color: QColor) -> str:
        return f"rgba({color.red()},{color.green()},{color.blue()},{color.alphaF():.3f})"

    return _STYLE.substitute(
        ink=palette.ink,
        ink2=palette.ink2,
        muted=palette.muted,
        page=palette.page,
        sidebar=palette.sidebar,
        surface=palette.surface,
        raised=palette.raised,
        input_background=palette.input_background,
        hover=palette.hover,
        grid=palette.grid,
        baseline=palette.baseline,
        border=_rgba(palette.border),
        border_strong=_rgba(palette.border_strong),
        accent=palette.accent,
        accent_fill=palette.accent_fill,
        accent_fill_hover=palette.accent_fill_hover,
        on_accent=palette.on_accent,
        critical=palette.critical,
        critical_text="#d03b3b" if palette.name == "light" else "#e66767",
        wash_neutral=css(wash["neutral"]),
        wash_accent=css(wash["accent"]),
        wash_good=css(wash["good"]),
        wash_warn=css(wash["warn"]),
        wash_serious=css(wash["serious"]),
        wash_bad=css(wash["bad"]),
    )


def qt_palette(palette: Palette) -> QPalette:
    """The theme's colours as a Qt palette.

    The style sheet sets every widget's text colour, but only some widgets' backgrounds; the rest
    (a menu bar, a file dialog, a calendar pop-up, a combo box's list) are painted from the Qt
    palette, which by default is the desktop's. Dark ink on a dark desktop's menu bar is what that
    looked like when this was missing. Giving the application the theme's palette makes the two
    agree whatever the desktop is set to.
    """
    result = QPalette()
    roles = {
        QPalette.ColorRole.Window: palette.page,
        QPalette.ColorRole.WindowText: palette.ink,
        QPalette.ColorRole.Base: palette.input_background,
        QPalette.ColorRole.AlternateBase: palette.raised,
        QPalette.ColorRole.Text: palette.ink,
        QPalette.ColorRole.Button: palette.raised,
        QPalette.ColorRole.ButtonText: palette.ink,
        QPalette.ColorRole.BrightText: palette.on_accent,
        QPalette.ColorRole.Highlight: palette.accent_fill,
        QPalette.ColorRole.HighlightedText: palette.on_accent,
        QPalette.ColorRole.ToolTipBase: palette.surface,
        QPalette.ColorRole.ToolTipText: palette.ink,
        QPalette.ColorRole.PlaceholderText: palette.ink2,
        QPalette.ColorRole.Link: palette.accent,
        QPalette.ColorRole.LinkVisited: palette.accent,
    }
    for role, value in roles.items():
        result.setColor(role, QColor(value))
    for role in (
        QPalette.ColorRole.WindowText,
        QPalette.ColorRole.Text,
        QPalette.ColorRole.ButtonText,
    ):
        result.setColor(QPalette.ColorGroup.Disabled, role, QColor(palette.muted))
    return result


def apply_theme(app: QApplication, mode: str = "system") -> Palette:
    """Style the whole application; returns the palette now in force."""
    global _current
    _current = palette_for(mode, app)
    # Each call re-polishes every widget that exists, which is slow once there are many; and they
    # change nothing if the style, the palette and the sheet are already the ones asked for.
    if app.style().objectName().lower() != "fusion":
        app.setStyle("Fusion")  # honours the style sheet the same way on every platform
    colors = qt_palette(_current)
    if app.palette() != colors:
        app.setPalette(colors)
    sheet = stylesheet(_current)
    if app.styleSheet() != sheet:
        app.setStyleSheet(sheet)
    return _current


def contrast_ratio(foreground: str, background: str) -> float:
    """WCAG 2 contrast ratio of two `#rrggbb` colours (used by the tests and the palette check)."""

    def luminance(hex_color: str) -> float:
        r, g, b = (int(hex_color.lstrip("#")[i : i + 2], 16) / 255 for i in (0, 2, 4))
        linear = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in (r, g, b)]
        return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]

    high, low = sorted((luminance(foreground), luminance(background)), reverse=True)
    return (high + 0.05) / (low + 0.05)
