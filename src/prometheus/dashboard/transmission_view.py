"""The shock transmission map: pick a shock, see where it starts and which links carry it.

Everything is computed on request from `prometheus.worldsim.transmission` (nothing is canned):
the same seeds are simulated with and without the shock, and again with each feedback loop
switched off in turn. The page is a SIMULATION with chosen (or calibrated) parameters and carries
the repository's synthetic badge: it shows how the simulator is wired, not how the real economy
transmits shocks.

The picture is a server-drawn SVG (no script): sectors on a ring, one arrow per switchable loop
whose width is the size of what the loop carries for the chosen outcome, drawn dashed and grey
when the 95% interval over seeds includes zero, and thin grey lines for the structural links that
cannot be switched off one at a time. A table below repeats every number in the picture.
"""

from __future__ import annotations

import math
from functools import lru_cache
from typing import Any

from prometheus.dashboard.charts import line_chart
from prometheus.dashboard.html import escape, page, table
from prometheus.dashboard.provenance import synthetic_badge
from prometheus.worldsim.calibrated import CALIBRATED_SCENARIOS, calibrated_scenario
from prometheus.worldsim.config import (
    CONNECTED_SCENARIOS,
    EXTENDED_SCENARIOS,
    SCENARIOS,
    WorldConfig,
    connected_scenario,
    full_scenario,
    scenario,
)
from prometheus.worldsim.impulse import OUTCOMES, SHOCK_SIZES
from prometheus.worldsim.transmission import (
    MAX_SEEDS,
    MIN_SEEDS,
    SECTOR_LABEL,
    SECTORS,
    SHOCK_LABEL,
    STRUCTURAL_EDGES,
    transmission_map,
)

DEFAULT_SEEDS = 6
ALL_SCENARIOS = SCENARIOS + EXTENDED_SCENARIOS + CONNECTED_SCENARIOS + CALIBRATED_SCENARIOS
OUTCOME_LABEL = {
    "output_gap": "Output gap (mean over 24 months, points)",
    "inflation": "Inflation (mean, % a year)",
    "unemployment": "Unemployment (mean, points)",
    "policy_rate": "Policy rate (mean, points)",
    "equity_return": "Equity return (24-month sum)",
    "failed_banks": "Banks failed (count)",
    "public_debt": "Public debt (change, share of GDP)",
    "exchange_rate": "Exchange rate (log change)",
    "consumption": "Household consumption (log change)",
    "gini": "Wealth Gini (change)",
    "top10_share": "Top-10% wealth share (change)",
}
_WIDTH, _HEIGHT, _RADIUS = 640, 480, 40
_CENTRE = (_WIDTH / 2, _HEIGHT / 2)
_RING = (245.0, 175.0)
_AMBER, _GREY, _RED, _BLUE = "#e0ab4a", "#6b6a64", "#e0617a", "#8ea0ff"


def _config(name: str, mode: str) -> WorldConfig:
    if name in CALIBRATED_SCENARIOS:
        return calibrated_scenario(name, mode=mode)  # type: ignore[arg-type]
    if name in CONNECTED_SCENARIOS:
        return connected_scenario(name, mode=mode)  # type: ignore[arg-type]
    if name in EXTENDED_SCENARIOS:
        return full_scenario(name, mode=mode)  # type: ignore[arg-type]
    if name in SCENARIOS:
        return scenario(name)
    raise ValueError(f"scenario must be one of {ALL_SCENARIOS}")


@lru_cache(maxsize=24)
def _compute(name: str, mode: str, kind: str, size: float, seeds: int) -> dict[str, Any]:
    config = _config(name, mode)
    return transmission_map(config, kind, size, list(range(seeds)))


def transmission_as_json(
    *,
    name: str = "stressed_connected",
    shock: str = "equity_crash",
    size: float | None = None,
    seeds: int = DEFAULT_SEEDS,
    mode: str = "none",
) -> dict[str, Any]:
    if shock not in SHOCK_SIZES:
        raise ValueError(f"shock must be one of {tuple(SHOCK_SIZES)}")
    if not MIN_SEEDS <= seeds <= MAX_SEEDS:
        raise ValueError(f"seeds must be between {MIN_SEEDS} and {MAX_SEEDS}")
    result = dict(_compute(name, mode, shock, SHOCK_SIZES[shock] if size is None else size, seeds))
    result["synthetic"] = True
    return result


def _node_positions() -> dict[str, tuple[float, float]]:
    """The economy (output and jobs) in the centre, every other sector on a ring around it."""
    positions: dict[str, tuple[float, float]] = {"economy": _CENTRE}
    ring = [key for key, _label in SECTORS if key != "economy"]
    for index, key in enumerate(ring):
        angle = -math.pi / 2 + 2.0 * math.pi * index / len(ring)
        positions[key] = (
            _CENTRE[0] + _RING[0] * math.cos(angle),
            _CENTRE[1] + _RING[1] * math.sin(angle),
        )
    return positions


def _arrow(
    a: tuple[float, float], b: tuple[float, float], offset: float
) -> tuple[float, float, float, float]:
    """Endpoints of an arrow from node `a` to node `b`, trimmed to the node circles and shifted
    sideways by `offset` so that two arrows between the same pair do not overlap."""
    dx, dy = b[0] - a[0], b[1] - a[1]
    length = math.hypot(dx, dy) or 1.0
    ux, uy = dx / length, dy / length
    nx, ny = -uy, ux
    start = (a[0] + ux * _RADIUS + nx * offset, a[1] + uy * _RADIUS + ny * offset)
    end = (b[0] - ux * (_RADIUS + 6) + nx * offset, b[1] - uy * (_RADIUS + 6) + ny * offset)
    return start[0], start[1], end[0], end[1]


def _significant_sectors(result: dict[str, Any]) -> set[str]:
    from prometheus.worldsim.transmission import OUTCOME_SECTOR

    response = result["response"]
    if response is None:
        return set()
    return {
        OUTCOME_SECTOR[name]
        for name, cell in response["outcomes"].items()
        if cell["excludes_zero"] and name != "equity_return"
    } | {result["origin"]}


def render_diagram(result: dict[str, Any], focus: str) -> str:
    positions = _node_positions()
    reached = _significant_sectors(result)
    effects = {key: row["outcomes"][focus]["estimate"] for key, row in result["channels"].items()}
    peak = max([abs(v) for v in effects.values()] + [1e-12])
    parts = [
        f'<svg class="chart" viewBox="0 0 {_WIDTH} {_HEIGHT}" width="{_WIDTH}" height="{_HEIGHT}" '
        'role="img" aria-label="shock transmission map">',
        "<defs>"
        + "".join(
            f'<marker id="head-{name}" viewBox="0 0 10 10" refX="9" refY="5" '
            'markerUnits="userSpaceOnUse" markerWidth="11" markerHeight="11" '
            f'orient="auto"><path d="M0,0 L10,5 L0,10 z" fill="{colour}"/></marker>'
            for name, colour in (("amber", _AMBER), ("grey", _GREY))
        )
        + "</defs>",
    ]
    for source, target, why in STRUCTURAL_EDGES:
        x1, y1, x2, y2 = _arrow(positions[source], positions[target], -5.0)
        parts.append(
            f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" stroke="{_GREY}" '
            f'stroke-width="1" opacity="0.55" marker-end="url(#head-grey)">'
            f"<title>{escape(SECTOR_LABEL[source])} to {escape(SECTOR_LABEL[target])}: "
            f"{escape(why)} (built in, not switchable)</title></line>"
        )
    for key, row in result["channels"].items():
        cell = row["outcomes"][focus]
        x1, y1, x2, y2 = _arrow(positions[row["source"]], positions[row["target"]], 6.0)
        width = 1.5 + (7.0 * abs(cell["estimate"]) / peak if cell["excludes_zero"] else 0.0)
        colour = _AMBER if cell["excludes_zero"] else _GREY
        head = "amber" if cell["excludes_zero"] else "grey"
        dash = "" if cell["excludes_zero"] else ' stroke-dasharray="5 4"'
        parts.append(
            f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" stroke="{colour}" '
            f'stroke-width="{width:.1f}"{dash} marker-end="url(#head-{head})" '
            f'data-channel="{escape(key)}">'
            f"<title>{escape(row['label'])}: {cell['estimate']:+.4f} "
            f"[{cell['low']:+.4f}, {cell['high']:+.4f}]</title></line>"
        )
    for key, label in SECTORS:
        x, y = positions[key]
        is_origin = key == result["origin"]
        stroke = _RED if is_origin else (_BLUE if key in reached else _GREY)
        width = 4 if is_origin else 2
        fill = "#2a1620" if is_origin else ("#161b33" if key in reached else "#181a1f")
        parts.append(
            f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{_RADIUS}" fill="{fill}" stroke="{stroke}" '
            f'stroke-width="{width}"><title>{escape(label)}</title></circle>'
        )
        words = label.split(" ")
        lines = (
            [" ".join(words[: len(words) // 2 or 1]), " ".join(words[len(words) // 2 or 1 :])]
            if len(label) > 9
            else [label]
        )
        for i, line in enumerate(lines):
            if not line:
                continue
            dy = 4 + (i - (len(lines) - 1) / 2) * 13
            parts.append(
                f'<text x="{x:.1f}" y="{y + dy:.1f}" text-anchor="middle" fill="#e8e6e0" '
                f'font-size="11.5">{escape(line)}</text>'
            )
    parts.append("</svg>")
    return "".join(parts)


def _form(name: str, shock: str, size: float, focus: str, seeds: int, mode: str) -> str:
    def options(values: tuple[str, ...], chosen: str, label: dict[str, str] | None = None) -> str:
        return "".join(
            f'<option value="{escape(v)}"{" selected" if v == chosen else ""}>'
            f"{escape(label[v] if label else v)}</option>"
            for v in values
        )

    return (
        '<form method="get" action="/dashboard/transmission">'
        f'<label>Scenario <select name="scenario">{options(ALL_SCENARIOS, name)}</select></label> '
        f'<label>Shock <select name="shock">{options(tuple(SHOCK_SIZES), shock, SHOCK_LABEL)}'
        "</select></label> "
        f'<label>Size <input name="size" value="{size}" size="6"></label> '
        f'<label>Outcome <select name="outcome">{options(OUTCOMES, focus, OUTCOME_LABEL)}'
        "</select></label> "
        f'<label>Seeds <input name="seeds" value="{seeds}" size="3"></label> '
        f'<label>Bank rescue <select name="mode">'
        f"{options(('none', 'liquidity', 'recapitalise'), mode)}</select></label> "
        '<button type="submit">Run</button></form>'
    )


def render_transmission(
    *,
    name: str = "stressed_connected",
    shock: str = "equity_crash",
    size: float | None = None,
    focus: str = "output_gap",
    seeds: int = DEFAULT_SEEDS,
    mode: str = "none",
) -> str:
    if focus not in OUTCOMES:
        raise ValueError(f"outcome must be one of {OUTCOMES}")
    result = transmission_as_json(name=name, shock=shock, size=size, seeds=seeds, mode=mode)
    used_size = float(result["size"])
    size_text = "no size" if shock == "sovereign_default" else f"size {used_size:g}"
    body = (
        synthetic_badge()
        + f"<p>Scenario <code>{escape(name)}</code>, shock <code>{escape(shock)}</code> "
        f"({size_text}) in month 100, {seeds} paired seeds (each simulated with and without "
        "the shock, and again with each link switched off). It takes a few seconds. This shows how "
        "the simulator is wired, not how the real economy transmits shocks.</p>"
        + _form(name, shock, used_size, focus, seeds, mode)
    )
    if result["unavailable"]:
        body += f"<p><strong>Nothing to show:</strong> {escape(result['unavailable'])}.</p>"
        return page("Shock transmission", "Shock transmission map (synthetic)", body)

    response = result["response"]
    months = [str(m) for m in response["months"]]
    paths = response["paths"]
    context = response["context"]
    body += (
        f"<p>At the moment of the shock the average world had "
        f"{context['banks_failed_at_shock']:.1f} of 10 banks already failed and was in the "
        f"crisis regime in {context['crisis_at_shock_share']:.0%} of the seeds; failure is "
        "absorbing, so a bank shock cannot add failures that have already happened.</p>"
        f"<h2>Where it goes: {escape(OUTCOME_LABEL[focus])}</h2>"
        "<p>Red ring: where the shock enters. Blue ring: a sector whose response excludes zero. "
        "Amber arrow: a link that carries a significant part of the response for the chosen "
        "outcome (width is its size); dashed grey: a link switched off in turn whose effect "
        "includes zero; thin grey: structural links that cannot be switched off one at a "
        "time.</p>" + render_diagram(result, focus)
    )
    channel_rows = [
        [
            row["label"],
            f"{SECTOR_LABEL[row['source']]} to {SECTOR_LABEL[row['target']]}",
            f"{row['outcomes'][focus]['estimate']:+.4f}",
            f"[{row['outcomes'][focus]['low']:+.4f}, {row['outcomes'][focus]['high']:+.4f}]",
            "yes" if row["outcomes"][focus]["excludes_zero"] else "no",
        ]
        for row in result["channels"].values()
    ]
    if channel_rows:
        body += "<h2>What each link carries</h2>" + table(
            ["link", "direction", "carried (full minus link off)", "95% interval", "excludes 0"],
            channel_rows,
        )
    else:
        body += (
            "<p>This scenario has no switchable feedback loops except the credit crunch and "
            "fire sales shown above; try a <code>*_connected</code> scenario.</p>"
        )
    body += "<h2>Response over time (months from the shock, mean over seeds)</h2>" + line_chart(
        months,
        {k: paths[k] for k in ("output_gap", "inflation", "unemployment", "policy_rate")},
    )
    body += line_chart(
        months, {k: paths[k] for k in ("equity_return", "exchange_rate", "public_debt")}
    )
    body += line_chart(months, {"banks failed": paths["failed_banks"]})
    outcome_rows = [
        [
            OUTCOME_LABEL[k],
            f"{v['estimate']:+.4f}",
            f"[{v['low']:+.4f}, {v['high']:+.4f}]",
            "yes" if v["excludes_zero"] else "no",
        ]
        for k, v in response["outcomes"].items()
    ]
    body += "<h2>Total response by outcome</h2>" + table(
        ["outcome", "response", "95% interval", "excludes 0"], outcome_rows
    )
    return page("Shock transmission", "Shock transmission map (synthetic)", body)
