"""A ledger-backed central bank: reserve issuance, open market operations
and interbank settlement, built directly on `core.ledger` the same way
every other agent in `econosim.agents` is.

This is new relative to `econosim.policy_rate.CentralBank`, which remains a
pure rate-process wrapper with no balance sheet at all -- that class is
unchanged and still used wherever only the policy rate itself matters
(`Economy.add_central_bank`, `StepHooks` scenarios). `CentralBankLedger` is
a separate, optional agent for simulations that need the central bank's
*balance sheet*, not just its rate.

PR-041 unifies the two, without retiring either: `CentralBankLedger` can
optionally be constructed with a `rate_rule`/`initial_rate` (the exact
same `policy_rate.PolicyRateRule` the standalone wrapper uses -- the rate
math is reused, not reimplemented), giving ONE object that is both the
rate-setter and the ledger-backed balance sheet, via `step_rate(shocks)`.
A `CentralBankLedger` built WITHOUT a rate rule behaves exactly as before
PR-041 -- `step_rate` raises a clear error naming what is missing rather
than a confusing one from deep inside a None attribute, and every
existing caller that never touches `step_rate` is completely unaffected.
`econosim.monetary_operations` (PR-028) still constructs the two
SEPARATELY under different agent_ids; unifying that scenario's own
construction is left to a future PR, not done silently here.

Three reserve-issuance/settlement channels, each one balanced
Transaction, checked against the ledger's existing per-sector accounting
identity before any mutation (ECO-16), exactly like every agent in
`econosim.agents`:

  purchase_government_bonds / sell_government_bonds
      Open market operations (OMO): the central bank buys (sells) a bank's
      government-bond holdings in exchange for (in exchange against)
      reserves. The bank's `loans_account` is the same account
      `Bank.originate_loan` uses for every Borrower (Household and
      Government alike, see agents.py) -- this ledger does not track bond
      identity separately from ordinary loans within that account, so a
      purchase is only validated against the bank's *aggregate* loans
      balance, not against a specific bond instrument.

  lend_to_bank / repay_central_bank_loan
      Discount-window lending: a second, unsecured (from this ledger's
      perspective -- no security changes hands) reserve-issuance channel,
      matched by a central-bank receivable (`loans_to_banks`) rather than
      by securities.

  settle_interbank_transfer
      Moves reserves between two *different* banks' accounts at this
      central bank. This is the first transaction anywhere in this
      repository that posts against two distinct agent instances that
      share the same `Sector` (`Sector.BANK`) within one Transaction --
      `Ledger._check_sector_balance` checks balance per *sector*, not per
      agent instance, so this already works by construction; it is tested
      directly here rather than merely asserted.

      Important limitation, caught by writing this module's own tests, not
      just asserted here: this moves *only* the reserve-asset leg. It is
      NOT, by itself, balanced on either individual bank's own book --
      only at the whole-BANK-sector level that `Ledger.check_identities`
      actually checks. A real interbank settlement is paired with a
      matching customer-deposit movement (payer bank's deposit liability
      falls, payee bank's deposit liability rises) that keeps each bank
      individually balanced; this repository has no cross-bank customer
      deposit/transfer mechanism yet (every Household/Firm's deposit is
      only ever at the one Bank that created it), so that pairing leg does
      not exist to post. A caller that needs single-bank-level balance
      must post that matching leg itself in the same step; this method
      alone deliberately does not assume or fabricate one.

A bank's reserve balance at this central bank (`cb_settlement_balance`) is
a distinct instrument from `Bank.reserves_account` (that bank's own
self-capitalized vault reserves, used in its leverage calculation) -- the
two are never reconciled in this model. A central bank's own equity
account is opened for structural symmetry with every other agent but is
never posted to by any operation here: every issuance channel above is
exactly asset-for-liability, so central-bank equity stays at zero
throughout (no seigniorage/profit remittance to government is modeled).

A limitation surfaced (not introduced) by PR-041's unification work,
documented here rather than left for a future caller to discover by
accident: `register_bank`'s linked account names (`{bank_id}:cb_settlement_balance`,
`{bank_id}:cb_loans_payable`) are keyed only by the BANK's agent_id, not
by `(central_bank_id, bank_id)` -- so one `Bank` can be registered with
at most one `CentralBankLedger` in a given `Ledger`; registering it with
a second raises `core.ledger.DuplicateAccountError` from the second
`register_bank` call. A simulation with genuinely multiple independent
central banks sharing banks would need each bank's settlement accounts
namespaced by central bank too, which this module does not do.
"""

from __future__ import annotations

from dataclasses import dataclass

from prometheus.core.ledger import AccountType, Ledger, Posting, Sector, Side, Transaction
from prometheus.core.money import Money
from prometheus.econosim.agents import Bank, InsufficientFundsError
from prometheus.econosim.policy_rate import PolicyRateRule
from prometheus.econosim.shocks import Shock


class CentralBankLedgerError(Exception):
    """Base class for central-bank-ledger-level (as opposed to core-ledger-
    level) errors."""


class BankAlreadyRegisteredError(CentralBankLedgerError):
    def __init__(self, bank_id: str, central_bank_id: str) -> None:
        super().__init__(f"bank {bank_id!r} is already registered with {central_bank_id!r}")
        self.bank_id = bank_id
        self.central_bank_id = central_bank_id


class UnregisteredBankError(CentralBankLedgerError):
    def __init__(self, bank_id: str, central_bank_id: str) -> None:
        super().__init__(f"bank {bank_id!r} is not registered with {central_bank_id!r}")
        self.bank_id = bank_id
        self.central_bank_id = central_bank_id


class NoPolicyRateRuleError(CentralBankLedgerError):
    def __init__(self, central_bank_id: str) -> None:
        super().__init__(
            f"{central_bank_id!r} was constructed without a rate_rule/initial_rate; "
            "pass both to CentralBankLedger() to enable step_rate"
        )
        self.central_bank_id = central_bank_id


@dataclass(frozen=True, slots=True)
class BankReserveLink:
    """The three accounts created by `register_bank` for one bank: two on
    the bank's own book (sector BANK) and one on the central bank's
    (sector CENTRAL_BANK)."""

    bank_id: str
    settlement_account: str
    loans_payable_account: str
    reserve_liability_account: str


class CentralBankLedger:
    def __init__(
        self,
        ledger: Ledger,
        agent_id: str,
        currency: str = "USD",
        rate_rule: PolicyRateRule | None = None,
        initial_rate: float | None = None,
    ) -> None:
        if (rate_rule is None) != (initial_rate is None):
            raise ValueError("rate_rule and initial_rate must be given together or not at all")
        self.ledger = ledger
        self.agent_id = agent_id
        self.currency = currency
        self.rate_rule = rate_rule
        self.current_rate = initial_rate
        self.securities_holdings_account = f"{agent_id}:securities_holdings"
        self.loans_to_banks_account = f"{agent_id}:loans_to_banks"
        self.equity_account = f"{agent_id}:equity"
        ledger.open_account(
            self.securities_holdings_account, Sector.CENTRAL_BANK, AccountType.ASSET, currency
        )
        ledger.open_account(
            self.loans_to_banks_account, Sector.CENTRAL_BANK, AccountType.ASSET, currency
        )
        ledger.open_account(self.equity_account, Sector.CENTRAL_BANK, AccountType.EQUITY, currency)
        self._links: dict[str, BankReserveLink] = {}

    @property
    def tracks_policy_rate(self) -> bool:
        return self.rate_rule is not None

    def step_rate(self, shocks: list[Shock]) -> float:
        """Advance the policy rate by one macro step, via the exact same
        `PolicyRateRule.step` the standalone `policy_rate.CentralBank`
        wrapper calls -- the rate math lives in one place regardless of
        which object holds the current rate."""
        if self.rate_rule is None or self.current_rate is None:
            raise NoPolicyRateRuleError(self.agent_id)
        self.current_rate = self.rate_rule.step(self.current_rate, shocks)
        return self.current_rate

    @property
    def securities_holdings(self) -> Money:
        return self.ledger.account(self.securities_holdings_account).balance

    @property
    def loans_to_banks_outstanding(self) -> Money:
        return self.ledger.account(self.loans_to_banks_account).balance

    def register_bank(self, bank: Bank) -> BankReserveLink:
        """Open the linked settlement/liability accounts for `bank`. Like
        every other agent's `__init__`, this only opens accounts at a zero
        balance -- it posts no Transaction, since there is nothing yet to
        balance."""
        if bank.agent_id in self._links:
            raise BankAlreadyRegisteredError(bank.agent_id, self.agent_id)
        settlement_account = f"{bank.agent_id}:cb_settlement_balance"
        loans_payable_account = f"{bank.agent_id}:cb_loans_payable"
        reserve_liability_account = f"{self.agent_id}:reserve_liability:{bank.agent_id}"
        self.ledger.open_account(settlement_account, Sector.BANK, AccountType.ASSET, self.currency)
        self.ledger.open_account(
            loans_payable_account, Sector.BANK, AccountType.LIABILITY, self.currency
        )
        self.ledger.open_account(
            reserve_liability_account, Sector.CENTRAL_BANK, AccountType.LIABILITY, self.currency
        )
        link = BankReserveLink(
            bank_id=bank.agent_id,
            settlement_account=settlement_account,
            loans_payable_account=loans_payable_account,
            reserve_liability_account=reserve_liability_account,
        )
        self._links[bank.agent_id] = link
        return link

    def _link_for(self, bank: Bank) -> BankReserveLink:
        try:
            return self._links[bank.agent_id]
        except KeyError:
            raise UnregisteredBankError(bank.agent_id, self.agent_id) from None

    def settlement_balance_of(self, bank: Bank) -> Money:
        return self.ledger.account(self._link_for(bank).settlement_account).balance

    def reserve_liability_to(self, bank: Bank) -> Money:
        return self.ledger.account(self._link_for(bank).reserve_liability_account).balance

    def loan_payable_of(self, bank: Bank) -> Money:
        return self.ledger.account(self._link_for(bank).loans_payable_account).balance

    def purchase_government_bonds(self, bank: Bank, amount: Money, step: int = 0) -> Transaction:
        """Expansionary OMO: buy `amount` of `bank`'s loans-receivable
        balance in exchange for reserves credited to its settlement
        account."""
        if not amount.is_positive():
            raise ValueError("purchase amount must be positive")
        link = self._link_for(bank)
        if bank.loans_outstanding < amount:
            raise ValueError(
                f"{bank.agent_id} holds only {bank.loans_outstanding!r}, cannot sell {amount!r} "
                "in government bonds"
            )
        postings = [
            Posting(bank.loans_account, Side.CREDIT, amount),
            Posting(link.settlement_account, Side.DEBIT, amount),
            Posting(self.securities_holdings_account, Side.DEBIT, amount),
            Posting(link.reserve_liability_account, Side.CREDIT, amount),
        ]
        return self.ledger.post(
            postings, description=f"OMO purchase {self.agent_id}<-{bank.agent_id}", step=step
        )

    def sell_government_bonds(self, bank: Bank, amount: Money, step: int = 0) -> Transaction:
        """Contractionary OMO: the exact reverse of `purchase_government_bonds`."""
        if not amount.is_positive():
            raise ValueError("sale amount must be positive")
        link = self._link_for(bank)
        if self.securities_holdings < amount:
            raise ValueError(
                f"{self.agent_id} holds only {self.securities_holdings!r}, cannot sell {amount!r}"
            )
        bank_balance = self.settlement_balance_of(bank)
        if bank_balance < amount:
            raise InsufficientFundsError(bank.agent_id, amount, bank_balance)
        postings = [
            Posting(self.securities_holdings_account, Side.CREDIT, amount),
            Posting(link.reserve_liability_account, Side.DEBIT, amount),
            Posting(bank.loans_account, Side.DEBIT, amount),
            Posting(link.settlement_account, Side.CREDIT, amount),
        ]
        return self.ledger.post(
            postings, description=f"OMO sale {self.agent_id}->{bank.agent_id}", step=step
        )

    def lend_to_bank(self, bank: Bank, amount: Money, step: int = 0) -> Transaction:
        """Discount-window lending: a reserve-issuance channel matched by a
        central-bank receivable rather than by securities."""
        if not amount.is_positive():
            raise ValueError("loan amount must be positive")
        link = self._link_for(bank)
        postings = [
            Posting(self.loans_to_banks_account, Side.DEBIT, amount),
            Posting(link.reserve_liability_account, Side.CREDIT, amount),
            Posting(link.settlement_account, Side.DEBIT, amount),
            Posting(link.loans_payable_account, Side.CREDIT, amount),
        ]
        return self.ledger.post(
            postings, description=f"discount window {self.agent_id}->{bank.agent_id}", step=step
        )

    def repay_central_bank_loan(self, bank: Bank, amount: Money, step: int = 0) -> Transaction:
        """The exact reverse of `lend_to_bank`."""
        if not amount.is_positive():
            raise ValueError("repayment amount must be positive")
        link = self._link_for(bank)
        outstanding = self.loan_payable_of(bank)
        if outstanding < amount:
            raise ValueError(
                f"{bank.agent_id} owes only {outstanding!r} to {self.agent_id}, "
                f"cannot repay {amount!r}"
            )
        bank_balance = self.settlement_balance_of(bank)
        if bank_balance < amount:
            raise InsufficientFundsError(bank.agent_id, amount, bank_balance)
        postings = [
            Posting(link.loans_payable_account, Side.DEBIT, amount),
            Posting(link.settlement_account, Side.CREDIT, amount),
            Posting(self.loans_to_banks_account, Side.CREDIT, amount),
            Posting(link.reserve_liability_account, Side.DEBIT, amount),
        ]
        return self.ledger.post(
            postings,
            description=f"discount window repayment {bank.agent_id}->{self.agent_id}",
            step=step,
        )

    def settle_interbank_transfer(
        self, payer_bank: Bank, payee_bank: Bank, amount: Money, step: int = 0
    ) -> Transaction:
        """Move `amount` of reserves from `payer_bank`'s to `payee_bank`'s
        account at this central bank -- a pure reallocation of an existing
        liability between two sub-accounts, not new issuance: the central
        bank's total reserve liability is unchanged by this call, only
        tested directly, not just asserted in the module docstring."""
        if payer_bank.agent_id == payee_bank.agent_id:
            raise ValueError("cannot settle a transfer to the same bank")
        if not amount.is_positive():
            raise ValueError("transfer amount must be positive")
        payer_link = self._link_for(payer_bank)
        payee_link = self._link_for(payee_bank)
        payer_balance = self.settlement_balance_of(payer_bank)
        if payer_balance < amount:
            raise InsufficientFundsError(payer_bank.agent_id, amount, payer_balance)
        postings = [
            Posting(payer_link.settlement_account, Side.CREDIT, amount),
            Posting(payer_link.reserve_liability_account, Side.DEBIT, amount),
            Posting(payee_link.reserve_liability_account, Side.CREDIT, amount),
            Posting(payee_link.settlement_account, Side.DEBIT, amount),
        ]
        return self.ledger.post(
            postings,
            description=(
                f"interbank settlement {payer_bank.agent_id}->{payee_bank.agent_id} "
                f"via {self.agent_id}"
            ),
            step=step,
        )
