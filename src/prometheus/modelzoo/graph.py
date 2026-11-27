"""The web: models, baselines, data, hypotheses, findings and pipelines, and the edges between them.

The graph is built from `registry` and from the recorded studies, never typed by hand, and
`validate` refuses a registry that disagrees with the repository: a module that does not import, a
symbol that is missing, a hypothesis no study recorded, a finding that is not in
`docs/RESULTS_AND_LIMITATIONS.md`, a dataset that is not committed. An edge in this graph is
therefore a fact about the code and the records, not a drawing.

Node kinds: `model`, `baseline`, `not_built`, `dataset`, `hypothesis`, `finding`, `pipeline`.
Edge kinds: `baseline_for` (A is what B is judged against), `extends`, `alternative_to`, `uses`,
`uses_data`, `tested_by`, `reported_in`, `feeds` (the output of A is the input of B in a pipeline)
and `runs` (a pipeline contains a model).
"""

from __future__ import annotations

import importlib
import json
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from prometheus.modelzoo.registry import ENTRIES, PIPELINES, Entry

ROOT = Path(__file__).resolve().parents[3]
NUMERICS = ROOT / "docs" / "numerics"
DATA = ROOT / "data_cache"
FINDINGS = ROOT / "docs" / "RESULTS_AND_LIMITATIONS.md"
VERDICTS = ("SUPPORTED", "INCONCLUSIVE", "CONTRADICTED")


def recorded_verdicts() -> dict[str, str]:
    """Hypothesis label -> verdict, read from every recorded `modelzoo_*.json`."""
    out: dict[str, str] = {}
    for path in sorted(NUMERICS.glob("modelzoo_*.json")):
        record = json.loads(path.read_text())
        for key, value in record.items():
            if not re.fullmatch(r"Z-[A-Z]\d+", key):
                continue
            verdict = (
                value
                if isinstance(value, str)
                else value.get("verdict")
                if isinstance(value, dict)
                else None
            )
            if verdict in VERDICTS:
                out[key] = str(verdict)
    return out


def finding_numbers() -> set[int]:
    return {
        int(m.group(1))
        for m in re.finditer(r"^## Finding (\d+) \(", FINDINGS.read_text(), re.MULTILINE)
    }


def entry(entry_id: str) -> Entry:
    for e in ENTRIES:
        if e.id == entry_id:
            return e
    raise KeyError(entry_id)


def validate() -> list[str]:
    """Return every disagreement between the registry and the repository (empty when consistent)."""
    problems: list[str] = []
    ids = [e.id for e in ENTRIES]
    for duplicate, count in Counter(ids).items():
        if count > 1:
            problems.append(f"duplicate id {duplicate}")
    known = set(ids)
    verdicts = recorded_verdicts()
    findings = finding_numbers()
    for e in ENTRIES:
        if e.status not in ("implemented", "existing", "not_built"):
            problems.append(f"{e.id}: unknown status {e.status!r}")
        if e.status == "not_built":
            if not e.reason or e.module:
                problems.append(f"{e.id}: a model that is not built needs a reason and no module")
        else:
            try:
                module = importlib.import_module(e.module)
            except ImportError as error:
                problems.append(f"{e.id}: module {e.module} does not import ({error})")
            else:
                if not hasattr(module, e.symbol):
                    problems.append(f"{e.id}: {e.module} has no {e.symbol}")
        for target in e.baselines:
            if target not in known:
                problems.append(f"{e.id}: unknown baseline {target}")
        for kind, target in e.relations:
            if target not in known:
                problems.append(f"{e.id}: {kind} unknown model {target}")
        for label in e.hypotheses:
            if label not in verdicts:
                problems.append(f"{e.id}: hypothesis {label} has no recorded verdict")
        if e.benchmarked and not e.hypotheses:
            problems.append(f"{e.id}: marked benchmarked with no hypothesis")
        if e.hypotheses and e.finding is None:
            problems.append(f"{e.id}: tested but reported in no finding")
        if e.finding is not None and e.finding not in findings:
            problems.append(f"{e.id}: Finding {e.finding} is not in the results document")
        for name in e.data:
            if not name.startswith("simulated:") and not (DATA / name).exists():
                problems.append(f"{e.id}: dataset {name} is not committed")
    for p in PIPELINES:
        for step in p.steps:
            if step not in known:
                problems.append(f"pipeline {p.id}: unknown step {step}")
        for label in p.hypotheses:
            if label not in verdicts:
                problems.append(f"pipeline {p.id}: hypothesis {label} has no recorded verdict")
        if p.finding is not None and p.finding not in findings:
            problems.append(f"pipeline {p.id}: Finding {p.finding} is not in the results document")
        try:
            module = importlib.import_module(p.module)
        except ImportError as error:
            problems.append(f"pipeline {p.id}: module {p.module} does not import ({error})")
        else:
            if not hasattr(module, p.symbol):
                problems.append(f"pipeline {p.id}: {p.module} has no {p.symbol}")
    return problems


@dataclass(frozen=True, slots=True)
class Graph:
    nodes: list[dict[str, Any]]
    edges: list[dict[str, str]]

    def neighbours(self, node_id: str) -> list[dict[str, str]]:
        return [e for e in self.edges if node_id in (e["source"], e["target"])]

    def to_json(self) -> dict[str, Any]:
        return {"nodes": self.nodes, "edges": self.edges}


def build_graph() -> Graph:
    verdicts = recorded_verdicts()
    nodes: dict[str, dict[str, Any]] = {}
    edges: list[dict[str, str]] = []

    def add_edge(source: str, target: str, kind: str) -> None:
        edge = {"source": source, "target": target, "kind": kind}
        if edge not in edges:
            edges.append(edge)

    for e in ENTRIES:
        kind = (
            "not_built"
            if e.status == "not_built"
            else "baseline"
            if e.role == "baseline"
            else "model"
        )
        nodes[e.id] = {
            "id": e.id,
            "label": e.name,
            "kind": kind,
            "family": e.family,
            "status": e.status,
            "source": e.source,
            "task": e.task or e.reason,
            "reference": e.reference,
            "benchmarked": e.benchmarked,
        }
    for e in ENTRIES:
        for base in e.baselines:
            add_edge(base, e.id, "baseline_for")
        for kind, target in e.relations:
            add_edge(e.id, target, kind)
        for name in e.data:
            node_id = f"data:{name}"
            nodes.setdefault(
                node_id,
                {
                    "id": node_id,
                    "label": name.removeprefix("simulated:"),
                    "kind": "dataset",
                    "family": "data",
                    "status": "simulated" if name.startswith("simulated:") else "committed",
                },
            )
            add_edge(e.id, node_id, "uses_data")
        for label in e.hypotheses:
            hyp_id = f"hyp:{label}"
            nodes.setdefault(
                hyp_id,
                {
                    "id": hyp_id,
                    "label": label,
                    "kind": "hypothesis",
                    "family": "tests",
                    "status": verdicts.get(label, "unrecorded"),
                },
            )
            add_edge(e.id, hyp_id, "tested_by")
        if e.finding is not None:
            node_id = f"finding:{e.finding}"
            nodes.setdefault(
                node_id,
                {
                    "id": node_id,
                    "label": f"Finding {e.finding}",
                    "kind": "finding",
                    "family": "findings",
                    "status": "recorded",
                },
            )
            for label in e.hypotheses:
                add_edge(f"hyp:{label}", node_id, "reported_in")
    for p in PIPELINES:
        node_id = f"pipeline:{p.id}"
        nodes[node_id] = {
            "id": node_id,
            "label": p.name,
            "kind": "pipeline",
            "family": "pipelines",
            "status": "implemented",
            "task": p.note,
        }
        for step in p.steps:
            add_edge(node_id, step, "runs")
        for a, b in zip(p.steps, p.steps[1:], strict=False):
            add_edge(a, b, "feeds")
        for label in p.hypotheses:
            hyp_id = f"hyp:{label}"
            nodes.setdefault(
                hyp_id,
                {
                    "id": hyp_id,
                    "label": label,
                    "kind": "hypothesis",
                    "family": "tests",
                    "status": verdicts.get(label, "unrecorded"),
                },
            )
            add_edge(node_id, hyp_id, "tested_by")
            if p.finding is not None:
                finding_id = f"finding:{p.finding}"
                nodes.setdefault(
                    finding_id,
                    {
                        "id": finding_id,
                        "label": f"Finding {p.finding}",
                        "kind": "finding",
                        "family": "findings",
                        "status": "recorded",
                    },
                )
                add_edge(hyp_id, finding_id, "reported_in")
    return Graph(list(nodes.values()), edges)


def coverage() -> dict[str, Any]:
    """What became of each requested model, overall and by section of the request."""
    requested = [e for e in ENTRIES if e.role == "model"]
    by_status = Counter(e.status for e in requested)
    sections: dict[str, Counter[str]] = {}
    for e in requested:
        for section in e.source.split():
            sections.setdefault(section, Counter())[e.status] += 1
    verdicts = Counter(recorded_verdicts().values())
    return {
        "requested": len(requested),
        "by_status": dict(by_status),
        "benchmarked": sum(1 for e in requested if e.benchmarked),
        "by_section": {s: dict(c) for s, c in sorted(sections.items())},
        "hypotheses": dict(verdicts),
        "baselines": sum(1 for e in ENTRIES if e.role == "baseline"),
    }


def to_mermaid(families: tuple[str, ...] | None = None) -> str:
    """A flowchart of the built models, their baselines and the pipelines' `feeds` edges."""
    graph = build_graph()
    keep = {
        n["id"]
        for n in graph.nodes
        if n["kind"] in ("model", "baseline")
        and n["status"] != "not_built"
        and (families is None or n["family"] in families)
    }
    lines = ["flowchart LR"]
    for n in graph.nodes:
        if n["id"] in keep:
            shape = ("[[{}]]" if n["kind"] == "baseline" else "[{}]").format(f'"{n["label"]}"')
            lines.append(f"    {n['id']}{shape}")
    arrows = {
        "baseline_for": "-.->",
        "feeds": "==>",
        "extends": "-->",
        "alternative_to": "<-->",
        "uses": "-->",
    }
    for e in graph.edges:
        if e["source"] in keep and e["target"] in keep and e["kind"] in arrows:
            label = "" if e["kind"] in ("feeds",) else f"|{e['kind'].replace('_', ' ')}|"
            lines.append(f"    {e['source']} {arrows[e['kind']]}{label} {e['target']}")
    return "\n".join(lines)
