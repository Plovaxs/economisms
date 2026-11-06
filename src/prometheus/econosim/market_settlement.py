"""Atomic single-firm settlement of exact price/quantity allocations.

One balanced journal batch transfers all market payments. Expected funds,
participant, currency and ledger failures are checked before mutation.
Largest-remainder rounding distributes floor(total nominal value) across
households deterministically, with ties ordered by agent ID. Aggregate
rounding loss is less than one minor unit; no cash is created or destroyed.
Whole multi-market macro steps are not transactions and are not rolled back.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from fractions import Fraction
from typing import Literal

from prometheus.core.ledger import Posting, Side, Transaction
from prometheus.core.money import CurrencyMismatchError, Money
from prometheus.econosim.agents import Firm, Household, InsufficientFundsError
from prometheus.econosim.price_discovery import MarketAllocation


@dataclass(frozen=True, slots=True)
class MarketPayment:
    household_id: str
    quantity: Fraction
    nominal_minor_units: Fraction
    paid: Money
    rounding_adjustment: Fraction


@dataclass(frozen=True, slots=True)
class MarketSettlement:
    kind: Literal["labor", "goods"]
    realized_quantity: Fraction
    payments: tuple[MarketPayment, ...]
    total_paid: Money
    rounding_remainder: Fraction
    transaction: Transaction | None


def settle_market(
    allocation: MarketAllocation,
    kind: Literal["labor", "goods"],
    firm: Firm,
    households: Mapping[str, Household],
    *,
    step: int = 0,
) -> MarketSettlement:
    if kind not in ("labor", "goods"):
        raise ValueError("market kind must be labor or goods")
    firm_side = allocation.buyers if kind == "labor" else allocation.sellers
    household_side = allocation.sellers if kind == "labor" else allocation.buyers
    if {order.agent_id for order in firm_side} != {firm.agent_id}:
        raise ValueError("single-firm settlement requires exactly this firm on its market side")
    if firm.currency != allocation.price.currency:
        raise CurrencyMismatchError(firm.currency, allocation.price.currency)
    participants = []
    for order in sorted(household_side, key=lambda item: item.agent_id):
        if order.agent_id not in households:
            raise KeyError(f"unknown market household: {order.agent_id!r}")
        household = households[order.agent_id]
        if household.agent_id != order.agent_id or household.ledger is not firm.ledger:
            raise ValueError("market participants must have matching IDs and share one ledger")
        if household.currency != firm.currency:
            raise CurrencyMismatchError(firm.currency, household.currency)
        participants.append((order, household))
    firm.ledger.check_identities(firm.currency)

    nominal = [order.realized * allocation.price.minor_units for order, _ in participants]
    paid = [int(amount) for amount in nominal]
    nominal_total = sum(nominal, Fraction(0))
    total_minor = int(nominal_total)
    remaining = total_minor - sum(paid)
    ranking = sorted(
        range(len(paid)),
        key=lambda index: (-(nominal[index] - paid[index]), participants[index][0].agent_id),
    )
    for index in ranking[:remaining]:
        paid[index] += 1
    total = Money(total_minor, firm.currency)
    if kind == "labor" and firm.cash_balance < total:
        raise InsufficientFundsError(firm.agent_id, total, firm.cash_balance)
    if kind == "goods":
        for index, (_, household) in enumerate(participants):
            required = Money(paid[index], firm.currency)
            if household.cash_balance < required:
                raise InsufficientFundsError(household.agent_id, required, household.cash_balance)

    payments = []
    postings = []
    for index, (order, household) in enumerate(participants):
        amount = Money(paid[index], firm.currency)
        payments.append(
            MarketPayment(
                order.agent_id,
                order.realized,
                nominal[index],
                amount,
                Fraction(paid[index]) - nominal[index],
            )
        )
        if not paid[index]:
            continue
        if kind == "labor":
            postings.extend(
                [
                    Posting(firm.deposit_account, Side.CREDIT, amount),
                    Posting(firm.equity_account, Side.DEBIT, amount),
                    Posting(household.cash_account, Side.DEBIT, amount),
                    Posting(household.equity_account, Side.CREDIT, amount),
                ]
            )
        else:
            postings.extend(
                [
                    Posting(household.cash_account, Side.CREDIT, amount),
                    Posting(household.equity_account, Side.DEBIT, amount),
                    Posting(firm.deposit_account, Side.DEBIT, amount),
                    Posting(firm.equity_account, Side.CREDIT, amount),
                ]
            )
    transaction = (
        firm.ledger.post(postings, description=f"{kind} market batch", step=step)
        if postings
        else None
    )
    return MarketSettlement(
        kind,
        allocation.realized_quantity,
        tuple(payments),
        total,
        nominal_total - total_minor,
        transaction,
    )
