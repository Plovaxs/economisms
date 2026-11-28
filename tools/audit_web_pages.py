"""Audit the web app's pages, in every theme, with a real (headless) Firefox.

Like `capture_web_screenshots.py` this only *drives* two things you start yourself: a built copy of
the web app being served (the demo edition, through
`python -m prometheus.webgateway serve --dist DIR --port 18080`, so that the real
Content-Security-Policy is in force) and a WebDriver server (`geckodriver --port 4444`).

For each page in each theme it runs `audit_web_pages.js` in the page. That computes text contrast
from the browser's own composited colours and checks accessible names, duplicate ids, heading
levels, the single `<h1>` and the landmark regions. It prints one line per page and theme, with the
details of anything that failed, and exits 1 if anything did.

    python tools/audit_web_pages.py                       # every theme, the main pages
    python tools/audit_web_pages.py --themes aurora,paper --pages /,/settings

What it cannot see is listed at the top of `audit_web_pages.js` (text on gradients, hover and focus
states, closed dialogs...): a clean run is evidence about the pages as rendered, not a claim of
conformance. Standard library only.
"""

from __future__ import annotations

import argparse
import re
import sys
import time
from pathlib import Path
from typing import Any

from capture_web_screenshots import PRESS_RUN, STORAGE_KEY, Driver

ROOT = Path(__file__).resolve().parent.parent
THEMES_SOURCE = ROOT / "frontend" / "src" / "settings" / "themes.ts"
AUDIT_SCRIPT = Path(__file__).with_name("audit_web_pages.js")

DEFAULT_PAGES = (
    "/",
    "/economy",
    "/balance-sheets",
    "/market-paths",
    "/pricing",
    "/hedge-actions",
    "/portfolio-risk",
    "/experiments",
    "/audit-trail",
    "/validation-issues",
    "/model-usage",
    "/lab/qmacro",
    "/lab/inflationcast",
    "/atlas",
    "/settings",
)
WIDTH, HEIGHT = 1280, 900


def theme_ids() -> list[str]:
    """The ids of every theme, read from the one file that defines them."""
    ids = re.findall(r'^    id: "([a-z0-9-]+)",$', THEMES_SOURCE.read_text(), flags=re.MULTILINE)
    if not ids:
        raise SystemExit(f"no themes found in {THEMES_SOURCE}")
    return ids


def failures(result: dict[str, Any]) -> list[str]:
    """What is wrong on a page, one short line each."""
    found = [
        f"contrast {row['ratio']}:1 (needs {row['need']}) '{row['text']}' <{row['tag']}>"
        for row in result["contrast"]
    ]
    found += [f"no accessible name: {html}" for html in result["names"]]
    found += [f"duplicate id: {name}" for name in result["ids"]]
    found += [f"heading level skipped: {heading}" for heading in result["headings"]]
    if result["h1"] != 1:
        found.append(f"{result['h1']} <h1> elements (expected exactly 1)")
    for role, count in result["landmarks"].items():
        if count < 1:
            found.append(f"no {role} landmark")
    return found


def audit(driver: Driver, base: str, themes: list[str], pages: list[str]) -> int:
    script = AUDIT_SCRIPT.read_text()
    driver.resize(HEIGHT, WIDTH)
    problems = checked = skipped = 0
    for theme in themes:
        driver.open(base, "/", wait=0.6)
        driver.script(
            f"localStorage.setItem('{STORAGE_KEY}', JSON.stringify({{theme: '{theme}'}}))"
        )
        for page in pages:
            driver.open(base, page, wait=1.6)
            if page.startswith("/lab/"):
                driver.script(PRESS_RUN)  # in the demo edition this shows the recorded real result
                time.sleep(2.5)
            result = driver.script(script)
            bad = failures(result)
            problems += len(bad)
            checked += result["checked"]
            skipped += result["skipped"]
            print(f"{theme:18s}{page:22s}{'ok' if not bad else f'{len(bad)} problem(s)'}")
            for line in bad:
                print("    ", line)
    driver.script(f"localStorage.removeItem('{STORAGE_KEY}')")
    print(
        f"\n{len(themes)} themes x {len(pages)} pages: {checked} text elements measured, "
        f"{skipped} skipped (gradient or clipped text), {problems} problem(s)"
    )
    return 1 if problems else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0] if __doc__ else None)
    parser.add_argument("--base-url", default="http://127.0.0.1:18080")
    parser.add_argument("--driver-url", default="http://127.0.0.1:4444")
    parser.add_argument("--themes", default="", help="comma-separated theme ids (default: all)")
    parser.add_argument(
        "--pages", default="", help="comma-separated routes (default: the main pages)"
    )
    args = parser.parse_args()
    themes = [t for t in args.themes.split(",") if t] or theme_ids()
    pages = [p for p in args.pages.split(",") if p] or list(DEFAULT_PAGES)
    driver = Driver(args.driver_url)
    driver.start()
    try:
        return audit(driver, args.base_url, themes, pages)
    finally:
        driver.stop()


if __name__ == "__main__":
    sys.exit(main())
