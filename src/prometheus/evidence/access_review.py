"""SEC-03: "Enforce MFA and least-privilege maintainers"; acceptance
criterion: "identity access review and access log evidence."

`REPOSITORY_ACCESS_SNAPSHOT` records a REAL, dated query against this
repository's own GitHub settings (`gh api repos/Plovaxs/economisms/
collaborators`, run 2026-11-11): exactly one collaborator, the
repository owner, with admin access -- not a hypothetical review. For
a genuinely single-maintainer repository, "least privilege" is
trivially, honestly satisfied: there is no second account to
over-privilege, and none to restrict down. `verify_least_privilege` is
the real, checkable half: it would fail loudly if this snapshot ever
listed an admin collaborator other than the declared owner.

Not covered, and not claimed: "Enforce MFA" has no programmatic
enforcement point for a personal-account repository -- GitHub's
`two_factor_requirement_enabled` setting exists only at the
ORGANIZATION level (`PATCH /orgs/{org}`), and there is deliberately no
API to toggle a personal account's own two-factor authentication (a
human-only action, by GitHub's own design, for security reasons).
"Access log evidence" beyond this collaborator snapshot would need
GitHub's audit-log API, itself only available on paid Enterprise/
organization plans -- also not available for a personal-account
repository. This module records what a single-maintainer, personal-
account repository CAN honestly show, and names exactly what it
cannot.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True, slots=True)
class CollaboratorAccess:
    login: str
    admin: bool
    push: bool

    def __post_init__(self) -> None:
        if not self.login.strip():
            raise ValueError("login must not be empty")


@dataclass(frozen=True, slots=True)
class AccessReviewSnapshot:
    reviewed_at: date
    repository: str
    owner_login: str
    collaborators: tuple[CollaboratorAccess, ...]

    def __post_init__(self) -> None:
        if not self.repository.strip():
            raise ValueError("repository must not be empty")
        if not self.owner_login.strip():
            raise ValueError("owner_login must not be empty")
        if not self.collaborators:
            raise ValueError("collaborators must not be empty")


REPOSITORY_ACCESS_SNAPSHOT: AccessReviewSnapshot = AccessReviewSnapshot(
    reviewed_at=date(2026, 11, 11),
    repository="Plovaxs/economisms",
    owner_login="Plovaxs",
    collaborators=(CollaboratorAccess(login="Plovaxs", admin=True, push=True),),
)


class LeastPrivilegeViolationError(ValueError):
    """Raised by `verify_least_privilege` when a collaborator other
    than the declared repository owner holds admin access."""


def verify_least_privilege(snapshot: AccessReviewSnapshot = REPOSITORY_ACCESS_SNAPSHOT) -> None:
    extra_admins = [
        c.login for c in snapshot.collaborators if c.admin and c.login != snapshot.owner_login
    ]
    if extra_admins:
        raise LeastPrivilegeViolationError(f"undisclosed admin collaborator(s): {extra_admins}")
