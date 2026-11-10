"""UIX-11: "Create accessibility and responsive-layout test plan --
Keyboard navigation and contrast review passes."

This sandboxed environment has no real browser, no screen reader, and
no visual rendering tool -- a genuine keyboard-only navigation pass or
a screen-reader pass CANNOT be run here, and `check_accessibility`
below does NOT claim to run one. What it DOES check, from the rendered
HTML source alone, is real and automatable: a `lang` attribute (screen
readers mispronounce content without one), exactly one `<h1>` (a
correct heading hierarchy's root), a `<main>` landmark (so assistive
tech can skip to content), that every `<img>` carries `alt` text, and
that the page's own stylesheet defines a `:focus-visible` rule (so a
keyboard-focused control is not invisible -- the one piece of "keyboard
navigation" truly checkable from source, since actually tabbing through
the page needs a real browser). See
`docs/UIX_ACCESSIBILITY_TEST_PLAN.md` for exactly what a human must
still verify in a real browser -- named explicitly as NOT COVERED here,
not silently implied to be covered.
"""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class AccessibilityReport:
    has_lang_attribute: bool
    has_exactly_one_h1: bool
    has_main_landmark: bool
    every_image_has_alt: bool
    has_focus_visible_rule: bool

    def passes(self) -> bool:
        return all(
            (
                self.has_lang_attribute,
                self.has_exactly_one_h1,
                self.has_main_landmark,
                self.every_image_has_alt,
                self.has_focus_visible_rule,
            )
        )


def check_accessibility(html: str) -> AccessibilityReport:
    images = re.findall(r"<img\b[^>]*>", html, flags=re.IGNORECASE)
    every_image_has_alt = all(
        re.search(r"""\balt\s*=\s*(?:"[^"]*"|'[^']*')""", tag) for tag in images
    )
    return AccessibilityReport(
        has_lang_attribute=bool(
            re.search(r"""<html[^>]*\blang\s*=\s*(?:"[a-zA-Z-]+"|'[a-zA-Z-]+')""", html)
        ),
        has_exactly_one_h1=len(re.findall(r"<h1\b", html, flags=re.IGNORECASE)) == 1,
        has_main_landmark=bool(re.search(r"<main\b", html, flags=re.IGNORECASE)),
        every_image_has_alt=every_image_has_alt,
        has_focus_visible_rule=":focus-visible" in html,
    )
