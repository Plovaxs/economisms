"""Turn any run result into something a person can read: headline numbers, tables and charts.

Sixteen runners and five explorers produce sixteen-plus differently shaped JSON payloads. Rather
than hand-write a viewer per shape (and miss the seventeenth), this module reads a payload with a
small, explicit set of rules and the window draws whatever they find:

- a **scalar** at the top level is a headline number (`verdict`, `best_point_challenger`, ...);
- an object whose values are all scalars is a **key/value section**;
- an object whose values are objects sharing numeric keys is a **comparison** (the `models` of the
  forecasting labs): a table, plus a bar chart for any chosen column;
- a **list of numbers** is a line chart (a training-loss history);
- a **list of records** is a table, plus a chart of any numeric column against the step/epoch
  column, split into one line per seed/scenario where the x column repeats;
- a **list of strings** called `limitations` or `invalid_reasons` is shown as notes, because a
  result without its limitations is not what this project means by a result.

Anything the rules do not recognise is still reachable in the raw tree, which is built from the
verified payload itself, so nothing is hidden by a heuristic: the heuristic only decides what is
shown *first*.

Everything is bounded (rows, columns, chart points, depth) because a result can be 16 MB; a limit
that cuts something off says so (`truncated`), it never cuts silently.

This module is plain Python and imports neither Qt nor torch.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from prometheus.desktop.forms import humanize

MAX_DEPTH = 6
MAX_TABLE_ROWS = 200
MAX_TABLE_COLUMNS = 14
MAX_CHART_POINTS = 2_000
MAX_LINES = 12
MAX_SECTION_ITEMS = 40
MAX_METRICS = 16
MAX_SCAN = 5_000
MAX_TEXT = 200

NOISE_KEYS = frozenset({"schema_version", "accounting_convention"})
CONFIG_KEYS = frozenset({"config"})
NOTE_KEYS = ("limitations", "invalid_reasons")
X_COLUMNS = ("step", "epoch", "t", "time", "index", "period", "month", "year", "grid_nodes")
GROUP_COLUMNS = ("seed", "scenario", "model", "method", "name", "policy_seed")

Path = tuple[str | int, ...]


@dataclass(frozen=True, slots=True)
class Metric:
    label: str
    value: str
    path: Path = ()


@dataclass(frozen=True, slots=True)
class Section:
    """A flat object shown as label/value rows."""

    title: str
    items: tuple[tuple[str, str], ...]
    truncated: int = 0
    path: Path = ()


@dataclass(frozen=True, slots=True)
class Table:
    title: str
    columns: tuple[str, ...]
    rows: tuple[tuple[str, ...], ...]
    numeric: tuple[bool, ...]
    truncated: int = 0
    path: Path = ()


@dataclass(frozen=True, slots=True)
class Line:
    name: str
    y: tuple[float, ...]
    x: tuple[float, ...] | None = None
    series: str = ""
    """The choice this line belongs to when the chart is `selectable` (a column of a table);
    empty means the line is its own choice."""


@dataclass(frozen=True, slots=True)
class Chart:
    """Lines against a shared axis.

    `selectable` means the lines are alternatives (the numeric columns of one table: choose one),
    not a set to draw together (the per-seed lines of one metric).
    """

    title: str
    x_label: str
    lines: tuple[Line, ...]
    selectable: bool = False
    original_points: int = 0
    path: Path = ()
    band: tuple[str, str] | None = None
    """Names of two lines (lower, upper) whose gap is one uncertainty band: drawn as a wash of a
    single hue between them, because the lines are one series' range, not separate identities."""

    @property
    def choices(self) -> tuple[str, ...]:
        """What the viewer can pick between, in order; empty when everything is drawn together."""
        if not self.selectable:
            return ()
        return tuple(dict.fromkeys(line.series or line.name for line in self.lines))

    def visible(self, choice: str | None = None) -> tuple[Line, ...]:
        """The lines to draw: all of them, or those of the chosen series."""
        if not self.selectable:
            return self.lines
        options = self.choices
        wanted = choice if choice in options else (options[0] if options else None)
        return tuple(line for line in self.lines if (line.series or line.name) == wanted)


@dataclass(frozen=True, slots=True)
class Comparison:
    """Named rows compared on shared numeric columns (`None` where a row has no value)."""

    title: str
    columns: tuple[str, ...]
    rows: tuple[tuple[str, tuple[float | None, ...]], ...]
    path: Path = ()


@dataclass(frozen=True, slots=True)
class ResultView:
    kind: str
    title: str
    verdict: str | None
    metrics: tuple[Metric, ...]
    sections: tuple[Section, ...]
    tables: tuple[Table, ...]
    charts: tuple[Chart, ...]
    comparisons: tuple[Comparison, ...]
    notes: tuple[tuple[str, tuple[str, ...]], ...]
    details: tuple[tuple[str, str], ...]
    """Long descriptive text (a decision rule, a design record): too long to be a headline tile."""
    provenance: tuple[tuple[str, str], ...]
    disclaimer: str
    configuration: tuple[tuple[str, str], ...]
    payload: Mapping[str, Any]
    invalid: bool = False
    """The run reported its own result as invalid (`invalid_reasons` or `valid: false`)."""


# ---------------------------------------------------------------------------------- formatting


def is_number(value: Any) -> bool:
    """A real number: not a bool (a `bool` is an `int` in Python), not NaN or infinite."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    try:
        return math.isfinite(float(value))
    except OverflowError:
        return False


def format_value(value: Any) -> str:
    """A short, honest rendering of one scalar (or a small flat object)."""
    if value is None:
        return "—"
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, int):
        return f"{value:,}"
    if isinstance(value, float):
        if not math.isfinite(value):
            return str(value)
        if value == 0.0:
            return "0"
        magnitude = abs(value)
        if magnitude < 1e-3 or magnitude >= 1e7:
            return f"{value:.3e}"
        return f"{value:.4g}" if magnitude < 1e4 else f"{value:,.1f}"
    if isinstance(value, str):
        return value if len(value) <= MAX_TEXT else value[: MAX_TEXT - 1] + "…"
    if isinstance(value, Mapping) and all(
        not isinstance(v, (Mapping, list, tuple)) for v in value.values()
    ):
        return ", ".join(f"{k}={format_value(v)}" for k, v in list(value.items())[:6])
    if isinstance(value, (list, tuple)):
        return f"[{len(value)} items]"
    return str(value)[:MAX_TEXT]


def _is_scalar(value: Any) -> bool:
    return value is None or isinstance(value, (bool, int, float, str))


_HEX = frozenset("0123456789abcdef")
MONEY_UNIT = " (minor units)"


def _is_digest(value: Any) -> bool:
    return isinstance(value, str) and len(value) == 64 and _HEX.issuperset(value)


def _is_money(value: Any) -> bool:
    return (
        isinstance(value, Mapping)
        and set(value) == {"minor_units", "currency"}
        and isinstance(value["minor_units"], int)
        and not isinstance(value["minor_units"], bool)
    )


def _is_fraction(value: Any) -> bool:
    return (
        isinstance(value, Mapping)
        and set(value) == {"numerator", "denominator"}
        and is_number(value["numerator"])
        and is_number(value["denominator"])
        and value["denominator"] != 0
    )


def _is_label_column(name: str) -> bool:
    last = name.split(" › ")[-1]
    return last in GROUP_COLUMNS or last.endswith("seed")


def _flatten_record(row: Mapping[str, Any], prefix: str = "", depth: int = 0) -> dict[str, Any]:
    """One record as flat `name -> scalar`: an exact Money becomes its minor units, an exact
    Fraction its value, a nested object its own flattened entries (two levels); lists are left to
    the raw tree."""
    flat: dict[str, Any] = {}
    for key, value in row.items():
        name = f"{prefix} › {key}" if prefix else str(key)
        if _is_scalar(value):
            flat[name] = value
        elif _is_money(value):
            flat[name + MONEY_UNIT] = value["minor_units"]
        elif _is_fraction(value):
            flat[name] = value["numerator"] / value["denominator"]
        elif isinstance(value, Mapping) and depth < 1:
            flat.update(_flatten_record(value, name, depth + 1))
    return flat


def _column_label(name: str) -> str:
    parts = []
    for part in name.split(" › "):
        if part.endswith(MONEY_UNIT):
            parts.append(humanize(part[: -len(MONEY_UNIT)]) + MONEY_UNIT)
        else:
            parts.append(humanize(part))
    return " › ".join(parts)


def _stride(values: Sequence[float], limit: int = MAX_CHART_POINTS) -> tuple[float, ...]:
    if len(values) <= limit:
        return tuple(values)
    step = math.ceil(len(values) / limit)
    kept = list(values[::step])
    if (len(values) - 1) % step:
        kept.append(values[-1])
    return tuple(kept)


def _stride_pair(
    x: Sequence[float], y: Sequence[float], limit: int = MAX_CHART_POINTS
) -> tuple[tuple[float, ...], tuple[float, ...]]:
    if len(y) <= limit:
        return tuple(x), tuple(y)
    step = math.ceil(len(y) / limit)
    xs, ys = list(x[::step]), list(y[::step])
    if (len(y) - 1) % step:
        xs.append(x[-1])
        ys.append(y[-1])
    return tuple(xs), tuple(ys)


def _label(path: Path, fallback: str) -> str:
    names = [humanize(part) if isinstance(part, str) else f"[{part}]" for part in path]
    return " › ".join(names) if names else fallback


# ---------------------------------------------------------------------------------- the walk


@dataclass(slots=True)
class _Collected:
    metrics: list[Metric]
    sections: list[Section]
    tables: list[Table]
    charts: list[Chart]
    comparisons: list[Comparison]
    notes: list[tuple[str, tuple[str, ...]]]
    configuration: list[tuple[str, str]]
    details: list[tuple[str, str]]
    hashes: list[tuple[str, str]]
    verdict: str | None = None
    invalid: bool = False


def _named_lines(title: str, node: Mapping[str, Any], path: Path) -> Chart | None:
    """An object of several equal-length lists of numbers, drawn together as named lines.

    An `x` list (or one of the usual step names) is the horizontal axis and `x_label` names it;
    without either the axis is the position. A producer that wants several curves on one chart
    -- the percentile bands of a fan, the price and payoff of an option -- says so by shape.
    """
    label = node.get("x_label")
    body = {key: value for key, value in node.items() if key not in ("x_label", "band")}
    if len(body) < 2 or not all(
        isinstance(value, list) and _number_list(value) for value in body.values()
    ):
        return None
    if len({len(value) for value in body.values()}) != 1:
        return None
    x_key = "x" if "x" in body else next((key for key in X_COLUMNS if key in body), None)
    names = [key for key in body if key != x_key]
    if not names:
        return None
    length = len(body[names[0]])
    positions = (
        [float(v) for v in body[x_key]] if x_key is not None else [float(i) for i in range(length)]
    )
    lines = []
    for name in names[:MAX_LINES]:
        xs, ys = _stride_pair(positions, [float(v) for v in body[name]])
        lines.append(Line(humanize(name) if name.islower() else name, ys, xs))
    shown = label if isinstance(label, str) else (humanize(x_key) if x_key else "Index")
    shown_names = {line.name for line in lines}
    wanted = node.get("band")
    band = None
    if isinstance(wanted, list) and len(wanted) == 2 and all(isinstance(n, str) for n in wanted):
        pair = tuple(humanize(n) if n.islower() else n for n in wanted)
        if pair[0] != pair[1] and set(pair) <= shown_names:
            band = (pair[0], pair[1])
    return Chart(title, shown, tuple(lines), original_points=length, path=path, band=band)


def _is_comparison(node: Mapping[str, Any]) -> bool:
    if len(node) < 2:
        return False
    rows = list(node.values())
    if not all(isinstance(row, Mapping) for row in rows):
        return False
    return len(_comparison_columns(node)) >= 1


def _comparison_columns(node: Mapping[str, Any]) -> tuple[str, ...]:
    counts: dict[str, int] = {}
    for row in node.values():
        for key, value in row.items():
            if is_number(value):
                counts[key] = counts.get(key, 0) + 1
    needed = max(1, (len(node) + 1) // 2)
    return tuple(key for key, count in counts.items() if count >= needed)[:MAX_TABLE_COLUMNS]


def _comparison(title: str, node: Mapping[str, Any], path: Path) -> Comparison:
    columns = _comparison_columns(node)
    rows = tuple(
        (
            str(name),
            tuple(float(row[column]) if is_number(row.get(column)) else None for column in columns),
        )
        for name, row in list(node.items())[:MAX_TABLE_ROWS]
    )
    return Comparison(title, columns, rows, path)


def _records(items: Sequence[Any]) -> list[Mapping[str, Any]] | None:
    sample = items[:MAX_SCAN]
    if not sample or not all(isinstance(item, Mapping) for item in sample):
        return None
    return list(sample)


def _record_table(title: str, rows: list[dict[str, Any]], total: int, path: Path) -> Table | None:
    columns: list[str] = []
    for row in rows[:50]:
        for key in row:
            if key not in columns:
                columns.append(key)
    columns = [
        column
        for column in columns
        if not all(_is_digest(row.get(column)) for row in rows[:MAX_TABLE_ROWS])
    ][:MAX_TABLE_COLUMNS]
    if not columns:
        return None
    shown = rows[:MAX_TABLE_ROWS]
    numeric = tuple(
        all(is_number(row.get(column)) or row.get(column) is None for row in shown)
        and any(is_number(row.get(column)) for row in shown)
        for column in columns
    )
    return Table(
        title,
        tuple(_column_label(column) for column in columns),
        tuple(tuple(format_value(row.get(column)) for column in columns) for row in shown),
        numeric,
        truncated=max(0, total - len(shown)),
        path=path,
    )


def _x_column(rows: list[dict[str, Any]], numeric: list[str]) -> str | None:
    for candidate in X_COLUMNS:
        if candidate in numeric and all(is_number(row.get(candidate)) for row in rows):
            return candidate
    return None


def _group_column(rows: list[dict[str, Any]], x_name: str | None, numeric: list[str]) -> str | None:
    if x_name is None:
        return None
    x_values = [float(row[x_name]) for row in rows]
    if all(later > earlier for earlier, later in zip(x_values, x_values[1:], strict=False)):
        return None  # the x column already orders a single line
    for candidate in GROUP_COLUMNS:
        if candidate == x_name or not all(
            candidate in row and _is_scalar(row[candidate]) for row in rows
        ):
            continue
        distinct = {row[candidate] for row in rows}
        if 2 <= len(distinct) <= MAX_LINES:
            return candidate
    return None


def _record_chart(title: str, rows: list[dict[str, Any]], path: Path) -> Chart | None:
    if len(rows) < 2:
        return None
    numeric = [key for key in rows[0] if all(is_number(row.get(key)) for row in rows)]
    x_name = _x_column(rows, numeric)
    group = _group_column(rows, x_name, numeric)
    plotted = [
        key
        for key in numeric
        if key not in (x_name, group)
        and not _is_label_column(key)  # a seed labels a line, it is not a measurement
        and len({row[key] for row in rows}) > 1  # a constant is not worth a line
    ][:MAX_TABLE_COLUMNS]
    if not plotted:
        return None
    lines: list[Line] = []
    for column in plotted:
        if x_name is not None and group is not None:
            # one line per group value (a seed, a scenario); the viewer picks the column
            for value in sorted({row[group] for row in rows}, key=str):
                members = [row for row in rows if row[group] == value]
                xs, ys = _stride_pair(
                    [float(row[x_name]) for row in members],
                    [float(row[column]) for row in members],
                )
                label = f"{_column_label(group)} {format_value(value)}"
                lines.append(Line(label, ys, xs, series=_column_label(column)))
        else:
            positions = (
                [float(row[x_name]) for row in rows]
                if x_name is not None
                else [float(i) for i in range(len(rows))]
            )
            xs, ys = _stride_pair(positions, [float(row[column]) for row in rows])
            lines.append(Line(_column_label(column), ys, xs, series=_column_label(column)))
    return Chart(
        title,
        _column_label(x_name) if x_name else "Row",
        tuple(lines),
        selectable=True,
        original_points=len(rows),
        path=path,
    )


def _number_list(items: Sequence[Any]) -> bool:
    return len(items) >= 3 and all(is_number(item) for item in items[:MAX_SCAN])


def _walk(node: Any, path: Path, out: _Collected, depth: int) -> None:
    if depth > MAX_DEPTH:
        return
    if isinstance(node, Mapping):
        _walk_mapping(node, path, out, depth)
    elif isinstance(node, list):
        _walk_list(node, path, out, depth)


def _walk_mapping(node: Mapping[str, Any], path: Path, out: _Collected, depth: int) -> None:
    scalars = [(k, v) for k, v in node.items() if _is_scalar(v) and k not in NOISE_KEYS]
    if path == ():
        for key, value in scalars:
            label = humanize(str(key))
            if _is_digest(value):
                out.hashes.append((label, str(value)))
            elif isinstance(value, str) and (len(value) > 48 or "\n" in value):
                out.details.append((label, value))
            elif len(out.metrics) < MAX_METRICS:
                out.metrics.append(Metric(label, format_value(value), (key,)))
            if key == "verdict" and isinstance(value, str):
                out.verdict = value
            if key == "valid" and value is False:
                out.invalid = True
        out.metrics.sort(key=lambda metric: metric.path != ("verdict",))  # the verdict leads
    elif scalars:
        shown = scalars[:MAX_SECTION_ITEMS]
        out.sections.append(
            Section(
                _label(path, "Values"),
                tuple((humanize(str(k)), format_value(v)) for k, v in shown),
                truncated=len(scalars) - len(shown),
                path=path,
            )
        )
    for key, value in node.items():
        child = (*path, key)
        if key in CONFIG_KEYS and not _is_scalar(value):
            if path == ():  # a nested `config` repeats the top one; it stays in the raw tree
                out.configuration.extend(_flatten_configuration(value))
            continue
        if isinstance(value, Mapping):
            lines = _named_lines(_label(child, str(key)), value, child)
            if lines is not None:
                out.charts.append(lines)
            elif _is_comparison(value):
                out.comparisons.append(_comparison(_label(child, str(key)), value, child))
            else:
                _walk_mapping(value, child, out, depth + 1)
        elif isinstance(value, list):
            if path == () and key in NOTE_KEYS and all(isinstance(v, str) for v in value):
                if value:
                    out.notes.append((humanize(key), tuple(value)))
                    if key == "invalid_reasons":
                        out.invalid = True
            else:
                _walk_list(value, child, out, depth + 1)


def _flatten_configuration(value: Any, prefix: str = "") -> list[tuple[str, str]]:
    items: list[tuple[str, str]] = []
    if isinstance(value, Mapping):
        flat = all(not isinstance(v, (Mapping, list)) for v in value.values())
        if flat and prefix:
            return [(prefix, format_value(value))]
        for key, child in value.items():
            name = f"{prefix} › {humanize(str(key))}" if prefix else humanize(str(key))
            items.extend(_flatten_configuration(child, name))
    elif isinstance(value, list):
        items.append(
            (prefix, format_value(value) if len(value) > 6 else ", ".join(map(str, value)))
        )
    else:
        items.append((prefix, format_value(value)))
    return items[:200]


def _walk_list(items: list[Any], path: Path, out: _Collected, depth: int) -> None:
    title = _label(path, "Values")
    if not items:
        return
    if _number_list(items):
        numbers = [float(v) for v in items[: MAX_SCAN * 20] if is_number(v)]
        xs, ys = _stride_pair([float(i) for i in range(len(numbers))], numbers)
        out.charts.append(
            Chart(title, "Index", (Line(title, ys, xs),), original_points=len(items), path=path)
        )
        return
    if all(isinstance(item, list) and _number_list(item) for item in items[:MAX_LINES]):
        lines = []
        for position, row in enumerate(items[:MAX_LINES]):
            numbers = [float(v) for v in row if is_number(v)]
            xs, ys = _stride_pair([float(i) for i in range(len(numbers))], numbers)
            lines.append(Line(f"Series {position + 1}", ys, xs))
        out.charts.append(
            Chart(title, "Index", tuple(lines), original_points=len(items[0]), path=path)
        )
        return
    sample = _records(items)
    if sample is None:
        return
    records = [_flatten_record(row) for row in sample]
    table = _record_table(title, records, len(items), path)
    if table is not None:
        out.tables.append(table)
    chart = _record_chart(title, records, path)
    if chart is not None:
        out.charts.append(chart)


# ---------------------------------------------------------------------------------- entry points


def analyze_payload(
    payload: Mapping[str, Any],
    *,
    kind: str,
    title: str,
    provenance: Sequence[tuple[str, str]] = (),
    disclaimer: str = "",
) -> ResultView:
    """Read one result payload (a runner's, or an explorer's) into a `ResultView`."""
    out = _Collected([], [], [], [], [], [], [], [], [])
    _walk(payload, (), out, 0)
    if payload.get("valid") is False:
        out.invalid = True
    if out.hashes:
        out.sections.append(Section("Content hashes", tuple(out.hashes)))
    return ResultView(
        kind=kind,
        title=title,
        verdict=out.verdict,
        metrics=tuple(out.metrics),
        sections=tuple(out.sections),
        tables=tuple(out.tables),
        charts=tuple(out.charts),
        comparisons=tuple(out.comparisons),
        notes=tuple(out.notes),
        details=tuple(out.details),
        provenance=tuple(provenance),
        disclaimer=disclaimer,
        configuration=tuple(out.configuration),
        payload=payload,
        invalid=out.invalid,
    )


def provenance_of(bundle: Mapping[str, Any]) -> tuple[tuple[str, str], ...]:
    """The facts that identify exactly which run, code and environment produced a result."""
    context = bundle.get("job_context", {})
    integrity = bundle.get("artifact_integrity", {})
    manifest = bundle.get("run_manifest", {})
    runtime = bundle.get("runtime", {})
    dependencies = runtime.get("dependencies", {}) if isinstance(runtime, Mapping) else {}
    rows: list[tuple[str, str]] = [
        ("Job", str(context.get("job_id", "—"))),
        ("Attempt", str(context.get("attempt", "—"))),
        ("Recipe SHA-256", str(context.get("recipe_sha256", "—"))),
        ("Artifact SHA-256", str(integrity.get("content_sha256", "—"))),
        ("Result hash", str(manifest.get("result_hash", "—"))),
        ("Run id", str(manifest.get("run_id", "—"))),
        ("Created", str(manifest.get("created_at", "—"))),
        ("Python", str(runtime.get("python", "—")) if isinstance(runtime, Mapping) else "—"),
        ("Platform", str(runtime.get("platform", "—")) if isinstance(runtime, Mapping) else "—"),
        (
            "Source SHA-256",
            str(runtime.get("source_sha256", "—")) if isinstance(runtime, Mapping) else "—",
        ),
    ]
    rows.extend((name, str(version)) for name, version in dependencies.items())
    return tuple(rows)


def build_result_view(bundle: Mapping[str, Any], *, title: str | None = None) -> ResultView:
    """A `ResultView` of a verified artifact bundle, as read back through `ArtifactStore.get`."""
    context = bundle.get("job_context", {})
    kind = str(context.get("kind", "")) if isinstance(context, Mapping) else ""
    payload = bundle.get(kind)
    if not isinstance(payload, Mapping):
        raise ValueError("the artifact has no result payload for its own kind")
    return analyze_payload(
        payload,
        kind=kind,
        title=title or humanize(kind),
        provenance=provenance_of(bundle),
        disclaimer=str(bundle.get("disclaimer", "")),
    )
