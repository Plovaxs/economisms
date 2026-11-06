import copy
import json
import subprocess
import sys
from dataclasses import asdict

import pytest

from prometheus.econosim.price_economy import EconomyRunConfig
from prometheus.evidence.contracts import read_evidence_bundle, verified_payload
from prometheus.evidence.export import export_evidence_bundle
from prometheus.evidence.integrity import seal_evidence_bundle
from prometheus.evidence.verify import audit_evidence_bundle, main
from prometheus.hedging.comparison import HedgeComparisonSettings
from prometheus.orchestration.monetary_run import MonetaryRunConfig, run_monetary_simulation


@pytest.fixture(scope="module")
def bundle():
    return run_monetary_simulation(
        MonetaryRunConfig(
            economy=EconomyRunConfig(n_steps=3, productivity_shock_step=2),
            hedge=HedgeComparisonSettings(
                n_train_paths=16, batch_size=8, n_train_epochs=2, risk_eval_n_paths=16
            ),
        )
    ).evidence_bundle


def test_audit_is_strict_by_default_and_legacy_access_requires_explicit_opt_in(bundle):
    with pytest.raises(ValueError, match="required"):
        audit_evidence_bundle(bundle)
    assert (
        audit_evidence_bundle(bundle, require_integrity=False).artifact_integrity
        == "legacy_unsealed"
    )
    audit = audit_evidence_bundle(seal_evidence_bundle(bundle))
    assert audit.valid and audit.artifact_integrity == "sha256_verified"
    assert audit.payload_kind == "monetary" and audit.model_card_count == 1
    assert not audit.external_digest_matched and audit.gate_decision == "NO-GO"


def test_tampered_card_rejected_even_after_an_unsigned_checksum_is_recomputed(bundle):
    changed = copy.deepcopy(bundle)
    changed["model_cards"][0]["content_hash"] = "0" * 64
    with pytest.raises(ValueError, match="fingerprints/count"):
        audit_evidence_bundle(seal_evidence_bundle(changed))


@pytest.mark.parametrize(
    "change",
    [
        "missing_card",
        "duplicate_card",
        "bool_metric",
        "infinite_metric",
        "missing_reviewer",
        "boolean_approver",
        "unknown_gate",
        "bad_date",
        "backwards_sunset",
        "invalid_runtime_hash",
        "bad_dependency",
        "naive_timestamp",
        "unknown_manifest_field",
        "missing_disclaimer",
    ],
)
def test_metadata_cannot_bypass_schema_or_required_review_fields(bundle, change):
    b = copy.deepcopy(bundle)
    card, gate = b["model_cards"][0], b["gate_report"]
    if change == "missing_card":
        b["model_cards"] = []
    elif change == "duplicate_card":
        b["model_cards"].append(copy.deepcopy(card))
    elif change == "bool_metric":
        card["primary_metrics"] = {"cvar": True}
    elif change == "infinite_metric":
        card["primary_metrics"] = {"cvar": float("inf")}
    elif change == "missing_reviewer":
        card["approval_status"] = "CONDITIONAL"
    elif change == "boolean_approver":
        gate.update(decision="GO", scientific_approval=True)
    elif change == "unknown_gate":
        gate["unknown"] = "value"
    elif change == "bad_date":
        card["created_at"] = "2026-99-99"
    elif change == "backwards_sunset":
        gate["sunset_date"] = "1900-01-01"
    elif change == "invalid_runtime_hash":
        b["runtime"]["source_sha256"] = "modified"
    elif change == "bad_dependency":
        b["runtime"]["dependencies"]["numpy"] = None
    elif change == "naive_timestamp":
        b["run_manifest"]["created_at"] = "2026-11-03T00:00:00"
    elif change == "unknown_manifest_field":
        b["run_manifest"]["unexpected"] = "x"
    else:
        del b["disclaimer"]
    with pytest.raises(ValueError):
        verified_payload(b)


def test_inconsistent_metadata_export_preserves_an_existing_artifact(bundle, tmp_path):
    bad = copy.deepcopy(bundle)
    bad["model_cards"][0]["content_hash"] = "0" * 64
    output = tmp_path / "evidence.json"
    output.write_text("previous evidence")
    with pytest.raises(ValueError):
        export_evidence_bundle(bad, output)
    assert output.read_text() == "previous evidence"
    assert list(tmp_path.iterdir()) == [output]


def test_cli_reports_checksum_and_metadata_without_replay(bundle, tmp_path, capsys):
    path = export_evidence_bundle(bundle, tmp_path / "sealed.json")
    pin = read_evidence_bundle(path)["artifact_integrity"]["content_sha256"]
    assert main([str(path), "--expected-content-sha256", pin]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["external_digest_matched"] and report["valid"]
    assert "no numerical replay" in report["scope"]
    assert asdict(audit_evidence_bundle(read_evidence_bundle(path)))["content_sha256"] == pin


def test_offline_auditor_import_does_not_load_torch_or_training_modules():
    code = (
        'import sys; import prometheus.evidence.verify; assert "torch" not in sys.modules; '
        'assert "prometheus.orchestration.rate_study" not in sys.modules'
    )
    result = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, check=False
    )
    assert result.returncode == 0, result.stderr
