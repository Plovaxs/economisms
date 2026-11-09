import pytest

from prometheus.evidence.cardinality_budget import (
    CardinalityBudget,
    compute_label_combinations,
    verify_cardinality_budget,
)
from prometheus.jobs.store import Job

_STATUSES = ("queued", "running", "succeeded", "failed", "cancelled", "timed_out")
_OWNERS = ("alice", "bob", "carol", "dave", "erin")


def _make_jobs(n: int) -> list[Job]:
    jobs = []
    for i in range(n):
        jobs.append(
            Job(
                job_id=f"job-{i:06d}",
                owner=_OWNERS[i % len(_OWNERS)],
                trace_id="t",
                kind="economy",
                config_json="{}",
                recipe_sha256="0" * 64,
                runtime_json="{}",
                estimate_json="{}",
                status=_STATUSES[i % len(_STATUSES)],
                created_ns=i,
                updated_ns=i,
                attempts=1,
                cancel_requested=False,
                timeout_seconds=60.0,
                artifact_sha256=None,
                result_hash=None,
                error_code=None,
                diagnostic_id=None,
                version=1,
            )
        )
    return jobs


def test_cardinality_budget_rejects_a_non_positive_max() -> None:
    with pytest.raises(ValueError, match="max_distinct_label_combinations"):
        CardinalityBudget(max_distinct_label_combinations=0)


def test_compute_label_combinations_rejects_empty_label_fields() -> None:
    with pytest.raises(ValueError, match="label_fields"):
        compute_label_combinations(_make_jobs(5), [])


def test_bounded_labels_give_the_exact_expected_combination_count() -> None:
    """6 statuses x 5 owners = at most 30 distinct combinations,
    exactly, with a real set of 50 jobs."""
    combos = compute_label_combinations(_make_jobs(50), ["status", "owner"])
    assert len(combos) == 30


def test_bounded_labels_stay_identical_at_a_much_higher_real_run_volume() -> None:
    """The acceptance criterion's own claim, checked directly: the
    SAME real label choice produces the SAME cardinality whether 50
    or 5,000 real jobs are simulated -- 'remains bounded during high
    run volume,' not merely asserted."""
    low_volume = compute_label_combinations(_make_jobs(50), ["status", "owner"])
    high_volume = compute_label_combinations(_make_jobs(5_000), ["status", "owner"])
    assert low_volume == high_volume
    assert len(high_volume) == 30


def test_an_unbounded_label_choice_genuinely_blows_the_budget_at_high_volume() -> None:
    """The discriminating negative case: labeling by job_id itself (an
    unbounded per-run identifier) is confirmed to grow linearly and
    exceed any fixed budget -- proving the check distinguishes a real
    bounded choice from a real unbounded one, not reporting 'fine'
    unconditionally."""
    unbounded = compute_label_combinations(_make_jobs(5_000), ["job_id"])
    assert len(unbounded) == 5_000

    budget = CardinalityBudget(max_distinct_label_combinations=100)
    report = verify_cardinality_budget(unbounded, budget)
    assert report.within_budget is False
    assert report.n_distinct_combinations == 5_000


def test_verify_cardinality_budget_reports_within_budget_for_the_bounded_choice() -> None:
    combos = compute_label_combinations(_make_jobs(5_000), ["status", "owner"])
    budget = CardinalityBudget(max_distinct_label_combinations=100)
    report = verify_cardinality_budget(combos, budget)
    assert report.within_budget is True
    assert report.n_distinct_combinations == 30
    assert report.budget == 100
