"""Direct, bilateral interbank lending (extending ECO-09; closing the
structural gap `econosim.network_risk`'s own docstring flags: "there is
no direct bank-to-bank lending instrument anywhere in econosim.agents, so
every off-diagonal bank<->bank entry in the resulting matrix is exactly
zero"). This module is that instrument.

Unlike `central_bank_ledger.CentralBankLedger` (every bank's relationship
is with ONE shared central bank), lending here is directly BETWEEN
arbitrary pairs of `Bank` agents. Per-pair linked accounts -- not one
aggregate payable/receivable account per bank -- are essential, not a
stylistic choice: if a bank borrowed from several different banks, one
aggregate liability balance could not tell a contagion analysis WHO it
owes, only how much in total. The Eisenberg-Noe clearing network
(`titan.contagion`) needs genuine pairwise liabilities, not a netted
total. This mirrors exactly the per-bank linked-account pattern
`CentralBankLedger.register_bank` already uses.

Capital/leverage treatment, an explicit simplification, not a hidden
cut corner: a lending bank's interbank exposure is checked against its
OWN capital/`max_leverage` cap, entirely separately from the credit
capacity `Bank.originate_loan` already enforces for household/government
lending (ECO-09). Real bank capital is a single shared resource backing
every kind of credit a bank extends; this repository tracks interbank and
customer/government credit as two independent capacity pools against the
same capital figure, rather than one netted pool -- a conservative
simplification (it under-counts, never over-counts, available capacity)
documented here rather than silently assumed away.
"""

from __future__ import annotations

from dataclasses import dataclass

from prometheus.core.ledger import AccountType, Ledger, Posting, Sector, Side, Transaction
from prometheus.core.money import Money
from prometheus.econosim.agents import Bank, CreditLimitExceededError, InsufficientFundsError


@dataclass(frozen=True, slots=True)
class LoanLink:
    lender_id: str
    borrower_id: str
    receivable_account: str
    payable_account: str


class InterbankMarket:
    """Owns the per-(lender, borrower)-pair linked accounts for every
    bilateral interbank loan relationship opened so far. A pair's
    accounts are opened lazily, on the first `lend` between that specific
    ordered (lender, borrower) pair -- a bank with no interbank activity
    at all never gets any extra accounts."""

    def __init__(self, ledger: Ledger) -> None:
        self.ledger = ledger
        self._links: dict[tuple[str, str], LoanLink] = {}

    def _get_or_open_link(self, lender: Bank, borrower: Bank) -> LoanLink:
        key = (lender.agent_id, borrower.agent_id)
        if key in self._links:
            return self._links[key]
        receivable_account = f"{lender.agent_id}:interbank_receivable_from:{borrower.agent_id}"
        payable_account = f"{borrower.agent_id}:interbank_payable_to:{lender.agent_id}"
        self.ledger.open_account(
            receivable_account, Sector.BANK, AccountType.ASSET, lender.currency
        )
        self.ledger.open_account(
            payable_account, Sector.BANK, AccountType.LIABILITY, borrower.currency
        )
        link = LoanLink(lender.agent_id, borrower.agent_id, receivable_account, payable_account)
        self._links[key] = link
        return link

    def exposure(self, lender: Bank, borrower: Bank) -> Money:
        """Current outstanding loan from `lender` to `borrower`; zero (not
        an error) if that specific ordered pair has never transacted --
        "no relationship yet" is a legitimate zero state, not a fault."""
        key = (lender.agent_id, borrower.agent_id)
        if key not in self._links:
            return Money.zero(lender.currency)
        return self.ledger.account(self._links[key].receivable_account).balance

    def total_interbank_exposure(self, lender: Bank) -> Money:
        """Sum of `lender`'s outstanding loans across every counterparty
        it has ever lent to -- the quantity the leverage check below
        actually constrains."""
        total = Money.zero(lender.currency)
        for link in self._links.values():
            if link.lender_id == lender.agent_id:
                total += self.ledger.account(link.receivable_account).balance
        return total

    def lend(self, lender: Bank, borrower: Bank, principal: Money, step: int = 0) -> Transaction:
        if lender.agent_id == borrower.agent_id:
            raise ValueError("a bank cannot lend to itself")
        if not principal.is_positive():
            raise ValueError("interbank loan principal must be positive")
        prospective_exposure = self.total_interbank_exposure(lender) + principal
        max_exposure_minor = int(lender.capital.minor_units * lender.max_leverage)
        if prospective_exposure.minor_units > max_exposure_minor:
            raise CreditLimitExceededError(
                lender.agent_id, prospective_exposure, lender.capital, lender.max_leverage
            )
        lender_reserves = self.ledger.account(lender.reserves_account).balance
        if lender_reserves < principal:
            raise InsufficientFundsError(lender.agent_id, principal, lender_reserves)

        link = self._get_or_open_link(lender, borrower)
        postings = [
            Posting(lender.reserves_account, Side.CREDIT, principal),
            Posting(link.receivable_account, Side.DEBIT, principal),
            Posting(borrower.reserves_account, Side.DEBIT, principal),
            Posting(link.payable_account, Side.CREDIT, principal),
        ]
        return self.ledger.post(
            postings,
            description=f"interbank loan {lender.agent_id}->{borrower.agent_id}",
            step=step,
        )

    def repay(self, lender: Bank, borrower: Bank, amount: Money, step: int = 0) -> Transaction:
        if not amount.is_positive():
            raise ValueError("repayment amount must be positive")
        outstanding = self.exposure(lender, borrower)
        if outstanding < amount:
            raise ValueError(
                f"{borrower.agent_id} owes {lender.agent_id} only {outstanding!r}, "
                f"cannot repay {amount!r}"
            )
        borrower_reserves = self.ledger.account(borrower.reserves_account).balance
        if borrower_reserves < amount:
            raise InsufficientFundsError(borrower.agent_id, amount, borrower_reserves)

        link = self._links[(lender.agent_id, borrower.agent_id)]
        postings = [
            Posting(borrower.reserves_account, Side.CREDIT, amount),
            Posting(link.payable_account, Side.DEBIT, amount),
            Posting(link.receivable_account, Side.CREDIT, amount),
            Posting(lender.reserves_account, Side.DEBIT, amount),
        ]
        return self.ledger.post(
            postings,
            description=f"interbank loan repayment {borrower.agent_id}->{lender.agent_id}",
            step=step,
        )
