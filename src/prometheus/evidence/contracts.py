"""Strict artifact reader and computational contract checks, without execution."""

from __future__ import annotations

import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from prometheus.evidence.constants import SOURCE_TAG
from prometheus.evidence.integrity import verify_artifact_integrity
from prometheus.evidence.jsonio import strict_json_loads
from prometheus.evidence.validation import validate_evidence_metadata
from prometheus.experiments.manifest import compute_result_hash

CONVENTIONS = {
    "simulation": "trade-then-accrue-v1",
    "benchmark": "trade-then-accrue-v1",
    "study": "trade-then-accrue-v1",
    "economy": "atomic-market-settlement-v1",
    "monetary": "opening-rate-finance-v1",
    "monetary_study": "opening-rate-finance-v1",
    "rate_study": "opening-rate-finance-v1",
    "mixture_study": "opening-rate-finance-v1",
    "monetary_operations": "central-bank-ledger-stephooks-v1",
}


def read_evidence_bundle(path: Path, *, require_integrity: bool = False) -> dict[str, Any]:
    value = strict_json_loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("evidence bundle must be a JSON object")
    verify_artifact_integrity(value, require=require_integrity)
    return value


def verified_payload(
    bundle: Mapping[str, Any], *, require_integrity: bool = False
) -> tuple[str, dict[str, Any], str]:
    """Reject inconsistent inputs before allocating simulation or training work."""
    verify_artifact_integrity(bundle, require=require_integrity)
    if bundle.get("source_tag") != SOURCE_TAG:
        raise ValueError("unsupported evidence source_tag")
    keys = [name for name in CONVENTIONS if name in bundle]
    if len(keys) != 1:
        raise ValueError("bundle must contain exactly one supported computational payload")
    key = keys[0]
    payload = bundle[key]
    manifest = bundle.get("run_manifest")
    if not isinstance(payload, dict) or not isinstance(manifest, dict):
        raise ValueError("payload and run_manifest must be objects")
    if type(payload.get("schema_version")) is not int or payload["schema_version"] != 1:
        raise ValueError("unsupported evidence schema_version")
    if payload.get("accounting_convention") != CONVENTIONS[key]:
        raise ValueError("unsupported accounting_convention")
    if key == "economy" and payload.get("model_convention") != "budget-linear-schedules-v1":
        raise ValueError("unsupported economy model_convention")
    if (
        key == "monetary"
        and payload.get("model_convention") != "published-price-policy-feedback-v1"
    ):
        raise ValueError("unsupported monetary model_convention")
    if (
        key == "monetary_study"
        and payload.get("model_convention") != "crossed-published-feedback-study-v1"
    ):
        raise ValueError("unsupported monetary study model_convention")
    if key == "rate_study" and payload.get("model_convention") != "causal-rate-feature-ablation-v1":
        raise ValueError("unsupported rate study model_convention")
    if (
        key == "mixture_study"
        and payload.get("model_convention") != "empirical-macro-mixture-cvar-v1"
    ):
        raise ValueError("unsupported mixture study model_convention")
    if (
        key == "monetary_operations"
        and payload.get("model_convention") != "rate-driven-omo-discount-window-interbank-v1"
    ):
        raise ValueError("unsupported monetary operations model_convention")
    expected = manifest.get("result_hash")
    if not isinstance(expected, str) or re.fullmatch(r"[0-9a-f]{64}", expected) is None:
        raise ValueError("result_hash must be a lowercase SHA-256 hex digest")
    if compute_result_hash(payload) != expected:
        raise ValueError("evidence payload does not match its recorded result_hash")
    config = payload.get("config")
    if not isinstance(config, dict) or not isinstance(manifest.get("config"), dict):
        raise ValueError("payload and manifest configurations must be objects")
    if compute_result_hash(config) != compute_result_hash(manifest["config"]):
        raise ValueError("manifest configuration differs from the hashed configuration")
    if type(manifest.get("seed")) is not int or manifest["seed"] != config.get("seed"):
        raise ValueError("manifest seed differs from the hashed configuration")
    validate_evidence_metadata(bundle, payload_kind=key, payload=payload)
    return key, payload, expected
