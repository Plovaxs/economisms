"""The model registry and its graph: every claim in them is checked against the repository."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from prometheus.modelzoo import graph
from prometheus.modelzoo.__main__ import main as modelzoo_main
from prometheus.modelzoo.registry import ENTRIES, PIPELINES

ROOT = Path(__file__).resolve().parents[2]
EXPORTED = ROOT / "frontend" / "src" / "atlas" / "graph.json"


def test_the_registry_agrees_with_the_repository() -> None:
    assert graph.validate() == []


def test_a_broken_registry_is_caught(monkeypatch: pytest.MonkeyPatch) -> None:
    from dataclasses import replace

    broken = (
        replace(ENTRIES[0], symbol="does_not_exist"),
        replace(ENTRIES[1], module="prometheus.no_such_module"),
        replace(ENTRIES[2], baselines=("ghost",)),
        replace(
            next(e for e in ENTRIES if e.id == "fno"),
            hypotheses=("Z-O1", "Z-X9"),
            finding=999,
            data=("not_a_file.csv",),
        ),
        replace(next(e for e in ENTRIES if e.status == "not_built"), reason=""),
        ENTRIES[3],
        ENTRIES[3],
    )
    monkeypatch.setattr(graph, "ENTRIES", broken)
    problems = "\n".join(graph.validate())
    for expected in (
        "has no does_not_exist",
        "does not import",
        "unknown baseline ghost",
        "Z-X9 has no recorded verdict",
        "Finding 999 is not in the results document",
        "not_a_file.csv is not committed",
        "needs a reason",
        "duplicate id",
    ):
        assert expected in problems


def test_ids_are_unique_and_every_requested_model_has_a_status_and_a_source() -> None:
    ids = [e.id for e in ENTRIES]
    assert len(ids) == len(set(ids))
    for e in ENTRIES:
        assert e.status in ("implemented", "existing", "not_built")
        if e.role == "model":
            assert e.source, f"{e.id} has no source section"
        if e.status == "not_built":
            assert e.reason and not e.module
    assert {e.source.split()[0][0] for e in ENTRIES if e.source} == {"A", "B"}


def test_coverage_adds_up() -> None:
    c = graph.coverage()
    assert (
        sum(c["by_status"].values())
        == c["requested"]
        == sum(1 for e in ENTRIES if e.role == "model")
    )
    assert c["baselines"] == sum(1 for e in ENTRIES if e.role == "baseline")
    assert c["benchmarked"] == sum(1 for e in ENTRIES if e.benchmarked)
    assert sum(c["hypotheses"].values()) == len(graph.recorded_verdicts())
    # every implemented model that is compared with a baseline has a baseline and a hypothesis
    for e in ENTRIES:
        if e.benchmarked:
            assert e.hypotheses and e.finding is not None


def test_the_graph_is_closed_and_its_edges_have_known_kinds() -> None:
    g = graph.build_graph()
    ids = {n["id"] for n in g.nodes}
    kinds = {
        "baseline_for",
        "extends",
        "alternative_to",
        "uses",
        "uses_data",
        "tested_by",
        "reported_in",
        "feeds",
        "runs",
    }
    assert len(ids) == len(g.nodes)
    for edge in g.edges:
        assert edge["source"] in ids and edge["target"] in ids and edge["kind"] in kinds
    node_kinds = {n["kind"] for n in g.nodes}
    assert {
        "model",
        "baseline",
        "not_built",
        "dataset",
        "hypothesis",
        "finding",
        "pipeline",
    } == node_kinds
    # every hypothesis node carries its recorded verdict
    assert {n["status"] for n in g.nodes if n["kind"] == "hypothesis"} <= set(graph.VERDICTS)


def test_the_pipelines_feed_models_in_order_and_meet_at_the_risk_metric() -> None:
    g = graph.build_graph()
    feeds = {(e["source"], e["target"]) for e in g.edges if e["kind"] == "feeds"}
    for p in PIPELINES:
        for a, b in zip(p.steps, p.steps[1:], strict=False):
            assert (a, b) in feeds
    assert ("delta_hedge", "titan_risk_metrics") in feeds and ("qae", "titan_risk_metrics") in feeds


def test_mermaid_export_is_a_flowchart_of_built_models() -> None:
    text = graph.to_mermaid()
    assert text.startswith("flowchart LR") and "fno" in text and "ferminet" not in text
    assert "==>" in text and "-.->" in text  # feeds and baseline edges


def test_the_exported_graph_the_web_app_imports_is_current() -> None:
    """Regenerate with: econosim modelzoo graph > frontend/src/atlas/graph.json"""
    assert json.loads(EXPORTED.read_text()) == json.loads(json.dumps(graph.build_graph().to_json()))


def test_the_command_line(capsys: pytest.CaptureFixture[str]) -> None:
    assert modelzoo_main(["validate"]) == 0
    assert "consistent" in capsys.readouterr().out
    assert modelzoo_main(["coverage"]) == 0
    assert json.loads(capsys.readouterr().out)["requested"] > 100
    assert modelzoo_main(["neighbours", "fno"]) == 0
    assert "baseline_for" in capsys.readouterr().out
    assert modelzoo_main(["neighbours", "no_such_model"]) == 2
    capsys.readouterr()
    assert modelzoo_main(["verdicts"]) == 0 and "Z-O3" in capsys.readouterr().out
    assert modelzoo_main(["list", "--status", "existing"]) == 0
    assert "pinn" in capsys.readouterr().out
    assert modelzoo_main(["graph", "--format", "mermaid"]) == 0
    assert capsys.readouterr().out.startswith("flowchart")
