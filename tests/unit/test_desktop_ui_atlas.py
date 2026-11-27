# ruff: noqa: E402
"""The Atlas page: the model web, its selection and its cards. What it says comes from the registry,
so these tests check that it says it, that the pointer and the keyboard move through it, and that
something real is painted in both themes."""

from __future__ import annotations

from typing import Any

import pytest

from tests.unit import desktop_ui_support as support

support.require_qt()

from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QImage
from PySide6.QtTest import QTest

from prometheus.desktop.ui.pages.atlas import AtlasPage, AtlasView
from prometheus.modelzoo import graph as zoo_graph


@pytest.fixture()
def page(qapp: Any) -> Any:
    widget = AtlasPage()
    widget.resize(1180, 760)
    widget.show()
    support.settle()
    yield widget
    widget.close()
    widget.deleteLater()
    support.settle()


def test_the_web_draws_built_models_baselines_and_pipelines_but_not_the_models_not_built(
    page: AtlasPage,
) -> None:
    kinds = {n["kind"] for n in page.view.nodes}
    assert kinds == {"model", "baseline", "pipeline"}
    assert all(n["status"] != "not_built" for n in page.view.nodes)
    assert "fno" in page.view.by_id and "ferminet" not in page.view.by_id
    for edge in page.view.edges:
        assert edge["source"] in page.view.by_id and edge["target"] in page.view.by_id


def test_every_node_gets_a_distinct_position_inside_the_view(page: AtlasPage) -> None:
    positions = page.view.positions()
    assert set(positions) == set(page.view.by_id)
    seen = {(round(p.x()), round(p.y())) for p in positions.values()}
    assert len(seen) == len(positions)
    for p in positions.values():
        assert 0 <= p.x() <= page.view.width() and 0 <= p.y() <= page.view.height()


def test_selecting_a_model_shows_what_it_was_judged_against_and_what_was_found(
    page: AtlasPage,
) -> None:
    page.select("fno")
    text = page.card.toPlainText()
    assert "Fourier Neural Operator" in text
    assert "Dense MLP on the payoff vector" in text  # a baseline it was judged against
    assert "Z-O3 (supported)" in text and "Z-O4 (contradicted)" in text
    assert "Finding 30" in text
    assert page.view.current == "fno"


def test_a_model_that_was_not_built_says_why_and_a_pipeline_names_its_steps(
    page: AtlasPage,
) -> None:
    page.select("alphaproof")
    assert "Not built" in page.card.toPlainText() and "Lean" in page.card.toPlainText()
    assert page.view.current is None  # not in the drawing
    page.select("pipeline:surrogate_hedge")
    text = page.card.toPlainText()
    assert "Fourier Neural Operator" in text and "Historical VaR and Expected Shortfall" in text
    assert "Z-I2 (supported)" in text


def test_clicking_a_node_selects_it_and_the_list_follows(page: AtlasPage) -> None:
    position = page.view.positions()["deeponet"]
    QTest.mouseClick(
        page.view, Qt.MouseButton.LeftButton, pos=QPoint(round(position.x()), round(position.y()))
    )
    assert page.view.current == "deeponet"
    assert "DeepONet" in page.card.toPlainText()
    current = page.list.currentItem()
    assert current is not None and current.data(Qt.ItemDataRole.UserRole) == "deeponet"
    # an empty spot clears the selection
    QTest.mouseClick(page.view, Qt.MouseButton.LeftButton, pos=QPoint(3, 3))
    assert page.view.current is None


def test_the_arrow_keys_walk_the_whole_web_and_wrap(page: AtlasPage) -> None:
    view: AtlasView = page.view
    support.focus(view)
    seen = []
    for _ in range(len(view.order)):
        QTest.keyClick(view, Qt.Key.Key_Right)
        seen.append(view.current)
    assert seen == view.order  # every node, in order, starting from the first
    QTest.keyClick(view, Qt.Key.Key_Right)
    assert view.current == view.order[0]  # and it wraps
    QTest.keyClick(view, Qt.Key.Key_Left)
    assert view.current == view.order[-1]
    assert "Selected" in view.accessibleDescription()


def test_search_and_the_status_filter_narrow_the_list(page: AtlasPage) -> None:
    total = page.list.count()
    assert total == zoo_graph.coverage()["requested"]
    page.search.setText("quantum")
    assert 0 < page.list.count() < total
    page.search.setText("")
    page.status.setCurrentIndex(page.status.findData("not_built"))
    assert page.list.count() == zoo_graph.coverage()["by_status"]["not_built"]
    assert "models shown" in page.count.text()
    page.status.setCurrentIndex(page.status.findData("existing"))
    assert page.list.count() == zoo_graph.coverage()["by_status"]["existing"]


def test_the_summary_states_the_real_counts(page: AtlasPage) -> None:
    c = zoo_graph.coverage()
    text = page.summary_text()
    assert (
        str(c["requested"]) in text
        and f"{c['by_status']['not_built']} are deliberately not built" in text
    )
    assert "contradicted" in text


def test_the_text_of_a_card_is_text_not_markup(page: AtlasPage) -> None:
    html = page.card.toHtml()
    page.card.setMarkdown("<img src='x'> <script>boom</script>")
    assert "<script" not in page.card.toHtml().lower().split("</head>")[-1].replace("&lt;", "")
    del html


@pytest.mark.parametrize("fixture_name", ["theme_dark", "theme_light"])
def test_something_real_is_painted_in_both_themes(
    request: pytest.FixtureRequest, page: AtlasPage, fixture_name: str
) -> None:
    request.getfixturevalue(fixture_name)
    page.select("fno")
    support.settle()
    image = page.view.grab().toImage()
    assert isinstance(image, QImage) and image.width() > 300
    assert support.distinct_colors(image, step=4) > 8
