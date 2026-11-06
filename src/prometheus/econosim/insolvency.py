"""Multi-creditor corporate default and insolvency process (LED-07).

`Bank.write_off_loan` (PR-043) is the single-creditor building block: it
extinguishes one bank's claim against one borrower, in isolation, and
assumes the caller already knows exactly how much to write off. Real
insolvency resolution has to do two things that single-creditor write-off
cannot: split one scarce pool of recovered cash across MULTIPLE creditors
holding DIFFERENT claims, and respect creditor seniority while doing it
-- the "absolute priority rule": a senior (e.g. secured) claim must be
paid in full before any junior (e.g. subordinated) claim receives
anything, and claims that share a priority tier split a short recovery
pro rata by claim size, not by arrival order.

This module adds exactly that allocation on top of the existing
primitives. `allocate_recovery` is pure arithmetic with no ledger side
effects, so its waterfall/apportionment logic can be (and is) tested
completely independently of any posting. `resolve_insolvency` then
applies that allocation through the existing `Bank.receive_repayment`
(for the paid portion of each claim) and `Bank.write_off_loan` (for the
unpaid shortfall), exactly one call of each per claim -- it does not
introduce a new posting pattern, only a new way of sizing the existing
two calls per creditor.

Known limitation, inherited from `econosim.agents` (see that module's own
docstring): a borrower's `loan_account` is one pooled liability balance
across every creditor, and a bank's `receive_repayment`/`write_off_loan`
touch that bank's own `deposits_account` as if the borrower's cash were a
deposit at that specific bank. This module does not change that
convention -- callers supply the per-creditor claim breakdown explicitly
(the same way `titan.contagion.eisenberg_noe_clearing` takes an explicit
pairwise obligations matrix rather than inferring one from an aggregate
balance), and `resolve_insolvency` validates that the supplied claims sum
to exactly the borrower's current pooled debt before changing anything.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum

from prometheus.core.ledger import Transaction
from prometheus.core.money import Money
from prometheus.econosim.agents import Bank, Borrower


class ClaimPriority(IntEnum):
    """Lower value = more senior = paid first under the absolute priority
    rule. Creditors sharing a value are the same tier and split a short
    recovery pro rata by claim size."""

    SECURED = 0
    SENIOR_UNSECURED = 1
    SUBORDINATED = 2


@dataclass(frozen=True)
class CreditorClaim:
    """One creditor's claim against the borrower being resolved.

    `amount` is this specific bank's own claim, not the borrower's pooled
    ledger balance -- the caller (simulation/orchestration code, which
    knows each loan's origin) is responsible for tracking it, exactly as
    `titan.contagion`'s nominal-obligations matrix is caller-supplied.
    """

    creditor: Bank
    amount: Money
    priority: ClaimPriority


@dataclass(frozen=True)
class ClaimSettlement:
    """How one claim was actually resolved: `paid + written_off == claim.amount`."""

    claim: CreditorClaim
    paid: Money
    written_off: Money


@dataclass(frozen=True)
class InsolvencyResult:
    borrower_id: str
    recovery: Money
    settlements: tuple[ClaimSettlement, ...]
    transactions: tuple[Transaction, ...]


def _apportion(amounts: list[int], target: int) -> list[int]:
    """Largest-remainder (Hamilton) apportionment: split integer `target`
    across `amounts`' shares as close as possible to each amount's exact
    real-valued proportion, with the integer shares summing to EXACTLY
    `target` (never leaving a leftover or minor-unit rounding drift).
    Ties in the fractional remainder are broken by ascending index, so the
    result is deterministic given the input order."""
    total = sum(amounts)
    shares = []
    remainders = []
    for amount in amounts:
        product = amount * target
        shares.append(product // total)
        remainders.append(product % total)
    leftover = target - sum(shares)
    order = sorted(range(len(amounts)), key=lambda i: (-remainders[i], i))
    for i in order[:leftover]:
        shares[i] += 1
    return shares


def allocate_recovery(claims: list[CreditorClaim], recovery: Money) -> list[Money]:
    """Pure allocation math (no ledger side effects): how much of
    `recovery` each entry of `claims` receives, under the absolute
    priority rule with pro-rata sharing within a tier. Returns one Money
    per claim, in the same order as `claims`, summing to exactly
    `recovery` (or to the sum of all claims, whichever is reached first --
    a tier is either paid in full or exhausts the remaining recovery, by
    construction of the waterfall)."""
    if not claims:
        raise ValueError("claims must be non-empty")
    currency = claims[0].amount.currency
    for claim in claims:
        if not claim.amount.is_positive():
            raise ValueError("every claim amount must be positive")
        if claim.amount.currency != currency:
            raise ValueError("all claims must share one currency")
    if recovery.currency != currency:
        raise ValueError("recovery currency must match the claims' currency")
    if recovery.is_negative():
        raise ValueError("recovery must be non-negative")
    total_claims = sum((c.amount for c in claims), Money.zero(currency))
    if recovery > total_claims:
        raise ValueError(
            f"recovery {recovery!r} exceeds total claims {total_claims!r}: "
            "this is not an insolvency allocation if every claim can be paid in full"
        )

    allocation = [Money.zero(currency) for _ in claims]
    remaining = recovery.minor_units
    for tier in sorted({claim.priority for claim in claims}):
        if remaining == 0:
            break
        tier_indices = [i for i, c in enumerate(claims) if c.priority == tier]
        tier_amounts = [claims[i].amount.minor_units for i in tier_indices]
        tier_total = sum(tier_amounts)
        if remaining >= tier_total:
            for i in tier_indices:
                allocation[i] = claims[i].amount
            remaining -= tier_total
        else:
            shares = _apportion(tier_amounts, remaining)
            for i, share in zip(tier_indices, shares, strict=True):
                allocation[i] = Money(share, currency)
            remaining = 0
    return allocation


def resolve_insolvency(
    borrower: Borrower, claims: list[CreditorClaim], recovery: Money, step: int = 0
) -> InsolvencyResult:
    """Resolve `borrower`'s default against every creditor in `claims` at
    once: allocate `recovery` by absolute priority (see
    `allocate_recovery`), pay each creditor its allocated share via the
    existing `Bank.receive_repayment`, and write off the remaining
    shortfall of each claim via the existing `Bank.write_off_loan`.

    Fails closed before posting anything if `claims` does not exactly
    account for the borrower's current pooled debt, or if `recovery`
    exceeds the borrower's actual cash on hand -- a partially-applied
    insolvency resolution would leave the ledger in a state no real
    insolvency process can produce.
    """
    if not claims:
        raise ValueError("claims must be non-empty")
    ledger = claims[0].creditor.ledger
    currency = claims[0].amount.currency
    outstanding = ledger.account(borrower.loan_account).balance
    total_claims = sum((c.amount for c in claims), Money.zero(currency))
    if total_claims != outstanding:
        raise ValueError(
            f"supplied claims total {total_claims!r} but {borrower.agent_id}'s "
            f"recorded debt is {outstanding!r}: claims must exactly partition "
            "the borrower's pooled liability before insolvency can be resolved"
        )
    borrower_cash = ledger.account(borrower.cash_account).balance
    if recovery > borrower_cash:
        raise ValueError(
            f"recovery {recovery!r} exceeds {borrower.agent_id}'s actual cash "
            f"on hand {borrower_cash!r}"
        )

    allocation = allocate_recovery(claims, recovery)
    settlements = []
    transactions: list[Transaction] = []
    for claim, paid in zip(claims, allocation, strict=True):
        written_off = claim.amount - paid
        if paid.is_positive():
            transactions.append(claim.creditor.receive_repayment(borrower, paid, step=step))
        if written_off.is_positive():
            transactions.append(claim.creditor.write_off_loan(borrower, written_off, step=step))
        settlements.append(ClaimSettlement(claim, paid, written_off))
    return InsolvencyResult(
        borrower_id=borrower.agent_id,
        recovery=recovery,
        settlements=tuple(settlements),
        transactions=tuple(transactions),
    )
