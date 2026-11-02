"""A multi-sector, double-entry ledger with fail-closed accounting invariants.

Implements (a growing, tested subset of):
  LED-01  every transaction is a set of balanced journal entries
  LED-02  deterministic integer minor units (see core.money.Money)
  LED-12  global resource/currency conservation under any transaction sequence
  ECO-01  typed economic state / immutable prior snapshots (see EconomicState)
  ECO-16  shutdown behavior on a broken accounting identity (fail closed)
  VAL-07  economic conservation under randomized transitions (see tests/property)

Design note on cross-sector instruments (loans, deposits): a single financial
instrument such as "household deposit at a bank" is represented as TWO linked
accounts -- an asset account on the holder's book and a liability account on
the issuer's book -- rather than one shared object, because a single account
can only have one normal balance side. Every operation that creates such an
instrument (see econosim.agents) posts both sides in one Transaction. The
ledger enforces, as a precondition checked before any mutation, that every
individual SECTOR's postings within a transaction are themselves balanced
(sum of debits == sum of credits for that sector). This is strictly stronger
than requiring only the whole transaction to balance, and it is exactly the
per-sector balance-sheet identity (Assets = Liabilities + Equity) required by
section 3.2 of the specification: it catches a missing counterpart posting
(e.g. crediting a bank's liability without debiting the matching household
asset) before it ever reaches account balances.
"""

from __future__ import annotations

import hashlib
from collections import defaultdict
from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum

from prometheus.core.money import CurrencyMismatchError, Money


class Sector(StrEnum):
    HOUSEHOLD = "household"
    FIRM = "firm"
    BANK = "bank"
    GOVERNMENT = "government"
    CENTRAL_BANK = "central_bank"


class AccountType(StrEnum):
    ASSET = "asset"
    LIABILITY = "liability"
    EQUITY = "equity"


class Side(StrEnum):
    DEBIT = "debit"
    CREDIT = "credit"


class LedgerError(Exception):
    """Base class for all ledger errors."""


class DuplicateAccountError(LedgerError):
    def __init__(self, account_id: str) -> None:
        super().__init__(f"account already exists: {account_id!r}")
        self.account_id = account_id


class UnknownAccountError(LedgerError):
    def __init__(self, account_id: str) -> None:
        super().__init__(f"unknown account: {account_id!r}")
        self.account_id = account_id


class EmptyTransactionError(LedgerError):
    def __init__(self) -> None:
        super().__init__("a transaction must contain at least one posting")


class LedgerImbalanceError(LedgerError):
    """Raised when a transaction's total debits do not equal total credits."""

    def __init__(self, currency: str, debits: int, credits: int) -> None:
        super().__init__(
            f"transaction does not balance in {currency}: "
            f"debits={debits} credits={credits}"
        )
        self.currency = currency
        self.debits = debits
        self.credits = credits


class SectorImbalanceError(LedgerError):
    """Raised (before any mutation) when one sector's share of a transaction
    does not itself balance -- i.e. a missing or mismatched counterpart
    posting. This is the fail-closed guard required by ECO-16."""

    def __init__(self, sector: Sector, currency: str, residual_minor_units: int) -> None:
        super().__init__(
            f"transaction breaks the accounting identity for sector {sector.value!r} "
            f"in {currency}: residual={residual_minor_units} minor units"
        )
        self.sector = sector
        self.currency = currency
        self.residual_minor_units = residual_minor_units


class LedgerIdentityViolation(LedgerError):
    """Raised by check_identities() when Assets != Liabilities + Equity for a
    sector. Under normal use via Ledger.post() this can never happen -- every
    posted transaction is checked before it is applied -- so this signals
    either a bypass of the public API or a bug in account bookkeeping."""

    def __init__(self, sector: Sector, currency: str, residual_minor_units: int) -> None:
        super().__init__(
            f"accounting identity violated for sector {sector.value!r} in {currency}: "
            f"assets - liabilities - equity = {residual_minor_units} minor units (expected 0)"
        )
        self.sector = sector
        self.currency = currency
        self.residual_minor_units = residual_minor_units


@dataclass
class Account:
    account_id: str
    sector: Sector
    account_type: AccountType
    currency: str = "USD"
    name: str = ""
    _balance_minor_units: int = field(default=0, repr=False)

    @property
    def balance(self) -> Money:
        return Money(self._balance_minor_units, self.currency)

    def _apply(self, side: Side, amount: Money) -> None:
        """Package-private mutator. Only Ledger.post() should call this --
        it is the sole path by which account balances change, which is what
        makes the journal an authoritative, replayable record of all state.

        Normal-balance convention: a debit increases an ASSET account and
        decreases a LIABILITY/EQUITY account; a credit does the reverse.
        This makes .balance report the economically meaningful, normally
        non-negative magnitude for every account type (contrast with the
        type-agnostic debit-positive/credit-negative residual used by
        Ledger._check_sector_balance, which computes a different quantity:
        each posting's net pull on Assets - Liabilities - Equity)."""
        if amount.currency != self.currency:
            raise CurrencyMismatchError(self.currency, amount.currency)
        if self.account_type is AccountType.ASSET:
            sign = 1 if side is Side.DEBIT else -1
        else:
            sign = -1 if side is Side.DEBIT else 1
        self._balance_minor_units += sign * amount.minor_units


@dataclass(frozen=True, slots=True)
class Posting:
    account_id: str
    side: Side
    amount: Money

    def __post_init__(self) -> None:
        if self.amount.is_negative() or self.amount.is_zero():
            raise ValueError(
                f"posting amount must be strictly positive, got {self.amount!r}; "
                "use the opposite Side to decrease a balance"
            )


@dataclass(frozen=True, slots=True)
class Transaction:
    """An immutable, balanced set of postings. Once constructed and posted,
    a Transaction is never mutated or removed from the ledger's journal --
    corrections are made with a new, offsetting transaction."""

    transaction_id: str
    step: int
    description: str
    postings: tuple[Posting, ...]

    def totals_by_currency(self) -> dict[str, tuple[int, int]]:
        """Return {currency: (total_debits, total_credits)} in minor units."""
        totals: dict[str, list[int]] = defaultdict(lambda: [0, 0])
        for p in self.postings:
            idx = 0 if p.side is Side.DEBIT else 1
            totals[p.amount.currency][idx] += p.amount.minor_units
        return {ccy: (d, c) for ccy, (d, c) in totals.items()}

    def is_balanced(self) -> bool:
        return all(d == c for d, c in self.totals_by_currency().values())


@dataclass(frozen=True, slots=True)
class EconomicState:
    """An immutable snapshot of every account balance at a point in time
    (ECO-01: typed economic state and immutable transitions). Two snapshots
    taken from identical replayed histories produce an identical hash."""

    step: int
    balances: Mapping[str, Money]
    journal_length: int

    def state_hash(self) -> str:
        parts = [f"step={self.step}", f"journal_length={self.journal_length}"]
        for account_id in sorted(self.balances):
            money = self.balances[account_id]
            parts.append(f"{account_id}={money.minor_units}{money.currency}")
        canonical = "|".join(parts)
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class Ledger:
    """A multi-sector double-entry ledger. See module docstring for the
    cross-sector instrument modeling convention."""

    def __init__(self) -> None:
        self._accounts: dict[str, Account] = {}
        self._journal: list[Transaction] = []
        self._next_seq = 0

    # -- account management --------------------------------------------

    def open_account(
        self,
        account_id: str,
        sector: Sector,
        account_type: AccountType,
        currency: str = "USD",
        name: str = "",
    ) -> Account:
        if account_id in self._accounts:
            raise DuplicateAccountError(account_id)
        account = Account(
            account_id=account_id,
            sector=sector,
            account_type=account_type,
            currency=currency,
            name=name or account_id,
        )
        self._accounts[account_id] = account
        return account

    def account(self, account_id: str) -> Account:
        try:
            return self._accounts[account_id]
        except KeyError:
            raise UnknownAccountError(account_id) from None

    def accounts_in_sector(self, sector: Sector) -> list[Account]:
        return [a for a in self._accounts.values() if a.sector is sector]

    # -- journal ----------------------------------------------------------

    @property
    def journal(self) -> tuple[Transaction, ...]:
        """Read-only view of the append-only transaction history."""
        return tuple(self._journal)

    def _generate_id(self) -> str:
        self._next_seq += 1
        return f"txn-{self._next_seq:08d}"

    def post(
        self,
        postings: list[Posting],
        description: str = "",
        step: int = 0,
        transaction_id: str | None = None,
    ) -> Transaction:
        """Validate and apply a transaction. Validation happens entirely
        before any account balance is mutated (fail closed, ECO-16): an
        imbalanced transaction, a reference to an unknown account, or a
        transaction that breaks a sector's own accounting identity is
        rejected with the ledger left exactly as it was."""
        if not postings:
            raise EmptyTransactionError()

        txn = Transaction(
            transaction_id=transaction_id or self._generate_id(),
            step=step,
            description=description,
            postings=tuple(postings),
        )

        for p in txn.postings:
            if p.account_id not in self._accounts:
                raise UnknownAccountError(p.account_id)

        for currency, (debits, credits) in txn.totals_by_currency().items():
            if debits != credits:
                raise LedgerImbalanceError(currency, debits, credits)

        self._check_sector_balance(txn)

        for p in txn.postings:
            self._accounts[p.account_id]._apply(p.side, p.amount)

        self._journal.append(txn)
        return txn

    def _check_sector_balance(self, txn: Transaction) -> None:
        """Precondition check: within this transaction, every sector's own
        postings must sum to zero (debit residual +amount, credit -amount).
        This is what catches a missing counterpart entry across sectors.

        This type-agnostic debit=+1/credit=-1 sum is exactly each posting's
        net effect on (Assets - Liabilities - Equity) for its sector,
        regardless of which of the three the posted account is: a debit on
        an asset or a credit on a liability/equity both push the residual by
        +amount, and symmetrically for the opposite sides (see the proof in
        Account._apply's docstring). So "every sector's postings net to
        zero" is exactly "this transaction cannot move any sector's
        Assets - Liabilities - Equity away from zero."""
        residuals: dict[tuple[Sector, str], int] = defaultdict(int)
        for p in txn.postings:
            account = self._accounts[p.account_id]
            sign = 1 if p.side is Side.DEBIT else -1
            residuals[(account.sector, p.amount.currency)] += sign * p.amount.minor_units
        for (sector, currency), residual in residuals.items():
            if residual != 0:
                raise SectorImbalanceError(sector, currency, residual)

    # -- invariants ---------------------------------------------------------

    def balance_sheet(self, sector: Sector, currency: str = "USD") -> dict[str, Money]:
        assets = Money.zero(currency)
        liabilities = Money.zero(currency)
        equity = Money.zero(currency)
        for account in self.accounts_in_sector(sector):
            if account.currency != currency:
                continue
            if account.account_type is AccountType.ASSET:
                assets += account.balance
            elif account.account_type is AccountType.LIABILITY:
                liabilities += account.balance
            else:
                equity += account.balance
        residual = assets - liabilities - equity
        return {
            "assets": assets,
            "liabilities": liabilities,
            "equity": equity,
            "residual": residual,
        }

    def check_identities(self, currency: str = "USD") -> None:
        """Fail-closed invariant check (ECO-16): raise LedgerIdentityViolation
        if any sector's Assets != Liabilities + Equity. Transactions posted
        through Ledger.post() can never violate this by construction; this
        method exists as an explicit, independently callable detector -- the
        kind of defense-in-depth check a replay or audit tool should run."""
        sectors = {a.sector for a in self._accounts.values() if a.currency == currency}
        for sector in sectors:
            sheet = self.balance_sheet(sector, currency)
            residual = sheet["residual"]
            if not residual.is_zero():
                raise LedgerIdentityViolation(sector, currency, residual.minor_units)

    def snapshot(self, step: int) -> EconomicState:
        balances = {aid: acct.balance for aid, acct in self._accounts.items()}
        return EconomicState(step=step, balances=balances, journal_length=len(self._journal))
