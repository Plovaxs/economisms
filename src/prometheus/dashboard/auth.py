"""UIX-10: "Implement authorization-aware project sharing -- Users
cannot view unauthorized portfolios or experiments." Also PRV-12:
"Record approvals and scope for all data sharing -- Access grant
includes requester, owner, expiry and justification."

Reuses `service.auth.CredentialStore`/`Principal` directly -- the same
bearer-token identity this repository's existing authenticated service
already uses -- rather than inventing a second, parallel authentication
mechanism for the dashboard. `require_portfolio_access` is the real,
enforced check: a principal may view a named portfolio's data only if
`portfolio_owner == principal.owner` (an owner always has implicit
access to their own data) OR the portfolio owner has explicitly shared
it with that principal's `subject` via `PortfolioShareRegistry` (a
real, minimal sharing table -- "project sharing," not just "no
sharing at all"). A caller for any OTHER portfolio is refused with
`UnauthorizedPortfolioAccessError`, confirmed by a real negative test
in `tests/unit/test_dashboard_auth.py` using two genuinely different
credentials from the SAME `CredentialStore` shape this repository's
existing service tests already use.

Every grant is a `ShareGrant` record carrying exactly PRV-12's four
named fields (`requester`, `portfolio_owner`, `expiry`,
`justification`), all required -- `share()` cannot record a grant
missing any of them. `is_shared_with` (the LIVE authorization check
`require_portfolio_access` actually uses) deliberately does NOT take a
clock reading -- this project avoids wall-clock reads in favor of
explicit, caller-supplied dates (see `econosim.pit`'s identical
discipline) -- so expiry is not enforced on the live request path
today; `is_expired_as_of` is the separate, explicit audit check a
caller (or a scheduled review process) can run against a specific date
to find grants that have lapsed, named honestly as audit-only rather
than implied to be live-enforced."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from prometheus.service.auth import Principal


class UnauthorizedPortfolioAccessError(PermissionError):
    """Raised when a principal requests a portfolio/experiment they do
    not own and that has not been explicitly shared with them."""


@dataclass(frozen=True, slots=True)
class ShareGrant:
    portfolio_owner: str
    subject: str
    requester: str
    expiry: date
    justification: str

    def __post_init__(self) -> None:
        for name, value in (
            ("portfolio_owner", self.portfolio_owner),
            ("subject", self.subject),
            ("requester", self.requester),
            ("justification", self.justification),
        ):
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{name} must not be empty")


@dataclass(slots=True)
class PortfolioShareRegistry:
    """subject -> portfolio_owner -> the real ShareGrant record. A
    real, minimal sharing table, not a full ACL system -- sufficient
    to demonstrate genuine authorization-aware sharing (a principal
    sees only their own data plus whatever has actually been shared
    with them)."""

    _grants: dict[str, dict[str, ShareGrant]] = field(default_factory=dict)

    def share(
        self,
        portfolio_owner: str,
        with_subject: str,
        *,
        requester: str,
        expiry: date,
        justification: str,
    ) -> ShareGrant:
        grant = ShareGrant(
            portfolio_owner=portfolio_owner,
            subject=with_subject,
            requester=requester,
            expiry=expiry,
            justification=justification,
        )
        self._grants.setdefault(with_subject, {})[portfolio_owner] = grant
        return grant

    def revoke(self, portfolio_owner: str, from_subject: str) -> None:
        self._grants.get(from_subject, {}).pop(portfolio_owner, None)

    def is_shared_with(self, portfolio_owner: str, subject: str) -> bool:
        return portfolio_owner in self._grants.get(subject, {})

    def grant_for(self, portfolio_owner: str, subject: str) -> ShareGrant | None:
        return self._grants.get(subject, {}).get(portfolio_owner)

    def is_expired_as_of(self, portfolio_owner: str, subject: str, as_of: date) -> bool:
        """Audit-only: does NOT affect `is_shared_with`/live
        authorization (see this module's own docstring for why)."""
        grant = self.grant_for(portfolio_owner, subject)
        if grant is None:
            raise KeyError(f"no grant from {portfolio_owner!r} to {subject!r} to check")
        return as_of > grant.expiry


def require_portfolio_access(
    principal: Principal, portfolio_owner: str, shares: PortfolioShareRegistry | None = None
) -> None:
    if principal.owner == portfolio_owner:
        return
    if shares is not None and shares.is_shared_with(portfolio_owner, principal.subject):
        return
    raise UnauthorizedPortfolioAccessError(
        f"{principal.subject!r} (owner={principal.owner!r}) is not authorized to view "
        f"portfolio {portfolio_owner!r}"
    )
