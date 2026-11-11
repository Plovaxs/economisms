"""Shared, dependency-free HTML templating for every dashboard view.

No frontend framework or template engine was added -- this repository
has zero JS/HTML build tooling today, and one view-rendering module
does not justify acquiring any (the same "don't add a dependency for
one item" discipline `release_provenance.py` applied to PDF export).
`escape` is the single place every piece of untrusted/dynamic text
passes through before reaching an HTML string, so a value containing
`<`/`&`/`"` cannot break page structure or inject markup.

`page()` is the one page skeleton every view uses (UIX-11's
accessibility baseline, checked by `dashboard.accessibility`): a
`lang` attribute, a `<main>` landmark, exactly one `<h1>`, and a
`:focus-visible` outline rule so keyboard-focused interactive elements
are not invisible (the one part of "keyboard navigation... passes"
this environment CAN check from source -- a real browser/screen-reader
walkthrough is still required, see the test plan doc).
"""

from __future__ import annotations

from html import escape as _escape

escape = _escape

_BASE_STYLE = (
    "body{font-family:system-ui,sans-serif;margin:0;padding:24px;"
    "background:#101216;color:#e8e6e0;}"
    "main{max-width:960px;margin:0 auto;}"
    "table{border-collapse:collapse;width:100%;margin:12px 0;}"
    "th,td{text-align:left;padding:6px 10px;border-bottom:1px solid #333;}"
    "a:focus-visible,button:focus-visible{outline:3px solid #8ea0ff;outline-offset:2px;}"
    ".provenance{font-size:0.85em;padding:4px 8px;border-radius:4px;display:inline-block;}"
    ".provenance.synthetic{background:#4a3410;color:#e0ab4a;}"
    ".provenance.real{background:#143a24;color:#4fbf84;}"
    ".chart{display:block;margin:8px 0 16px;max-width:100%;}"
    ".chart-bar-fill{transform-box:fill-box;transform-origin:left center;"
    "animation:chart-grow-x 0.6s ease-out forwards;}"
    "@keyframes chart-grow-x{from{transform:scaleX(0);}to{transform:scaleX(1);}}"
    ".chart-line-draw{animation:chart-draw-line 1.1s ease-out forwards;}"
    "@keyframes chart-draw-line{to{stroke-dashoffset:0;}}"
    ".chart-legend{display:flex;gap:16px;flex-wrap:wrap;margin-bottom:4px;font-size:0.85em;}"
    ".chart-legend-item{display:inline-flex;align-items:center;gap:4px;}"
    ".indicator-row{display:flex;align-items:center;gap:8px;}"
    ".indicator-dot{width:12px;height:12px;border-radius:50%;display:inline-block;"
    "animation:indicator-pulse 1.6s ease-in-out infinite;}"
    ".indicator-dot.indicator-pass{background:#4fbf84;}"
    ".indicator-dot.indicator-fail{background:#e0617a;}"
    "@keyframes indicator-pulse{0%,100%{opacity:1;}50%{opacity:0.35;}}"
    "@media (prefers-reduced-motion: reduce){"
    ".chart-bar-fill,.chart-line-draw,.indicator-dot{animation:none;}"
    ".chart-line-draw{stroke-dashoffset:0;}}"
)


def page(title: str, heading: str, body_html: str) -> str:
    return (
        "<!doctype html>"
        f'<html lang="en"><head><meta charset="utf-8">'
        f"<title>{escape(title)}</title><style>{_BASE_STYLE}</style></head>"
        f"<body><main>"
        f"<h1>{escape(heading)}</h1>"
        f"{body_html}"
        f"</main></body></html>"
    )


def table(headers: list[str], rows: list[list[str]]) -> str:
    head = "".join(f"<th>{escape(h)}</th>" for h in headers)
    body = "".join(
        "<tr>" + "".join(f"<td>{escape(str(cell))}</td>" for cell in row) + "</tr>" for row in rows
    )
    return f"<table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>"
