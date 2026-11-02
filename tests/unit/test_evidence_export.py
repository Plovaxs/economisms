import json
from datetime import date

from prometheus.evidence.export import (
    SIMULATION_DISCLAIMER,
    SOURCE_TAG,
    build_evidence_bundle,
    export_evidence_bundle,
)
from prometheus.evidence.gate_report import GateDecisionForm
from prometheus.evidence.model_card import ModelCard
from prometheus.experiments.manifest import RunManifest


def _dummy_card() -> ModelCard:
    return ModelCard(
        model_id="test-model",
        model_type="MLP",
        framework="PyTorch 2.0",
        version="0.1.0",
        license="MIT",
        content_hash="abc123",
        intended_use="Research only.",
        prohibited_use="Live trading.",
        input_schema_summary="three floats",
        training_data_summary="synthetic GBM paths",
        primary_metrics={"cvar": 1.0},
        metric_uncertainty_note="single seed",
        failure_modes=("not OOD-tested",),
        independent_reviewer=None,
        approval_status="NOT REVIEWED",
        created_at=date(2026, 1, 1),
    )


def _dummy_gate_report() -> GateDecisionForm:
    return GateDecisionForm(
        gate="R0",
        artifact_version="0.1.0",
        scope_enabled=("local simulation",),
        scope_prohibited=("live trading",),
        evidence_index=("CHECKLIST_STATUS.md",),
        open_findings=(),
        scientific_approval=None,
        security_ops_approval=None,
        legal_compliance_assessment=None,
        decision="NO-GO",
        decided_at=date(2026, 1, 1),
        sunset_date=None,
    )


def test_bundle_always_carries_disclaimer_and_source_tag() -> None:
    bundle = build_evidence_bundle(None, [_dummy_card()], _dummy_gate_report())
    assert bundle["disclaimer"] == SIMULATION_DISCLAIMER
    assert bundle["source_tag"] == SOURCE_TAG


def test_bundle_includes_run_manifest_when_provided() -> None:
    manifest = RunManifest(
        run_id="run-1",
        created_at="2026-01-01T00:00:00+00:00",
        seed=1,
        config={"a": 1},
        result_hash="h",
    )
    bundle = build_evidence_bundle(manifest, [_dummy_card()], _dummy_gate_report())
    assert bundle["run_manifest"]["run_id"] == "run-1"
    assert bundle["run_manifest"]["result_hash"] == "h"


def test_bundle_run_manifest_is_none_when_not_provided() -> None:
    bundle = build_evidence_bundle(None, [_dummy_card()], _dummy_gate_report())
    assert bundle["run_manifest"] is None


def test_export_writes_valid_json_round_trip(tmp_path) -> None:
    bundle = build_evidence_bundle(None, [_dummy_card()], _dummy_gate_report())
    out_path = export_evidence_bundle(bundle, tmp_path / "evidence.json")

    assert out_path.exists()
    loaded = json.loads(out_path.read_text())
    assert loaded["disclaimer"] == SIMULATION_DISCLAIMER
    assert loaded["gate_report"]["decision"] == "NO-GO"
    assert loaded["model_cards"][0]["model_id"] == "test-model"


def test_export_serializes_dates_and_tuples_correctly(tmp_path) -> None:
    bundle = build_evidence_bundle(None, [_dummy_card()], _dummy_gate_report())
    out_path = export_evidence_bundle(bundle, tmp_path / "evidence.json")
    loaded = json.loads(out_path.read_text())
    assert loaded["gate_report"]["decided_at"] == "2026-01-01"
    assert loaded["gate_report"]["scope_prohibited"] == ["live trading"]
