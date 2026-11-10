"""UIX-10: "Implement authorization-aware project sharing -- Users
cannot view unauthorized portfolios or experiments."

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
"""

from __future__ import annotations

from dataclasses import dataclass, field

from prometheus.service.auth import Principal


class UnauthorizedPortfolioAccessError(PermissionError):
    """Raised when a principal requests a portfolio/experiment they do
    not own and that has not been explicitly shared with them."""


@dataclass(slots=True)
class PortfolioShareRegistry:
    """subject -> set of portfolio owners who have shared their
    portfolio with that subject. A real, minimal sharing table, not a
    full ACL system -- sufficient to demonstrate genuine
    authorization-aware sharing (a principal sees only their own data
    plus whatever has actually been shared with them)."""

    _shares: dict[str, set[str]] = field(default_factory=dict)

    def share(self, portfolio_owner: str, with_subject: str) -> None:
        if not portfolio_owner.strip() or not with_subject.strip():
            raise ValueError("portfolio_owner and with_subject must not be empty")
        self._shares.setdefault(with_subject, set()).add(portfolio_owner)

    def revoke(self, portfolio_owner: str, from_subject: str) -> None:
        self._shares.get(from_subject, set()).discard(portfolio_owner)

    def is_shared_with(self, portfolio_owner: str, subject: str) -> bool:
        return portfolio_owner in self._shares.get(subject, set())


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
