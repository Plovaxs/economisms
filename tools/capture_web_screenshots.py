"""Capture the web app's pages as PNG files with a real (headless) Firefox.

This only *drives* two things that you start yourself, so that it never owns a process:

1. a built copy of the web app being served, for example the demo edition
   (`cd frontend && npx vite build --mode demo --outDir /tmp/demo`, then
   `python -m prometheus.webgateway serve --dist /tmp/demo --port 18080`); and
2. a WebDriver server for Firefox (`geckodriver --port 4444`).

Then: `python tools/capture_web_screenshots.py --out docs/images/web`.

Standard library only. The lab pages are captured after pressing their Run button; in the demo
edition that returns the recorded real result, so what is photographed is real output.
"""

from __future__ import annotations

import argparse
import base64
import json
import time
import urllib.request
from pathlib import Path
from typing import Any

# (file name, route, press the Run button first)
PAGES: tuple[tuple[str, str, bool], ...] = (
    ("overview", "/", False),
    ("economy", "/economy", False),
    ("balance-sheets", "/balance-sheets", False),
    ("market-paths", "/market-paths", False),
    ("pricing", "/pricing", False),
    ("hedge-actions", "/hedge-actions", False),
    ("portfolio-risk", "/portfolio-risk", False),
    ("experiments", "/experiments", False),
    ("audit-trail", "/audit-trail", False),
    ("validation-issues", "/validation-issues", False),
    ("model-usage", "/model-usage", False),
    ("lab-qmacro", "/lab/qmacro", True),
    ("lab-recessionnet", "/lab/recessionnet", True),
    ("lab-inflationcast", "/lab/inflationcast", True),
    ("lab-neural-sde", "/lab/neural-sde", True),
    ("lab-pde-solver", "/lab/pde-solver", True),
    ("lab-marl", "/lab/marl", True),
    ("lab-rl-hedge", "/lab/rl-hedge", True),
)

WIDTH = 1440
MIN_HEIGHT = 900
# the lowest element of the page's main column, so a short page is not photographed with a void
CONTENT_BOTTOM = (
    "const m=document.querySelector('main')||document.body; let b=0;"
    "m.querySelectorAll('*').forEach(e=>{b=Math.max(b,e.getBoundingClientRect().bottom+window.scrollY)});"
    "return b;"
)
PRESS_RUN = (
    "const b=[...document.querySelectorAll('button')].find(x=>/^Run/.test(x.textContent.trim()));"
    "if(b) b.click();"
)


class Driver:
    """The few W3C WebDriver calls this needs, over plain HTTP."""

    def __init__(self, url: str) -> None:
        if not url.startswith(("http://", "https://")):
            raise ValueError("the driver URL must be http or https")
        self.url = url.rstrip("/")
        self.session = ""

    def call(self, method: str, path: str, body: dict[str, Any] | None = None) -> Any:
        data = None if body is None else json.dumps(body).encode()
        request = urllib.request.Request(  # noqa: S310 - scheme checked in __init__
            self.url + path, method=method, data=data, headers={"Content-Type": "application/json"}
        )
        with urllib.request.urlopen(request, timeout=120) as response:  # noqa: S310 - local driver
            return json.loads(response.read())["value"]

    def start(self) -> None:
        caps = {"alwaysMatch": {"moz:firefoxOptions": {"args": ["-headless"]}}}
        self.session = self.call("POST", "/session", {"capabilities": caps})["sessionId"]

    def stop(self) -> None:
        if self.session:
            self.call("DELETE", f"/session/{self.session}")

    def at(self, path: str) -> str:
        return f"/session/{self.session}{path}"

    def script(self, code: str) -> Any:
        return self.call("POST", self.at("/execute/sync"), {"script": code, "args": []})

    def resize(self, height: int) -> None:
        self.call("POST", self.at("/window/rect"), {"width": WIDTH, "height": height})

    def png(self, element: str | None = None) -> bytes:
        path = "/screenshot" if element is None else f"/element/{element}/screenshot"
        return base64.b64decode(self.call("GET", self.at(path)))


def capture(driver: Driver, base_url: str, out: Path) -> list[Path]:
    saved: list[Path] = []
    driver.resize(MIN_HEIGHT)
    for name, route, press_run in PAGES:
        driver.call("POST", driver.at("/url"), {"url": base_url.rstrip("/") + route})
        time.sleep(2.5)
        if press_run:
            driver.script(PRESS_RUN)
            time.sleep(4)
        height = max(int(driver.script(CONTENT_BOTTOM)) + 56, MIN_HEIGHT)
        driver.resize(min(height + 90, 1800))
        time.sleep(0.6)
        target = out / f"{name}.png"
        target.write_bytes(driver.png())
        saved.append(target)
        if name == "overview":
            element = driver.script("return document.querySelector('aside')")
            (out / "sidebar.png").write_bytes(driver.png(next(iter(element.values()))))
            saved.append(out / "sidebar.png")
        driver.resize(MIN_HEIGHT)
    return saved


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0] if __doc__ else None)
    parser.add_argument("--base-url", default="http://127.0.0.1:18080")
    parser.add_argument("--driver-url", default="http://127.0.0.1:4444")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    driver = Driver(args.driver_url)
    driver.start()
    try:
        for path in capture(driver, args.base_url, args.out):
            print("saved", path)
    finally:
        driver.stop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
