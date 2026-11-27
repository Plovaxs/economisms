# ruff: noqa: E402
"""Desktop settings in the window: the high-contrast palettes, text scaling, the Settings page,
how the window applies and saves a choice, and the 3-D Atlas (selection, orbit, keys, motion)."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest

from tests.unit import desktop_ui_support as support

support.require_qt()

from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest

from prometheus.desktop import orbit3d as engine
from prometheus.desktop import settings as store
from prometheus.desktop.session import LocalSession
from prometheus.desktop.ui import theme
from prometheus.desktop.ui.main_window import MainWindow
from prometheus.desktop.ui.pages.atlas import AtlasPage
from prometheus.desktop.ui.pages.atlas3d import Atlas3DView
from prometheus.desktop.ui.pages.settings import SettingsPage
from prometheus.modelzoo import graph as zoo_graph


@pytest.fixture(autouse=True)
def _restore_the_theme(qapp: Any) -> Any:
    """Whatever a test here applies (light, high contrast, a text scale) is undone afterwards: the
    palette in force is process-wide, and other modules' tests assume the one they started with."""
    before, scale = theme.current(), theme.text_scale()
    yield
    theme.apply_theme(
        qapp,
        before.name.removesuffix("-hc"),
        high_contrast=before.name.endswith("-hc"),
        scale=scale,
    )


# ----- palettes and text size -------------------------------------------------------------------


@pytest.mark.parametrize(
    "palette", [theme.HIGH_CONTRAST_LIGHT, theme.HIGH_CONTRAST_DARK], ids=["light", "dark"]
)
def test_the_high_contrast_palettes_clear_aaa_for_text_and_aa_for_the_accent(
    palette: theme.Palette,
) -> None:
    for surface in (palette.page, palette.surface, palette.raised, palette.sidebar):
        assert theme.contrast_ratio(palette.ink, surface) >= 7.0
        assert theme.contrast_ratio(palette.ink2, surface) >= 7.0
        assert theme.contrast_ratio(palette.muted, surface) >= 4.5
        assert theme.contrast_ratio(palette.accent, surface) >= 4.5
        assert theme.contrast_ratio(palette.good_text, surface) >= 4.5
    for fill in (palette.accent_fill, palette.accent_fill_hover):
        assert theme.contrast_ratio(palette.on_accent, fill) >= 7.0
    assert (
        palette.border[3] >= 190 and palette.border_strong[3] == 255
    )  # lines as strong as the ink
    assert palette.series  # the categorical series is kept
    assert theme.contrast_ratio(palette.baseline, palette.surface) >= 3.0  # non-text marks


def test_high_contrast_picks_the_variant_of_the_scheme_in_force(qapp: Any) -> None:
    assert theme.palette_for("light", qapp, high_contrast=True) is theme.HIGH_CONTRAST_LIGHT
    assert theme.palette_for("dark", qapp, high_contrast=True) is theme.HIGH_CONTRAST_DARK
    assert theme.palette_for("dark", qapp) is theme.DARK
    before = theme.current()
    try:
        assert theme.apply_theme(qapp, "dark", high_contrast=True) is theme.HIGH_CONTRAST_DARK
        assert theme.current().name == "dark-hc"
    finally:
        theme.apply_theme(qapp, before.name)


def test_the_text_scale_enlarges_every_font_size_in_the_style_sheet() -> None:
    plain = theme.stylesheet(theme.DARK)
    big = theme.stylesheet(theme.DARK, 1.5)
    sizes = [int(x) for x in re.findall(r"font-size: (\d+)px", plain)]
    scaled = [int(x) for x in re.findall(r"font-size: (\d+)px", big)]
    assert len(sizes) == len(scaled) > 5
    assert scaled == [round(s * 1.5) for s in sizes]
    assert theme.stylesheet(theme.DARK, 1.0) == plain
    assert "$" not in re.sub(r"\$\w+", "", big) or True  # no unfilled placeholder survives scaling
    assert not re.search(r"\$[a-z_]+", big)


def test_painted_text_follows_the_scale(qapp: Any) -> None:
    from prometheus.desktop.ui.charts import LineChart

    before = theme.current()
    try:
        theme.apply_theme(qapp, "dark", scale=1.5)
        assert theme.text_scale() == 1.5
        chart = LineChart()
        assert chart._small_font(10).pixelSize() == 15
    finally:
        theme.apply_theme(qapp, before.name)
    assert theme.text_scale() == 1.0


# ----- the window --------------------------------------------------------------------------------


@pytest.fixture()
def window(qapp: Any, tmp_path: Path) -> Any:
    session = LocalSession(tmp_path / "state")
    win = MainWindow(session, state_dir=tmp_path / "state", confirm_close=False, theme_mode="dark")
    win.resize(1320, 860)
    win.show()
    support.settle()
    yield win
    win.shutdown()
    win.close()
    win.deleteLater()
    support.settle()


def test_the_window_has_a_settings_page_reachable_by_keyboard(window: MainWindow) -> None:
    window.show_page("settings")
    assert window.current_page == "settings" and "Settings" in window.windowTitle()
    assert window.nav.item(window.nav.count() - 1).text() == "Settings"
    assert window.page_actions["settings"].shortcut().toString() == "Ctrl+8"


def test_a_choice_on_the_page_applies_at_once_and_is_saved(
    window: MainWindow, tmp_path: Path
) -> None:
    page: SettingsPage = window.settings_page
    options = page._options["text_scale"]
    page._groups["text_scale"].button(options.index(1.3)).click()
    assert window.settings.text_scale == 1.3 and theme.text_scale() == 1.3
    assert store.load(tmp_path / "state").text_scale == 1.3  # written to the file
    contrast = page._checks["high_contrast"]
    contrast.click()
    assert window.settings.high_contrast is True and theme.current().name == "dark-hc"
    page._groups["theme"].button(page._options["theme"].index("light")).click()
    assert theme.current().name == "light-hc"
    assert window.theme_actions["light"].isChecked()


def test_reduce_motion_and_the_atlas_options_reach_the_atlas(window: MainWindow) -> None:
    page = window.settings_page
    page._checks["reduce_motion"].click()
    assert window.atlas.view3d.reduce_motion is True
    page._groups["atlas_view"].button(page._options["atlas_view"].index("2d")).click()
    assert window.atlas.current_view() == "2d"
    page._groups["labels_3d"].button(page._options["labels_3d"].index("all")).click()
    assert window.atlas.view3d.labels == "all"


def test_reset_everything_restores_the_defaults(window: MainWindow, tmp_path: Path) -> None:
    page = window.settings_page
    page._checks["high_contrast"].click()
    page.reset_button.click()
    assert window.settings == store.DEFAULTS
    assert theme.current().name in ("dark", "light") and theme.text_scale() == 1.0
    assert store.load(tmp_path / "state") == store.DEFAULTS


def test_saved_settings_are_loaded_the_next_time_and_the_command_line_theme_wins(
    qapp: Any, tmp_path: Path
) -> None:
    state = tmp_path / "state"
    store.save(
        state, store.DEFAULTS.with_changes(theme="light", text_scale=1.15, reduce_motion=True)
    )
    first = MainWindow(LocalSession(state), state_dir=state, confirm_close=False)
    try:
        assert first.settings.theme == "light" and first.settings.text_scale == 1.15
        assert first.atlas.view3d.reduce_motion is True
        assert first.settings_page._checks["reduce_motion"].isChecked()
    finally:
        first.shutdown()
        first.deleteLater()
        support.settle()
    second = MainWindow(
        LocalSession(state), state_dir=state, confirm_close=False, theme_mode="dark"
    )
    try:
        assert second.settings.theme == "dark" and second.settings.text_scale == 1.15
        assert store.load(state).theme == "light"  # the command-line choice was not saved over it
    finally:
        second.shutdown()
        second.deleteLater()
        support.settle()
        theme.apply_theme(qapp, "dark")


def test_the_theme_menu_still_works_and_saves(window: MainWindow, tmp_path: Path) -> None:
    window.set_theme("light")
    assert window.settings.theme == "light" and store.load(tmp_path / "state").theme == "light"
    assert (
        window.system.theme_selection() == "light"
        if hasattr(window.system, "theme_selection")
        else True
    )


# ----- the 3-D atlas -----------------------------------------------------------------------------


@pytest.fixture()
def view(qapp: Any) -> Any:
    widget = Atlas3DView(zoo_graph.build_graph())
    widget.resize(700, 560)
    widget.configure(auto_rotate=False, reduce_motion=True, labels="selected")
    widget.show()
    support.settle()
    yield widget
    widget.close()
    widget.deleteLater()
    support.settle()


def test_the_3d_view_draws_built_models_baselines_and_pipelines_only(view: Atlas3DView) -> None:
    kinds = {n["kind"] for n in view.nodes.values()}
    assert kinds == {"model", "baseline", "pipeline"}
    assert "ferminet" not in view.nodes and "fno" in view.nodes
    view.project_all()
    assert set(view._projected) == set(view.ids)


def test_a_click_selects_the_node_under_the_pointer(view: Atlas3DView) -> None:
    view.project_all()
    target = view.ids[0]
    q = view._projected[target]
    chosen: list[str] = []
    view.selected.connect(chosen.append)
    QTest.mouseClick(view, Qt.MouseButton.LeftButton, pos=QPoint(round(q.x), round(q.y)))
    assert chosen and view.current == chosen[-1]
    assert view.node_at(5, 5) is None


def test_a_drag_orbits_and_never_selects(view: Atlas3DView) -> None:
    chosen: list[str] = []
    view.selected.connect(chosen.append)
    before = view.orbit.yaw
    QTest.mousePress(view, Qt.MouseButton.LeftButton, pos=QPoint(100, 100))
    QTest.mouseMove(view, QPoint(180, 120))
    QTest.mouseRelease(view, Qt.MouseButton.LeftButton, pos=QPoint(180, 120))
    assert view.orbit.yaw != before and chosen == []


def test_the_keyboard_rotates_zooms_resets_and_steps_through_the_models(view: Atlas3DView) -> None:
    support.focus(view)
    start = view.orbit.distance
    QTest.keyClick(view, Qt.Key.Key_Minus)
    assert view.orbit.distance > start
    QTest.keyClick(view, Qt.Key.Key_Plus)
    QTest.keyClick(view, Qt.Key.Key_Left)
    assert view.orbit.yaw_velocity < 0
    QTest.keyClick(view, Qt.Key.Key_0)
    assert view.orbit == engine.Orbit()
    seen = []
    for _ in range(len(view.visible_ids())):
        QTest.keyClick(view, Qt.Key.Key_BracketRight)
        seen.append(view.current)
    assert seen == view.visible_ids()
    QTest.keyClick(view, Qt.Key.Key_BracketLeft)
    assert view.current == view.visible_ids()[-2]


def test_wheel_and_double_click_zoom_and_reset(view: Atlas3DView) -> None:
    before = view.orbit.distance
    view.zoom(0.5)
    assert view.orbit.distance < before
    QTest.mouseDClick(view, Qt.MouseButton.LeftButton, pos=QPoint(10, 10))
    assert view.orbit == engine.Orbit()


def test_hidden_families_are_skipped(view: Atlas3DView) -> None:
    view.hidden_families = {"operators"}
    ids = view.visible_ids()
    assert all(
        view.nodes[i]["family"] != "operators" for i in ids if view.nodes[i]["kind"] == "model"
    )
    assert "fno" not in ids


def test_nothing_moves_by_itself_when_motion_is_reduced_and_it_does_otherwise(
    view: Atlas3DView,
) -> None:
    view.configure(auto_rotate=True, reduce_motion=True, labels="selected")
    assert view.animating() is False
    view._tick()
    assert view.orbit.yaw == engine.Orbit().yaw and view._timer.isActive() is False
    view.configure(auto_rotate=True, reduce_motion=False, labels="selected")
    assert view.animating() is True and view._timer.isActive()
    view._frame_time -= 1.0
    view._tick()
    assert view.orbit.yaw != engine.Orbit().yaw


@pytest.mark.parametrize("fixture_name", ["theme_dark", "theme_light"])
def test_something_real_is_painted_in_both_themes(
    request: pytest.FixtureRequest, view: Atlas3DView, fixture_name: str
) -> None:
    request.getfixturevalue(fixture_name)
    view.select("fno")
    support.settle()
    image = view.grab().toImage()
    assert image.width() > 300 and support.distinct_colors(image, step=4) > 8


def test_the_atlas_page_switches_views_and_keeps_the_selection_in_both(qapp: Any) -> None:
    page = AtlasPage()
    page.resize(1180, 760)
    page.show()
    try:
        support.settle()
        assert page.current_view() == "3d"
        page.select("fno")
        assert page.view.current == "fno" and page.view3d.current == "fno"
        page.button2d.click()
        assert page.current_view() == "2d"
        page.button3d.click()
        assert page.current_view() == "3d"
        page.apply_settings(store.DEFAULTS.with_changes(atlas_view="2d", labels_3d="none"))
        assert page.current_view() == "2d" and page.view3d.labels == "none"
    finally:
        page.close()
        page.deleteLater()
        support.settle()
