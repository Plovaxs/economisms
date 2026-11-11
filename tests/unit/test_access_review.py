from __future__ import annotations

from datetime import date

import pytest

from prometheus.evidence.access_review import (
    REPOSITORY_ACCESS_SNAPSHOT,
    AccessReviewSnapshot,
    CollaboratorAccess,
    LeastPrivilegeViolationError,
    verify_least_privilege,
)


def test_the_real_snapshot_has_exactly_one_admin_the_declared_owner() -> None:
    """SEC-03's own acceptance wording: "identity access review" --
    checked directly against the real, dated GitHub collaborator
    snapshot rather than asserted in prose."""
    admins = [c.login for c in REPOSITORY_ACCESS_SNAPSHOT.collaborators if c.admin]
    assert admins == [REPOSITORY_ACCESS_SNAPSHOT.owner_login]


def test_verify_least_privilege_passes_on_the_real_snapshot() -> None:
    verify_least_privilege()  # must not raise


def test_verify_least_privilege_rejects_an_undisclosed_admin() -> None:
    bad = AccessReviewSnapshot(
        reviewed_at=date(2026, 1, 1),
        repository="example/repo",
        owner_login="owner",
        collaborators=(
            CollaboratorAccess(login="owner", admin=True, push=True),
            CollaboratorAccess(login="someone-else", admin=True, push=True),
        ),
    )
    with pytest.raises(LeastPrivilegeViolationError, match="someone-else"):
        verify_least_privilege(bad)


def test_a_snapshot_requires_at_least_one_collaborator() -> None:
    with pytest.raises(ValueError, match="collaborators"):
        AccessReviewSnapshot(
            reviewed_at=date(2026, 1, 1),
            repository="example/repo",
            owner_login="owner",
            collaborators=(),
        )


def test_a_collaborator_requires_a_non_empty_login() -> None:
    with pytest.raises(ValueError, match="login"):
        CollaboratorAccess(login="   ", admin=True, push=True)
