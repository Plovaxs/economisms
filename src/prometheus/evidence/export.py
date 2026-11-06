"""A one-command evidence bundle export (AUD-11, AUD-08).

AUD-08: "Publish simulation versus empirical disclaimer in exports --
Machine-readable source tag and visible watermark included." Every bundle
built here carries both a human-readable disclaimer string and a
machine-readable `source_tag`, unconditionally -- there is no code path
through build_evidence_bundle that omits them.
"""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import asdict
from pathlib import Path
from typing import Any

from prometheus.evidence.constants import SIMULATION_DISCLAIMER as SIMULATION_DISCLAIMER
from prometheus.evidence.constants import SOURCE_TAG as SOURCE_TAG
from prometheus.evidence.gate_report import GateDecisionForm
from prometheus.evidence.integrity import seal_evidence_bundle
from prometheus.evidence.model_card import ModelCard
from prometheus.experiments.manifest import RunManifest, json_default, runtime_provenance


def build_evidence_bundle(
    run_manifest: RunManifest | None,
    model_cards: list[ModelCard],
    gate_report: GateDecisionForm,
) -> dict[str, Any]:
    return {
        "disclaimer": SIMULATION_DISCLAIMER,
        "source_tag": SOURCE_TAG,
        "run_manifest": run_manifest.to_dict() if run_manifest is not None else None,
        "model_cards": [asdict(card) for card in model_cards],
        "gate_report": asdict(gate_report),
        "runtime": runtime_provenance(),
    }


def export_evidence_bundle(bundle: dict[str, Any], path: Path) -> Path:
    # Serialize before touching the destination, then atomically replace it.
    sealed = seal_evidence_bundle(bundle)
    if sealed.get("source_tag") == SOURCE_TAG:
        from prometheus.evidence.contracts import CONVENTIONS, verified_payload
        from prometheus.evidence.validation import validate_evidence_metadata

        if any(key in sealed for key in CONVENTIONS):
            verified_payload(sealed)
        else:
            validate_evidence_metadata(sealed)
    content = json.dumps(sealed, indent=2, sort_keys=True, default=json_default, allow_nan=False)
    temporary: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=path.parent, delete=False
        ) as stream:
            temporary = stream.name
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        Path(temporary).replace(path)
    finally:
        if temporary is not None:
            Path(temporary).unlink(missing_ok=True)
    return path
