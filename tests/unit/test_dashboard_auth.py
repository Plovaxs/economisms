from __future__ import annotations

import pytest

from prometheus.dashboard.auth import (
    PortfolioShareRegistry,
    UnauthorizedPortfolioAccessError,
    require_portfolio_access,
)
from prometheus.service.auth import Principal


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

    shares.share("alice", with_subject="bob-sub")
    require_portfolio_access(principal, "alice", shares)  # now allowed

    shares.revoke("alice", from_subject="bob-sub")
    with pytest.raises(UnauthorizedPortfolioAccessError):
        require_portfolio_access(principal, "alice", shares)


def test_a_share_for_a_different_subject_does_not_leak_access() -> None:
    bob = Principal(subject="bob-sub", owner="bob", scopes=frozenset({"read"}))
    shares = PortfolioShareRegistry()
    shares.share("alice", with_subject="someone-else-sub")
    with pytest.raises(UnauthorizedPortfolioAccessError):
        require_portfolio_access(bob, "alice", shares)
