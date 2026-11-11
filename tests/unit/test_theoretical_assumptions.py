from __future__ import annotations

import pytest

from prometheus.evidence.theoretical_assumptions import (
    THEORETICAL_ASSUMPTIONS,
    AssumptionCoverageError,
    AssumptionRecord,
    verify_theoretical_assumptions,
)


def test_every_record_documents_a_real_theoretical_assumption() -> None:
    """MGR-02's own acceptance wording, checked directly: every record
    names a real assumption and where it is documented."""
    assert len(THEORETICAL_ASSUMPTIONS) >= 3
    for record in THEORETICAL_ASSUMPTIONS:
        assert record.theoretical_assumption.strip()
        assert record.documented_in.strip()


def test_no_record_claims_external_review() -> None:
    """The honest half of this item: MGR-02 asks for an independent
    reviewer, and this repository has no external or independent human
    one -- every record says so explicitly."""
    for record in THEORETICAL_ASSUMPTIONS:
        assert record.reviewer_type == "internal_ai_assisted"


def test_the_reinforce_record_names_the_real_bug_pr_162_found() -> None:
    hedging_records = [
        r for r in THEORETICAL_ASSUMPTIONS if r.subsystem_module == "prometheus.hedging.rl_agent"
    ]
    assert len(hedging_records) == 1
    assert "rsample" in hedging_records[0].theoretical_assumption
    assert hedging_records[0].mathematical_logic_evaluated is True


def test_verify_theoretical_assumptions_passes_on_the_real_records() -> None:
    verify_theoretical_assumptions()  # must not raise


def test_verify_theoretical_assumptions_rejects_a_module_that_does_not_exist() -> None:
    bad = AssumptionRecord(
        subsystem="made-up",
        subsystem_module="prometheus.this_module_does_not_exist",
        theoretical_assumption="claim",
        documented_in="nowhere",
        mathematical_logic_evaluated=False,
        reviewer_type="internal_ai_assisted",
    )
    with pytest.raises(AssumptionCoverageError, match="made-up"):
        verify_theoretical_assumptions((bad,))


def test_a_record_requires_a_non_empty_assumption() -> None:
    with pytest.raises(ValueError, match="theoretical_assumption"):
        AssumptionRecord(
            subsystem="x",
            subsystem_module="prometheus",
            theoretical_assumption="   ",
            documented_in="somewhere",
            mathematical_logic_evaluated=False,
            reviewer_type="internal_ai_assisted",
        )
