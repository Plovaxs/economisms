from __future__ import annotations

import pytest

from prometheus.evidence.replication_digest import (
    REAL_REPLICATIONS,
    ReplicationCoverageError,
    ReplicationRecord,
    verify_replications,
)


def test_every_record_names_a_real_subsystem_with_a_rerun_result_and_comparison() -> None:
    """EXP-14's own acceptance wording: "replication digest and
    comparison stored" -- checked directly against the real records."""
    assert len(REAL_REPLICATIONS) >= 3
    for record in REAL_REPLICATIONS:
        assert record.original_claim.strip()
        assert record.independent_rerun_result.strip()
        assert isinstance(record.matched, bool)


def test_no_record_claims_external_review() -> None:
    """The honest half of this item: EXP-14 asks for an external or
    reviewer replication, and this repository has neither -- every
    record says so explicitly rather than overclaiming."""
    for record in REAL_REPLICATIONS:
        assert record.reviewer_type == "internal_ai_assisted"


def test_verify_replications_passes_on_the_real_records() -> None:
    verify_replications()  # must not raise


def test_verify_replications_rejects_a_module_that_does_not_exist() -> None:
    bad = ReplicationRecord(
        subsystem="made-up",
        subsystem_module="prometheus.this_module_does_not_exist",
        original_claim="claim",
        independent_rerun_result="result",
        reviewer_type="internal_ai_assisted",
        matched=True,
    )
    with pytest.raises(ReplicationCoverageError, match="made-up"):
        verify_replications((bad,))


def test_a_record_requires_a_non_empty_original_claim() -> None:
    with pytest.raises(ValueError, match="original_claim"):
        ReplicationRecord(
            subsystem="x",
            subsystem_module="prometheus",
            original_claim="   ",
            independent_rerun_result="result",
            reviewer_type="internal_ai_assisted",
            matched=True,
        )
