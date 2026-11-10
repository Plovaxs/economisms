"""GOV-03: "Assign accountable technical, scientific, security and
risk owners"; acceptance criterion: "RACI register with named owners
and deputies."

`RACI_REGISTER` names a REAL owner -- the project-maintainer role,
the same identity `evidence.license_inventory` (GOV-09) and
`evidence.risk_register.RiskException` (GOV-12) already name for
"approved by maintainer" -- for each of the four domains this item
names by name: technical, scientific, security and risk.

Each entry's `deputy` is explicitly `None`: this repository is
single-maintainer and has no second identity to honestly name as a
deputy, the same disclosed gap `CHECKLIST_STATUS.md` has already
recorded for this exact item (GOV-12/GOV-09's "Not covered" notes).
`verify_raci_register` is the real, checkable half of this item: every
one of the four required domains has a non-empty, named accountable
owner, confirmed by a passing test -- not merely a table nobody
checks. "Named owners AND deputies" is only PARTIALLY satisfied by
design; this module does not, and should not, invent a second person.
"""

from __future__ import annotations

from dataclasses import dataclass

_MAINTAINER = "project maintainer"

REQUIRED_DOMAINS: tuple[str, ...] = ("technical", "scientific", "security", "risk")


@dataclass(frozen=True, slots=True)
class RACIEntry:
    domain: str
    accountable_owner: str
    responsible: str
    consulted: tuple[str, ...]
    informed: tuple[str, ...]
    deputy: str | None

    def __post_init__(self) -> None:
        if self.domain not in REQUIRED_DOMAINS:
            raise ValueError(f"domain must be one of {REQUIRED_DOMAINS}")
        if not self.accountable_owner.strip():
            raise ValueError("accountable_owner must not be empty")
        if not self.responsible.strip():
            raise ValueError("responsible must not be empty")


RACI_REGISTER: tuple[RACIEntry, ...] = (
    RACIEntry(
        domain="technical",
        accountable_owner=_MAINTAINER,
        responsible=_MAINTAINER,
        consulted=(),
        informed=(),
        deputy=None,
    ),
    RACIEntry(
        domain="scientific",
        accountable_owner=_MAINTAINER,
        responsible=_MAINTAINER,
        consulted=(),
        informed=(),
        deputy=None,
    ),
    RACIEntry(
        domain="security",
        accountable_owner=_MAINTAINER,
        responsible=_MAINTAINER,
        consulted=(),
        informed=(),
        deputy=None,
    ),
    RACIEntry(
        domain="risk",
        accountable_owner=_MAINTAINER,
        responsible=_MAINTAINER,
        consulted=(),
        informed=(),
        deputy=None,
    ),
)


class RACICoverageError(ValueError):
    """Raised by `verify_raci_register` when a required domain has no
    entry, or an entry with no non-empty named accountable owner."""


def verify_raci_register(register: tuple[RACIEntry, ...] = RACI_REGISTER) -> None:
    covered = {e.domain for e in register if e.accountable_owner.strip()}
    missing = [d for d in REQUIRED_DOMAINS if d not in covered]
    if missing:
        raise RACICoverageError(f"missing a named accountable owner for: {missing}")
