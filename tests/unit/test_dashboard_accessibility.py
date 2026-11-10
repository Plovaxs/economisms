from __future__ import annotations

from prometheus.dashboard.accessibility import check_accessibility
from prometheus.dashboard.html import page

_GOOD = page("Title", "Heading", '<img src="x.png" alt="a chart"><p>body</p>')


def test_a_well_formed_page_passes_every_check() -> None:
    report = check_accessibility(_GOOD)
    assert report.passes()
    assert report.has_lang_attribute
    assert report.has_exactly_one_h1
    assert report.has_main_landmark
    assert report.every_image_has_alt
    assert report.has_focus_visible_rule


def test_missing_lang_attribute_fails_only_that_check() -> None:
    broken = _GOOD.replace('lang="en"', "")
    report = check_accessibility(broken)
    assert report.has_lang_attribute is False
    assert report.passes() is False


def test_two_h1_elements_fails_the_single_h1_check() -> None:
    broken = _GOOD.replace("</h1>", "</h1><h1>Second heading</h1>")
    report = check_accessibility(broken)
    assert report.has_exactly_one_h1 is False


def test_missing_main_landmark_fails_that_check() -> None:
    broken = _GOOD.replace("<main>", "<div>").replace("</main>", "</div>")
    report = check_accessibility(broken)
    assert report.has_main_landmark is False


def test_an_image_missing_alt_text_fails_that_check() -> None:
    broken = _GOOD.replace('alt="a chart"', "")
    report = check_accessibility(broken)
    assert report.every_image_has_alt is False


def test_missing_focus_visible_rule_fails_that_check() -> None:
    broken = _GOOD.replace(":focus-visible", "")
    report = check_accessibility(broken)
    assert report.has_focus_visible_rule is False
