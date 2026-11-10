from __future__ import annotations

import pytest

from prometheus.evidence.model_inventory import MODEL_INVENTORY, active_inventory
from prometheus.evidence.model_validation_report import (
    DEFAULT_VALIDATION_REPORT,
    ModelValidationRecord,
    ValidationCoverageError,
    verify_validation_report,
)


def test_a_record_requires_all_four_fields_non_empty() -> None:
    with pytest.raises(ValueError, match="calibration_evidence"):
        ModelValidationRecord(
            model_id="m",
            backtest_against_baseline="b",
            calibration_evidence="  ",
            operational_use_statement="o",
        )


def test_the_real_default_report_verifies_clean() -> None:
    """MGR-04's own acceptance wording -- "validation report covers
    calibration and operational use" -- checked as a real passing
    assertion, not merely a populated table nobody runs a check
    against."""
    verify_validation_report()  # must not raise


def test_every_active_inventory_model_has_a_validation_record() -> None:
    covered = {r.model_id for r in DEFAULT_VALIDATION_REPORT}
    for entry in active_inventory(MODEL_INVENTORY):
        assert entry.model_id in covered, f"{entry.model_id} has no validation record"


def test_every_record_states_the_real_research_only_operational_use() -> None:
    for record in DEFAULT_VALIDATION_REPORT:
        assert "research use only" in record.operational_use_statement.lower()
        assert "NO-GO" in record.operational_use_statement


def test_verify_raises_when_an_active_model_is_missing_from_the_report() -> None:
    incomplete_report = tuple(
        r for r in DEFAULT_VALIDATION_REPORT if r.model_id != "recessionnet"
    )
    with pytest.raises(ValidationCoverageError, match="recessionnet"):
        verify_validation_report(incomplete_report)
