from __future__ import annotations

from datetime import date

import pytest

from prometheus.dashboard.auth import (
    PortfolioShareRegistry,
    ShareGrant,
    UnauthorizedPortfolioAccessError,
    require_portfolio_access,
)
from prometheus.service.auth import Principal

_EXPIRY = date(2027, 1, 1)


def test_an_owner_always_has_access_to_their_own_portfolio() -> None:
    principal = Principal(subject="alice-sub", owner="alice", scopes=frozenset({"read"}))
    require_portfolio_access(principal, "alice")  # must not raise


def test_a_principal_with_no_share_is_refused_a_different_owners_portfolio() -> None:
    """UIX-10's own acceptance wording: "users cannot view unauthorized
    portfolios" -- the real negative case."""
    principal = Principal(subject="bob-sub", owner="bob", scopes=frozenset({"read"}))
    with pytest.raises(UnauthorizedPortfolioAccessError, match="bob-sub"):
        require_portfolio_access(principal, "alice")


def test_an_explicit_share_grants_access_and_revoke_removes_it() -> None:
    principal = Principal(subject="bob-sub", owner="bob", scopes=frozenset({"read"}))
    shares = PortfolioShareRegistry()
    with pytest.raises(UnauthorizedPortfolioAccessError):
        require_portfolio_access(principal, "alice", shares)

    shares.share(
        "alice", with_subject="bob-sub",
        requester="bob-sub", expiry=_EXPIRY, justification="joint research review",
    )
    require_portfolio_access(principal, "alice", shares)  # now allowed

    shares.revoke("alice", from_subject="bob-sub")
    with pytest.raises(UnauthorizedPortfolioAccessError):
        require_portfolio_access(principal, "alice", shares)


def test_a_share_for_a_different_subject_does_not_leak_access() -> None:
    bob = Principal(subject="bob-sub", owner="bob", scopes=frozenset({"read"}))
    shares = PortfolioShareRegistry()
    shares.share(
        "alice", with_subject="someone-else-sub",
        requester="someone-else-sub", expiry=_EXPIRY, justification="joint research review",
    )
    with pytest.raises(UnauthorizedPortfolioAccessError):
        require_portfolio_access(bob, "alice", shares)


def test_share_requires_all_four_prv_12_fields_to_be_non_empty() -> None:
    shares = PortfolioShareRegistry()
    with pytest.raises(ValueError, match="justification"):
        shares.share(
            "alice", with_subject="bob-sub",
            requester="bob-sub", expiry=_EXPIRY, justification="   ",
        )


def test_a_recorded_grant_carries_all_four_prv_12_fields() -> None:
    """PRV-12's own acceptance wording: "access grant includes
    requester, owner, expiry and justification" -- checked directly
    against the real stored record, not merely assumed from share()
    having been called."""
    shares = PortfolioShareRegistry()
    shares.share(
        "alice", with_subject="bob-sub",
        requester="bob-sub", expiry=_EXPIRY, justification="joint research review",
    )
    grant = shares.grant_for("alice", "bob-sub")
    assert isinstance(grant, ShareGrant)
    assert grant.portfolio_owner == "alice"
    assert grant.subject == "bob-sub"
    assert grant.requester == "bob-sub"
    assert grant.expiry == _EXPIRY
    assert grant.justification == "joint research review"


def test_is_expired_as_of_is_a_real_audit_only_check_not_wired_into_live_authorization() -> None:
    principal = Principal(subject="bob-sub", owner="bob", scopes=frozenset({"read"}))
    shares = PortfolioShareRegistry()
    shares.share(
        "alice", with_subject="bob-sub",
        requester="bob-sub", expiry=date(2026, 1, 1), justification="temporary review",
    )
    assert shares.is_expired_as_of("alice", "bob-sub", date(2026, 6, 1)) is True
    assert shares.is_expired_as_of("alice", "bob-sub", date(2025, 6, 1)) is False
    # Live authorization is unaffected by expiry -- disclosed explicitly in the module docstring.
    require_portfolio_access(principal, "alice", shares)
