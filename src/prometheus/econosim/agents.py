"""Household, firm, bank and government agents.

Each agent owns a handful of ledger accounts and exposes economically
meaningful operations (consume, originate_loan, repay_loan). Every operation
builds one balanced Transaction and posts it through the shared Ledger, so
every state change is journaled and checked against the per-sector
accounting identity before it is applied (see core.ledger).

Covers, with passing tests:
  ECO-02  household assets, debt, income and consumption (budget feasibility)
  ECO-03  firm deposits and equity (revenue recognition on sale)
  ECO-04  bank loans, deposits and equity (double-entry loan creation)
  ECO-06  government taxes, transfers and expenditures (sectoral flows
            reconcile to their counterpart accounts, by the same mechanism
            as loan origination below)
  ECO-09  loan demand, underwriting and bank capital limits (leverage cap);
            applies uniformly to household and government borrowing, since
            both go through Bank.originate_loan against the same capital
  LED-06  (partial) loan/bond repayment reduces receivable/payable and
            deposits; no write-off/recovery path yet

Bank.originate_loan / Bank.receive_repayment are written against a
structural Borrower protocol (agent_id, cash_account, loan_account), not
against Household specifically, so Government borrows and repays through
the exact same code path and the exact same capital/leverage constraint --
there is no separate, possibly-inconsistent "government debt" mechanism.

Not implemented here (do not infer otherwise from the names above): interest
accrual/amortization (LED-05), deposit-instrument reconciliation across the
whole household population (ECO-06, LED-08) -- household and firm deposit
balances are not yet bank-custodied for non-loan flows, so that check would
not currently be a true invariant of this model -- a central bank's own
ledger-backed balance sheet (see econosim.policy_rate.CentralBank, which is
a rate-process wrapper only, not a ledger agent), and labor/goods-market
clearing.
"""

from __future__ import annotations

from typing import Protocol

from prometheus.core.ledger import AccountType, Ledger, Posting, Sector, Side, Transaction
from prometheus.core.money import Money


class Borrower(Protocol):
    """Anything Bank.originate_loan / Bank.receive_repayment can lend to:
    an asset account to receive/repay cash and a liability account to
    record the debt. Household and Government both satisfy this
    structurally -- no inheritance relationship is required."""

    agent_id: str
    cash_account: str
    loan_account: str


class AgentError(Exception):
    """Base class for agent-level (as opposed to ledger-level) errors."""


class InsufficientFundsError(AgentError):
    def __init__(self, agent_id: str, requested: Money, available: Money) -> None:
        super().__init__(
            f"{agent_id} cannot pay {requested!r}: only {available!r} available"
        )
        self.agent_id = agent_id
        self.requested = requested
        self.available = available


class CreditLimitExceededError(AgentError):
    def __init__(
        self,
        bank_id: str,
        requested_exposure: Money,
        capital: Money,
        max_leverage: float,
    ) -> None:
        super().__init__(
            f"{bank_id} cannot extend {requested_exposure!r} in loans: "
            f"would exceed max_leverage={max_leverage} against capital {capital!r}"
        )
        self.bank_id = bank_id
        self.requested_exposure = requested_exposure
        self.capital = capital
        self.max_leverage = max_leverage


class Household:
    """Cash/deposit asset, a loan-payable liability and an equity (net
    worth) account that absorbs consumption spending and interest expense."""

    def __init__(self, ledger: Ledger, agent_id: str, currency: str = "USD") -> None:
        self.ledger = ledger
        self.agent_id = agent_id
        self.currency = currency
        self.cash_account = f"{agent_id}:deposit"
        self.loan_account = f"{agent_id}:loan_payable"
        self.equity_account = f"{agent_id}:equity"
        ledger.open_account(self.cash_account, Sector.HOUSEHOLD, AccountType.ASSET, currency)
        ledger.open_account(self.loan_account, Sector.HOUSEHOLD, AccountType.LIABILITY, currency)
        ledger.open_account(self.equity_account, Sector.HOUSEHOLD, AccountType.EQUITY, currency)

    @property
    def cash_balance(self) -> Money:
        return self.ledger.account(self.cash_account).balance

    @property
    def debt_balance(self) -> Money:
        return self.ledger.account(self.loan_account).balance

    @property
    def net_worth(self) -> Money:
        return self.ledger.account(self.equity_account).balance

    def receive_income(
        self, amount: Money, step: int = 0, description: str = "income"
    ) -> Transaction:
        """Credit an exogenous income flow (e.g. wages from a firm not yet
        modeled, or a government transfer) directly to equity and cash.
        A full wage/labor market belongs to a later PR; this exists so tests
        and demos can seed household wealth without bypassing the ledger."""
        if amount.is_negative() or amount.is_zero():
            raise ValueError("income amount must be positive")
        postings = [
            Posting(self.cash_account, Side.DEBIT, amount),
            Posting(self.equity_account, Side.CREDIT, amount),
        ]
        return self.ledger.post(postings, description=f"{description}: {self.agent_id}", step=step)

    def consume(self, firm: Firm, amount: Money, step: int = 0) -> Transaction:
        """Spend cash buying goods from a firm (ECO-02 budget feasibility:
        a household can never spend more cash than it holds)."""
        if amount.is_negative() or amount.is_zero():
            raise ValueError("consumption amount must be positive")
        if self.cash_balance < amount:
            raise InsufficientFundsError(self.agent_id, amount, self.cash_balance)
        postings = [
            Posting(self.cash_account, Side.CREDIT, amount),
            Posting(self.equity_account, Side.DEBIT, amount),
            Posting(firm.deposit_account, Side.DEBIT, amount),
            Posting(firm.equity_account, Side.CREDIT, amount),
        ]
        return self.ledger.post(
            postings, description=f"consumption {self.agent_id}->{firm.agent_id}", step=step
        )

    def repay_loan(self, bank: Bank, amount: Money, step: int = 0) -> Transaction:
        return bank.receive_repayment(self, amount, step=step)


class Firm:
    """Deposit asset and an equity account that accrues revenue from sales."""

    def __init__(self, ledger: Ledger, agent_id: str, currency: str = "USD") -> None:
        self.ledger = ledger
        self.agent_id = agent_id
        self.currency = currency
        self.deposit_account = f"{agent_id}:deposit"
        self.equity_account = f"{agent_id}:equity"
        ledger.open_account(self.deposit_account, Sector.FIRM, AccountType.ASSET, currency)
        ledger.open_account(self.equity_account, Sector.FIRM, AccountType.EQUITY, currency)

    @property
    def cash_balance(self) -> Money:
        return self.ledger.account(self.deposit_account).balance

    @property
    def net_worth(self) -> Money:
        return self.ledger.account(self.equity_account).balance

    def pay_wages(self, household: Household, amount: Money, step: int = 0) -> Transaction:
        """Pay a household for labor: firm equity falls (wage expense),
        household equity rises (wage income); cash moves firm -> household."""
        if amount.is_negative() or amount.is_zero():
            raise ValueError("wage amount must be positive")
        if self.cash_balance < amount:
            raise InsufficientFundsError(self.agent_id, amount, self.cash_balance)
        postings = [
            Posting(self.deposit_account, Side.CREDIT, amount),
            Posting(self.equity_account, Side.DEBIT, amount),
            Posting(household.cash_account, Side.DEBIT, amount),
            Posting(household.equity_account, Side.CREDIT, amount),
        ]
        return self.ledger.post(
            postings, description=f"wages {self.agent_id}->{household.agent_id}", step=step
        )


class Bank:
    """Loans-receivable and reserves assets; customer-deposits liability;
    an equity (bank capital) account. Credit creation is blocked once total
    loans would exceed capital * max_leverage (ECO-09)."""

    def __init__(
        self,
        ledger: Ledger,
        agent_id: str,
        currency: str = "USD",
        max_leverage: float = 10.0,
    ) -> None:
        if max_leverage <= 0:
            raise ValueError("max_leverage must be positive")
        self.ledger = ledger
        self.agent_id = agent_id
        self.currency = currency
        self.max_leverage = max_leverage
        self.loans_account = f"{agent_id}:loans_receivable"
        self.reserves_account = f"{agent_id}:reserves"
        self.deposits_account = f"{agent_id}:customer_deposits"
        self.equity_account = f"{agent_id}:equity"
        ledger.open_account(self.loans_account, Sector.BANK, AccountType.ASSET, currency)
        ledger.open_account(self.reserves_account, Sector.BANK, AccountType.ASSET, currency)
        ledger.open_account(self.deposits_account, Sector.BANK, AccountType.LIABILITY, currency)
        ledger.open_account(self.equity_account, Sector.BANK, AccountType.EQUITY, currency)

    @property
    def loans_outstanding(self) -> Money:
        return self.ledger.account(self.loans_account).balance

    @property
    def capital(self) -> Money:
        return self.ledger.account(self.equity_account).balance

    def capitalize(self, amount: Money, step: int = 0) -> Transaction:
        """Seed bank capital: reserves (asset) and equity both rise. This
        models an exogenous equity injection, e.g. at simulation start."""
        if amount.is_negative() or amount.is_zero():
            raise ValueError("capitalization amount must be positive")
        postings = [
            Posting(self.reserves_account, Side.DEBIT, amount),
            Posting(self.equity_account, Side.CREDIT, amount),
        ]
        return self.ledger.post(postings, description=f"capitalize {self.agent_id}", step=step)

    def originate_loan(self, borrower: Borrower, principal: Money, step: int = 0) -> Transaction:
        if principal.is_negative() or principal.is_zero():
            raise ValueError("loan principal must be positive")
        prospective_loans = self.loans_outstanding + principal
        # max_leverage may be non-integer; the comparison itself stays exact
        # integer minor-unit arithmetic on both sides (no ledger value is
        # ever a float -- only this capacity bound is derived from one).
        max_exposure_minor = int(self.capital.minor_units * self.max_leverage)
        if prospective_loans.minor_units > max_exposure_minor:
            raise CreditLimitExceededError(
                self.agent_id, prospective_loans, self.capital, self.max_leverage
            )
        postings = [
            Posting(self.loans_account, Side.DEBIT, principal),
            Posting(self.deposits_account, Side.CREDIT, principal),
            Posting(borrower.cash_account, Side.DEBIT, principal),
            Posting(borrower.loan_account, Side.CREDIT, principal),
        ]
        return self.ledger.post(
            postings,
            description=f"loan origination {self.agent_id}->{borrower.agent_id}",
            step=step,
        )

    def receive_repayment(self, borrower: Borrower, amount: Money, step: int = 0) -> Transaction:
        """Generalized loan/bond repayment: usable by any Borrower, so a
        Household repaying a loan and a Government repaying a bond go
        through the identical accounting (LED-06)."""
        if amount.is_negative() or amount.is_zero():
            raise ValueError("repayment amount must be positive")
        borrower_cash = self.ledger.account(borrower.cash_account).balance
        borrower_debt = self.ledger.account(borrower.loan_account).balance
        if borrower_cash < amount:
            raise InsufficientFundsError(borrower.agent_id, amount, borrower_cash)
        if borrower_debt < amount:
            raise ValueError(
                f"{borrower.agent_id} cannot repay {amount!r}: outstanding debt is only "
                f"{borrower_debt!r}"
            )
        postings = [
            Posting(borrower.cash_account, Side.CREDIT, amount),
            Posting(borrower.loan_account, Side.DEBIT, amount),
            Posting(self.loans_account, Side.CREDIT, amount),
            Posting(self.deposits_account, Side.DEBIT, amount),
        ]
        return self.ledger.post(
            postings,
            description=f"loan repayment {borrower.agent_id}->{self.agent_id}",
            step=step,
        )


class Government:
    """Treasury (cash) asset, bonds-payable liability and an equity
    (accumulated surplus/deficit) account (ECO-06). Borrows from and repays
    a Bank through the exact same Borrower-protocol methods a Household
    uses (Bank.originate_loan / Bank.receive_repayment) -- there is no
    separate government-debt mechanism to keep consistent with the
    household one."""

    def __init__(self, ledger: Ledger, agent_id: str, currency: str = "USD") -> None:
        self.ledger = ledger
        self.agent_id = agent_id
        self.currency = currency
        self.cash_account = f"{agent_id}:treasury"
        self.loan_account = f"{agent_id}:bonds_payable"
        self.equity_account = f"{agent_id}:equity"
        ledger.open_account(self.cash_account, Sector.GOVERNMENT, AccountType.ASSET, currency)
        ledger.open_account(self.loan_account, Sector.GOVERNMENT, AccountType.LIABILITY, currency)
        ledger.open_account(self.equity_account, Sector.GOVERNMENT, AccountType.EQUITY, currency)

    @property
    def cash_balance(self) -> Money:
        return self.ledger.account(self.cash_account).balance

    @property
    def debt_balance(self) -> Money:
        return self.ledger.account(self.loan_account).balance

    @property
    def net_worth(self) -> Money:
        return self.ledger.account(self.equity_account).balance

    def collect_tax(self, household: Household, amount: Money, step: int = 0) -> Transaction:
        """Household equity/cash fall; government cash/equity rise -- the
        same transfer pattern as Household.consume, just directed at the
        government sector instead of a firm."""
        if amount.is_negative() or amount.is_zero():
            raise ValueError("tax amount must be positive")
        if household.cash_balance < amount:
            raise InsufficientFundsError(household.agent_id, amount, household.cash_balance)
        postings = [
            Posting(household.cash_account, Side.CREDIT, amount),
            Posting(household.equity_account, Side.DEBIT, amount),
            Posting(self.cash_account, Side.DEBIT, amount),
            Posting(self.equity_account, Side.CREDIT, amount),
        ]
        return self.ledger.post(
            postings, description=f"tax {household.agent_id}->{self.agent_id}", step=step
        )

    def pay_transfer(self, household: Household, amount: Money, step: int = 0) -> Transaction:
        """The reverse of collect_tax: a transfer payment (e.g. an
        unemployment benefit) from government to household."""
        if amount.is_negative() or amount.is_zero():
            raise ValueError("transfer amount must be positive")
        if self.cash_balance < amount:
            raise InsufficientFundsError(self.agent_id, amount, self.cash_balance)
        postings = [
            Posting(self.cash_account, Side.CREDIT, amount),
            Posting(self.equity_account, Side.DEBIT, amount),
            Posting(household.cash_account, Side.DEBIT, amount),
            Posting(household.equity_account, Side.CREDIT, amount),
        ]
        return self.ledger.post(
            postings, description=f"transfer {self.agent_id}->{household.agent_id}", step=step
        )

    def issue_bonds(self, bank: Bank, principal: Money, step: int = 0) -> Transaction:
        """Borrow from `bank`, subject to the exact same capital/leverage
        constraint (ECO-09) that already governs household lending -- a
        bank capitalized to support household loans cannot be used to
        circumvent its own leverage cap by lending to the government
        instead."""
        return bank.originate_loan(self, principal, step=step)

    def repay_bond(self, bank: Bank, amount: Money, step: int = 0) -> Transaction:
        return bank.receive_repayment(self, amount, step=step)
