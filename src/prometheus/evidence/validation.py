"""Structural metadata checks and computational/model-card fingerprint binding.

These checks cannot authenticate an author, validate the numerical result,
or grant scientific/deployment approval. Actual replay remains necessary.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping
from dataclasses import fields
from datetime import date, datetime
from typing import Any

from prometheus.evidence.gate_report import GateDecisionForm
from prometheus.evidence.integrity import is_sha256
from prometheus.evidence.model_card import ModelCard, is_finite_metric
from prometheus.experiments.manifest import RunManifest


def _record(value: Any, model: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != {item.name for item in fields(model)}:
        raise ValueError(f"{label} requires exactly the complete metadata fields")
    return dict(value)


def _text(value: Any, label: str, *, optional: bool = False) -> None:
    if optional and value is None:
        return
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be nonempty text")


def _date(value: Any, label: str) -> date:
    if type(value) is date:
        return value
    if not isinstance(value, str):
        raise ValueError(f"{label} requires an ISO date")
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"{label} requires an ISO date") from exc


def _texts(value: Any, label: str) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)):
        raise ValueError(f"{label} requires a text sequence")
    for item in value:
        _text(item, label)
    return tuple(value)


def _declared_hashes(kind: str, payload: Mapping[str, Any]) -> list[str]:
    if "valid" in payload and type(payload["valid"]) is not bool:
        raise ValueError("payload valid status must be bool")
    if payload.get("valid") is False or kind in ("economy", "monetary_operations"):
        return []
    if kind in ("simulation", "benchmark"):
        values = [payload.get("policy_content_hash")]
    elif kind == "monetary":
        training = payload.get("training")
        if not isinstance(training, dict):
            raise ValueError("monetary training metadata must be an object")
        values = [training.get("policy_content_hash")]
    else:
        source = payload.get("conditional_study") if kind == "mixture_study" else payload
        if not isinstance(source, Mapping) or not isinstance(source.get("training"), list):
            raise ValueError("training fingerprints require a training metadata list")
        values = [
            item.get("policy_content_hash") if isinstance(item, dict) else None
            for item in source["training"]
        ]
    if not values or any(not is_sha256(value) for value in values):
        raise ValueError("training policy fingerprints must be lowercase SHA-256 values")
    return values  # type: ignore[return-value]


def validate_evidence_metadata(
    bundle: Mapping[str, Any],
    *,
    payload_kind: str | None = None,
    payload: Mapping[str, Any] | None = None,
) -> None:
    _text(bundle.get("disclaimer"), "disclaimer")
    cards = bundle.get("model_cards")
    if not isinstance(cards, list):
        raise ValueError("model_cards must be a list")
    ids, hashes = [], []
    for original in cards:
        card = _record(original, ModelCard, "model card")
        card["created_at"] = _date(card["created_at"], "model card created_at")
        for item in fields(ModelCard):
            if item.name not in {
                "created_at",
                "primary_metrics",
                "failure_modes",
                "independent_reviewer",
            }:
                _text(card[item.name], f"model card {item.name}")
        _text(card["independent_reviewer"], "independent_reviewer", optional=True)
        if (
            card["approval_status"] in ("APPROVED", "CONDITIONAL")
            and card["independent_reviewer"] is None
        ):
            raise ValueError(
                "approved/conditional model card requires a named independent reviewer"
            )
        card["failure_modes"] = _texts(card["failure_modes"], "failure_modes")
        metrics = card["primary_metrics"]
        if not isinstance(metrics, dict) or not metrics:
            raise ValueError("model card primary_metrics must be a nonempty object")
        for key, value in metrics.items():
            _text(key, "metric name")
            if not is_finite_metric(value):
                raise ValueError("model card metric values must be finite numbers")
        ModelCard(**card)
        ids.append(card["model_id"])
        hashes.append(card["content_hash"])
    if len(set(ids)) != len(ids):
        raise ValueError("model card identifiers must be unique within an artifact")
    gate = _record(bundle.get("gate_report"), GateDecisionForm, "gate report")
    for name in ("gate", "artifact_version", "decision"):
        _text(gate[name], f"gate {name}")
    for name in ("scientific_approval", "security_ops_approval", "legal_compliance_assessment"):
        _text(gate[name], name, optional=True)
    for name in ("scope_enabled", "scope_prohibited", "evidence_index", "open_findings"):
        gate[name] = _texts(gate[name], name)
    gate["decided_at"] = _date(gate["decided_at"], "gate decided_at")
    if gate["sunset_date"] is not None:
        gate["sunset_date"] = _date(gate["sunset_date"], "gate sunset_date")
        if gate["sunset_date"] < gate["decided_at"]:
            raise ValueError("gate sunset_date cannot precede its decision")
    GateDecisionForm(**gate)
    if bundle.get("runtime") is not None:
        runtime = bundle["runtime"]
        if not isinstance(runtime, dict) or set(runtime) != {
            "python",
            "platform",
            "dependencies",
            "source_sha256",
        }:
            raise ValueError("runtime requires exactly its provenance fields")
        for name in ("python", "platform"):
            _text(runtime[name], f"runtime {name}")
        if not is_sha256(runtime["source_sha256"]):
            raise ValueError("runtime source_sha256 must be lowercase SHA-256")
        if not isinstance(runtime["dependencies"], dict) or not runtime["dependencies"]:
            raise ValueError("runtime dependency versions must be a nonempty object")
        for name, version in runtime["dependencies"].items():
            _text(name, "dependency name")
            _text(version, "dependency version")
    elif "artifact_integrity" in bundle:
        raise ValueError("sealed evidence requires runtime provenance")
    manifest = bundle.get("run_manifest")
    if manifest is not None:
        manifest = _record(manifest, RunManifest, "run manifest")
        _text(manifest["run_id"], "run_id")
        _text(manifest["created_at"], "manifest created_at")
        try:
            created = datetime.fromisoformat(manifest["created_at"])
        except ValueError as exc:
            raise ValueError("manifest created_at requires an ISO timestamp") from exc
        if created.utcoffset() is None:
            raise ValueError("manifest created_at requires timezone information")
        if type(manifest["seed"]) is not int or manifest["seed"] < 0:
            raise ValueError("manifest seed must be a nonnegative integer")
        if not isinstance(manifest["config"], dict) or not is_sha256(manifest["result_hash"]):
            raise ValueError("manifest requires an object recipe and SHA-256 result hash")
    if payload_kind is not None and payload is not None:
        expected = _declared_hashes(payload_kind, payload)
        if Counter(hashes) != Counter(expected):
            raise ValueError(
                "model card fingerprints/count differ from the computational training metadata"
            )
