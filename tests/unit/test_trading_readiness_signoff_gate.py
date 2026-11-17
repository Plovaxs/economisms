from __future__ import annotations

from datetime import UTC, datetime

import pytest

from prometheus.trading_readiness.signoff_gate import InsufficientSignoffError, arm


def test_five_distinct_names_arms_successfully() -> None:
    decision = arm(
        trading="Alice T.",
        risk="Bob R.",
        compliance="Carol C.",
        security="Dave S.",
        legal="Eve L.",
    )
    assert decision.trading == "Alice T."
    assert decision.roles == ("trading", "risk", "compliance", "security", "legal")


def test_a_missing_role_is_rejected_and_named() -> None:
    with pytest.raises(InsufficientSignoffError, match="legal"):
        arm(trading="Alice", risk="Bob", compliance="Carol", security="Dave", legal="")


def test_every_missing_role_is_named_at_once() -> None:
    with pytest.raises(InsufficientSignoffError) as excinfo:
        arm(trading="Alice", risk="", compliance="", security="Dave", legal="Eve")
    assert "risk" in str(excinfo.value)
    assert "compliance" in str(excinfo.value)


def test_two_roles_signed_off_by_the_same_name_is_rejected() -> None:
    with pytest.raises(InsufficientSignoffError, match="distinct"):
        arm(
            trading="Alice",
            risk="Alice",
            compliance="Carol",
            security="Dave",
            legal="Eve",
        )


def test_the_same_single_person_signing_off_everything_is_rejected() -> None:
    with pytest.raises(InsufficientSignoffError, match="distinct"):
        arm(
            trading="Alice",
            risk="Alice",
            compliance="Alice",
            security="Alice",
            legal="Alice",
        )


def test_an_explicit_timestamp_is_honored() -> None:
    when = datetime(2026, 1, 1, tzinfo=UTC)
    decision = arm(
        trading="Alice", risk="Bob", compliance="Carol", security="Dave", legal="Eve", at=when
    )
    assert decision.armed_at == when


def test_this_project_has_no_real_distinct_individuals_for_these_five_roles() -> None:
    """The actual, honest state of this solo research project: there is
    no real trading/risk/compliance/security/legal function staffed by
    5 distinct people, so this gate is not just theoretically
    constrained but PRACTICALLY un-armable with real names today -- a
    deliberate attempt using this project's only real identity
    (its maintainer) for every role fails exactly as it should."""
    with pytest.raises(InsufficientSignoffError, match="distinct"):
        arm(
            trading="PROMETHEUS maintainer",
            risk="PROMETHEUS maintainer",
            compliance="PROMETHEUS maintainer",
            security="PROMETHEUS maintainer",
            legal="PROMETHEUS maintainer",
        )
