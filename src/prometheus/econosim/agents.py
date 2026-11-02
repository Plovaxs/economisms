"""Household, firm and bank agents.

Each agent owns a handful of ledger accounts and exposes economically
meaningful operations (consume, originate_loan, repay_loan). Every operation
builds one balanced Transaction and posts it through the shared Ledger, so
every state change is journaled and checked against the per-sector
accounting identity before it is applied (see core.ledger).

Covers, with passing tests:
  ECO-02  household assets, debt, income and consumption (budget feasibility)
  ECO-03  firm deposits and equity (revenue recognition on sale)
  ECO-04  bank loans, deposits and equity (double-entry loan creation)
  ECO-09  loan demand, underwriting and bank capital limits (leverage cap)
  LED-06  (partial) loan repayment reduces receivable/payable and deposits;
            no write-off/recovery path yet

Not implemented here (do not infer otherwise from the names above): interest
accrual/amortization (LED-05), deposit-instrument reconciliation across the
whole household population (ECO-06, LED-08) -- household and firm deposit
balances are not yet bank-custodied for non-loan flows, so that check would
not currently be a true invariant of this model -- default, labor markets,
goods-market clearing, government and central bank sectors.
"""

from __future__ import annotations

from prometheus.core.ledger import AccountType, Ledger, Posting, Sector, Side, Transaction
from prometheus.core.money import Money


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
        if amount.is_negative() or amount.is_zero():
            raise ValueError("repayment amount must be positive")
        if self.cash_balance < amount:
            raise InsufficientFundsError(self.agent_id, amount, self.cash_balance)
        if self.debt_balance < amount:
            raise ValueError(
                f"{self.agent_id} cannot repay {amount!r}: outstanding debt is only "
                f"{self.debt_balance!r}"
            )
        postings = [
            Posting(self.cash_account, Side.CREDIT, amount),
            Posting(self.loan_account, Side.DEBIT, amount),
            Posting(bank.loans_account, Side.CREDIT, amount),
            Posting(bank.deposits_account, Side.DEBIT, amount),
        ]
        return self.ledger.post(
            postings, description=f"loan repayment {self.agent_id}->{bank.agent_id}", step=step
        )


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

    def originate_loan(self, household: Household, principal: Money, step: int = 0) -> Transaction:
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
            Posting(household.cash_account, Side.DEBIT, principal),
            Posting(household.loan_account, Side.CREDIT, principal),
        ]
        return self.ledger.post(
            postings,
            description=f"loan origination {self.agent_id}->{household.agent_id}",
            step=step,
        )
