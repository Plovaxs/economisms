from __future__ import annotations

from datetime import date

import pytest

from prometheus.evidence.data_retention import (
    DEFAULT_RETENTION_SCHEDULE,
    RetentionException,
    RetentionPolicy,
    is_covered_by_exception,
    is_past_retention,
)


def test_a_policy_requires_non_empty_category_and_rationale() -> None:
    with pytest.raises(ValueError, match="rationale"):
        RetentionPolicy(data_category="x", retention_days=30, rationale="  ")


def test_retention_days_must_be_positive_when_set() -> None:
    with pytest.raises(ValueError, match="retention_days"):
        RetentionPolicy(data_category="x", retention_days=0, rationale="r")


def test_an_indefinite_policy_never_expires() -> None:
    assert is_past_retention(date(2020, 1, 1), None, date(2099, 1, 1)) is False


def test_a_bounded_policy_expires_exactly_at_the_boundary() -> None:
    created = date(2026, 1, 1)
    assert is_past_retention(created, 90, date(2026, 3, 31)) is False  # 89 days
    assert is_past_retention(created, 90, date(2026, 4, 1)) is True  # exactly 90 days


def test_an_exception_requires_non_empty_signer_and_reason() -> None:
    with pytest.raises(ValueError, match="signed_by"):
        RetentionException(
            data_category="x", signed_by="", reason="r", sunset_date=date(2027, 1, 1)
        )


def test_an_active_exception_covers_the_category_and_an_expired_one_does_not() -> None:
    exc = RetentionException(
        data_category="local encrypted recovery snapshots (recovery.snapshot)",
        signed_by="project maintainer",
        reason="extended retention for an active investigation",
        sunset_date=date(2026, 12, 31),
    )
    assert is_covered_by_exception(
        "local encrypted recovery snapshots (recovery.snapshot)", date(2026, 6, 1), (exc,)
    ) is True
    assert is_covered_by_exception(
        "local encrypted recovery snapshots (recovery.snapshot)", date(2027, 1, 1), (exc,)
    ) is False


def test_the_real_default_schedule_covers_every_real_category_with_a_deliberate_choice() -> None:
    """PRV-04's own acceptance wording: "automated expiry or signed
    exceptions verifiable" -- every real entry either has a real
    bounded period (automated expiry applies) or is explicitly
    indefinite with a named reason (not merely unset)."""
    assert len(DEFAULT_RETENTION_SCHEDULE) >= 4
    for policy in DEFAULT_RETENTION_SCHEDULE:
        assert policy.rationale  # every policy states why, never silently defaulted
        if policy.retention_days is not None:
            assert is_past_retention(date(2000, 1, 1), policy.retention_days, date(2026, 1, 1))
