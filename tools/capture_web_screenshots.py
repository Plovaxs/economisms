"""Capture the web app's pages as PNG files with a real (headless) Firefox.

This only *drives* two things that you start yourself, so that it never owns a process:

1. a built copy of the web app being served, for example the demo edition
   (`cd frontend && npx vite build --mode demo --outDir /tmp/demo`, then
   `python -m prometheus.webgateway serve --dist /tmp/demo --port 18080`; serving it through the
   gateway means the real Content-Security-Policy is in force while the pictures are taken); and
2. a WebDriver server for Firefox (`geckodriver --port 4444`).

Then: `python tools/capture_web_screenshots.py --out docs/images/web`.

Standard library only. The lab pages are captured after pressing their Run button; in the demo
edition that returns the recorded real result, so what is photographed is real output. `--extras`
also takes the interactive states (command palette, shortcuts, the 3D web turned by a drag, a few
themes, large text with high contrast); `--only a,b` takes just those names.
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
    ("atlas", "/atlas?model=fno", False),
    ("settings", "/settings", False),
)

THEME_SHOTS = ("tokyo-night", "catppuccin-latte", "gruvbox", "high-contrast")
STORAGE_KEY = "econosim.settings.v1"
WIDTH = 1280
MIN_HEIGHT = 900
MAX_HEIGHT = 2600
CONTROL = ""
ESCAPE = ""

# how much taller the window must be for the main panel (which scrolls inside the window) to need
# no scrollbar
OVERFLOW = (
    "const m=document.querySelector('main');"
    "return m ? Math.max(0, m.scrollHeight - m.clientHeight) : 0;"
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

    def resize(self, height: int, width: int = WIDTH) -> None:
        self.call("POST", self.at("/window/rect"), {"width": width, "height": height})

    def open(self, base: str, route: str, wait: float = 2.2) -> None:
        self.call("POST", self.at("/url"), {"url": base.rstrip("/") + route})
        time.sleep(wait)

    def png(self, element: str | None = None) -> bytes:
        path = "/screenshot" if element is None else f"/element/{element}/screenshot"
        return base64.b64decode(self.call("GET", self.at(path)))

    def keys(self, text: str = "", *, control: str = "", special: tuple[str, ...] = ()) -> None:
        """Type `text`, then press each of `special`; `control` is a key pressed with Ctrl held."""
        actions: list[dict[str, str]] = []
        if control:
            actions += [{"type": "keyDown", "value": CONTROL}]
            actions += [{"type": "keyDown", "value": control}, {"type": "keyUp", "value": control}]
            actions += [{"type": "keyUp", "value": CONTROL}]
        for ch in text:
            actions += [{"type": "keyDown", "value": ch}, {"type": "keyUp", "value": ch}]
        for key in special:
            actions += [{"type": "keyDown", "value": key}, {"type": "keyUp", "value": key}]
        body = {"actions": [{"type": "key", "id": "kb", "actions": actions}]}
        self.call("POST", self.at("/actions"), body)
        self.call("DELETE", self.at("/actions"))
        time.sleep(0.5)

    def drag(self, x0: int, y0: int, x1: int, y1: int) -> None:
        pointer = {
            "type": "pointer",
            "id": "mouse",
            "parameters": {"pointerType": "mouse"},
            "actions": [
                {"type": "pointerMove", "x": x0, "y": y0},
                {"type": "pointerDown", "button": 0},
                {"type": "pointerMove", "x": x1, "y": y1, "duration": 350},
                {"type": "pointerUp", "button": 0},
            ],
        }
        self.call("POST", self.at("/actions"), {"actions": [pointer]})
        self.call("DELETE", self.at("/actions"))
        time.sleep(0.6)

    def set_settings(self, base: str, settings: dict[str, Any] | None) -> None:
        """Store (or clear) the person's settings in this origin, to be read on the next load."""
        self.open(base, "/", wait=0.5)
        if settings is None:
            self.script(f"localStorage.removeItem('{STORAGE_KEY}')")
        else:
            payload = json.dumps(settings)
            self.script(f"localStorage.setItem('{STORAGE_KEY}', JSON.stringify({payload}))")


def fit(driver: Driver, base_height: int = MIN_HEIGHT, width: int = WIDTH) -> None:
    """Grow the window until the page needs no inner scrollbar (the shell scrolls inside itself)."""
    height = base_height
    for _ in range(3):
        driver.resize(height, width)
        time.sleep(0.4)
        extra = int(driver.script(OVERFLOW))
        if extra <= 0:
            break
        height = min(height + extra + 8, MAX_HEIGHT)


def save(driver: Driver, out: Path, name: str, saved: list[Path]) -> None:
    target = out / f"{name}.png"
    target.write_bytes(driver.png())
    saved.append(target)


def capture_pages(driver: Driver, base: str, out: Path, only: set[str] | None) -> list[Path]:
    saved: list[Path] = []
    driver.set_settings(base, None)
    for name, route, press_run in PAGES:
        if only and name not in only:
            continue
        driver.resize(MIN_HEIGHT)
        driver.open(base, route)
        if press_run:
            driver.script(PRESS_RUN)
            time.sleep(4)
        fit(driver)
        save(driver, out, name, saved)
        if name == "overview":
            element = driver.script("return document.querySelector('aside')")
            target = out / "sidebar.png"
            target.write_bytes(driver.png(next(iter(element.values()))))
            saved.append(target)
    return saved


def capture_extras(driver: Driver, base: str, out: Path, only: set[str] | None) -> list[Path]:
    saved: list[Path] = []

    def wanted(name: str) -> bool:
        return not only or name in only

    if wanted("palette"):
        driver.set_settings(base, {"theme": "tokyo-night"})
        driver.resize(MIN_HEIGHT)
        driver.open(base, "/")
        driver.keys(control="k")
        driver.keys("theme")
        save(driver, out, "palette", saved)
        driver.keys(special=(ESCAPE,))
    if wanted("shortcuts"):
        driver.open(base, "/")
        driver.keys("?")
        save(driver, out, "shortcuts", saved)
        driver.keys(special=(ESCAPE,))
    if wanted("atlas-3d"):
        still = {"theme": "tokyo-night", "autoRotate": False, "labels3d": "selected"}
        driver.set_settings(base, still)
        driver.resize(MIN_HEIGHT)
        driver.open(base, "/atlas?model=qae", wait=2.5)
        fit(driver)
        driver.drag(520, 600, 640, 560)
        save(driver, out, "atlas-3d", saved)
    for theme_id in THEME_SHOTS:
        name = f"theme-{theme_id}"
        if not wanted(name):
            continue
        driver.set_settings(base, {"theme": theme_id})
        driver.resize(720, 1100)
        driver.open(base, "/pricing")
        save(driver, out, name, saved)
    if wanted("access-large-text"):
        driver.set_settings(
            base,
            {
                "theme": "catppuccin-latte",
                "fontScale": 1.3,
                "contrast": "high",
                "targetSize": "large",
                "focusRing": "strong",
            },
        )
        driver.resize(MIN_HEIGHT)
        driver.open(base, "/pricing")
        fit(driver)
        save(driver, out, "access-large-text", saved)
    driver.set_settings(base, None)
    return saved


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0] if __doc__ else None)
    parser.add_argument("--base-url", default="http://127.0.0.1:18080")
    parser.add_argument("--driver-url", default="http://127.0.0.1:4444")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument(
        "--extras", action="store_true", help="also the interactive states and themes"
    )
    parser.add_argument("--extras-only", action="store_true", help="only the interactive states")
    parser.add_argument("--only", default="", help="comma-separated names to capture")
    args = parser.parse_args()
    only = {n for n in args.only.split(",") if n} or None
    args.out.mkdir(parents=True, exist_ok=True)
    driver = Driver(args.driver_url)
    driver.start()
    try:
        saved: list[Path] = []
        if not args.extras_only:
            saved += capture_pages(driver, args.base_url, args.out, only)
        if args.extras or args.extras_only:
            saved += capture_extras(driver, args.base_url, args.out, only)
        for path in saved:
            print("saved", path)
    finally:
        driver.stop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
