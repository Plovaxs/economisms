"""Equity rollforward reconciliation (LED-04: "track equity and P&L
across all agent sectors; equity rollforward matches realized changes
and flows").

Every agent already carries a running equity balance (`Household.
net_worth`, `Firm.net_worth`, `Bank.capital`, `Government.net_worth`),
updated by `Account._apply` every time `Ledger.post` posts a
transaction touching it. `reconcile_equity_rollforward` recomputes that
SAME closing balance independently -- opening balance plus every
CREDIT (an increase to an equity/liability-type account) minus every
DEBIT (a decrease) posted to the account across a given sequence of
transactions -- and confirms it agrees with the account's own reported
closing balance. The two numbers come from genuinely separate code
paths (`Account._apply`'s running mutation during `Ledger.post`, versus
a fresh scan of `Transaction.postings` here), so agreement is a real
check, not a tautology.

Pure reconciliation, no ledger side effects (the same "caller composes
it" pattern `econosim.insolvency.allocate_recovery`, `econosim.liquidity`
and `econosim.trade_lifecycle` already use this session): the caller
decides what "a period" means by which transactions they pass in
(typically a slice of `Ledger.journal()`), and supplies the opening and
closing balances to check against (typically captured from
`Ledger.account(account_id).balance` at the period's boundaries).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from prometheus.core.ledger import Side, Transaction
from prometheus.core.money import Money


@dataclass(frozen=True, slots=True)
class EquityRollforward:
    account_id: str
    opening_equity: Money
    total_increases: Money
    total_decreases: Money
    closing_equity: Money
    recomputed_closing_equity: Money
    reconciles: bool


def reconcile_equity_rollforward(
    account_id: str,
    opening_equity: Money,
    transactions: Sequence[Transaction],
    closing_equity: Money,
) -> EquityRollforward:
    """Recomputes `opening_equity` + credits - debits to `account_id`
    across exactly `transactions`, and reports whether that matches the
    caller-supplied `closing_equity`."""
    currency = opening_equity.currency
    total_increase_minor = 0
    total_decrease_minor = 0
    for txn in transactions:
        for posting in txn.postings:
            if posting.account_id != account_id:
                continue
            if posting.amount.currency != currency:
                raise ValueError(
                    f"posting currency {posting.amount.currency!r} does not match "
                    f"opening_equity currency {currency!r}"
                )
            if posting.side == Side.CREDIT:
                total_increase_minor += posting.amount.minor_units
            else:
                total_decrease_minor += posting.amount.minor_units

    net_change = total_increase_minor - total_decrease_minor
    recomputed_closing = Money(opening_equity.minor_units + net_change, currency)
    return EquityRollforward(
        account_id=account_id,
        opening_equity=opening_equity,
        total_increases=Money(total_increase_minor, currency),
        total_decreases=Money(total_decrease_minor, currency),
        closing_equity=closing_equity,
        recomputed_closing_equity=recomputed_closing,
        reconciles=(recomputed_closing == closing_equity),
    )
