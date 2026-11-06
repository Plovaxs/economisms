"""Generic quantity-based market clearing with pro-rata rationing on the
short side (ECO-07 goods market / ECO-08 labor market). Price is exogenous
in this v0 -- there is no iterative price discovery (tatonnement); a buyer
and a seller each submit a desired quantity at an already-given price/wage,
and clear_quantity_market() only determines how much of each is actually
realized when aggregate supply and demand don't match.

ECO-08's "no double counting of hours or paid wages" is a structural
property of the pro-rata construction, not a runtime check: every buyer's
realized quantity is desired_quantity * (total_realized / total_demand),
and every seller's is desired_quantity * (total_realized / total_supply),
so summing either side always returns exactly total_realized_quantity --
proven in tests, not merely asserted.

apply_labor_clearing_to_ledger / apply_goods_clearing_to_ledger execute a
ClearingResult onto the ledger for the common single-firm case (N
households <-> 1 firm), via the existing Firm.pay_wages / Household.consume
methods, so realized (not desired) quantities are what actually get paid.
A general many-buyer/many-seller ledger execution would need a market-
maker/clearing-account abstraction that does not exist yet; that case is
explicitly out of scope here, not silently approximated.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Literal

from prometheus.core.ledger import Transaction
from prometheus.core.money import CurrencyMismatchError, Money
from prometheus.econosim.agents import Firm, Household, InsufficientFundsError


@dataclass(frozen=True, slots=True)
class ClearingResult:
    realized_buy_quantities: dict[str, float]
    realized_sell_quantities: dict[str, float]
    total_realized_quantity: float
    total_desired_demand: float
    total_desired_supply: float
    clearing_residual: float
    """total_desired_demand - total_desired_supply: positive means excess
    demand (buyers rationed), negative means excess supply (sellers
    rationed), zero means the market cleared exactly."""


def clear_quantity_market(
    buy_orders: dict[str, float], sell_orders: dict[str, float]
) -> ClearingResult:
    if any(isinstance(q, bool) or not math.isfinite(q) or q < 0 for q in buy_orders.values()):
        raise ValueError("buy_orders quantities must be finite and non-negative")
    if any(isinstance(q, bool) or not math.isfinite(q) or q < 0 for q in sell_orders.values()):
        raise ValueError("sell_orders quantities must be finite and non-negative")

    total_demand = sum(buy_orders.values())
    total_supply = sum(sell_orders.values())
    if not math.isfinite(total_demand) or not math.isfinite(total_supply):
        raise ValueError("aggregate order quantity must be finite")
    total_realized = min(total_demand, total_supply)

    demand_fill_ratio = total_realized / total_demand if total_demand > 0 else 0.0
    supply_fill_ratio = total_realized / total_supply if total_supply > 0 else 0.0

    realized_buy = {buyer: qty * demand_fill_ratio for buyer, qty in buy_orders.items()}
    realized_sell = {seller: qty * supply_fill_ratio for seller, qty in sell_orders.items()}

    return ClearingResult(
        realized_buy_quantities=realized_buy,
        realized_sell_quantities=realized_sell,
        total_realized_quantity=total_realized,
        total_desired_demand=total_demand,
        total_desired_supply=total_supply,
        clearing_residual=total_demand - total_supply,
    )


def _settlement_plan(
    clearing: ClearingResult,
    households: dict[str, Household],
    firm: Firm,
    price: Money,
    kind: Literal["labor", "goods"],
) -> list[tuple[Household, Money]]:
    """Preflight every legacy per-household posting, preserving its floor rounding and IDs."""
    if not price.is_positive():
        raise ValueError("unit price must be positive")
    if price.currency != firm.currency:
        raise CurrencyMismatchError(firm.currency, price.currency)
    values = [
        *clearing.realized_buy_quantities.values(),
        *clearing.realized_sell_quantities.values(),
        clearing.total_realized_quantity,
        clearing.total_desired_demand,
        clearing.total_desired_supply,
    ]
    if any(not math.isfinite(value) or value < 0 for value in values):
        raise ValueError("clearing quantities must be finite and non-negative")
    total = clearing.total_realized_quantity
    for value in (
        sum(clearing.realized_buy_quantities.values()),
        sum(clearing.realized_sell_quantities.values()),
        min(clearing.total_desired_demand, clearing.total_desired_supply),
    ):
        if not math.isclose(value, total, rel_tol=1e-12, abs_tol=1e-12):
            raise ValueError("clearing quantities do not reconcile")
    firm_side = (
        clearing.realized_buy_quantities if kind == "labor" else clearing.realized_sell_quantities
    )
    household_side = (
        clearing.realized_sell_quantities if kind == "labor" else clearing.realized_buy_quantities
    )
    if set(firm_side) != {firm.agent_id}:
        raise ValueError("single-firm settlement requires this firm as the sole counterparty")
    firm.ledger.check_identities(firm.currency)
    plan = []
    for household_id, realized in household_side.items():
        if household_id not in households:
            raise KeyError(f"unknown household_id in clearing result: {household_id!r}")
        household = households[household_id]
        if household.agent_id != household_id or household.ledger is not firm.ledger:
            raise ValueError("household IDs and shared ledger must match the market")
        if household.currency != firm.currency:
            raise CurrencyMismatchError(firm.currency, household.currency)
        amount = Money(int(realized * price.minor_units), price.currency)
        if kind == "goods" and household.cash_balance < amount:
            raise InsufficientFundsError(household_id, amount, household.cash_balance)
        plan.append((household, amount))
    wage_bill = Money(sum(amount.minor_units for _, amount in plan), price.currency)
    if kind == "labor" and firm.cash_balance < wage_bill:
        raise InsufficientFundsError(firm.agent_id, wage_bill, firm.cash_balance)
    return plan


def apply_labor_clearing_to_ledger(
    clearing: ClearingResult,
    households: dict[str, Household],
    firm: Firm,
    wage_rate_per_hour: Money,
    step: int = 0,
) -> list[Transaction]:
    """Pay each household for its realized (rationed) labor hours via
    Firm.pay_wages, in integer minor units -- fractional-hour wage amounts
    are rounded down (floor) so total paid never exceeds
    total_realized_quantity * wage_rate_per_hour by construction.

    Households are the *sellers* in this market (they supply labor; the
    firm demands it), so their realized quantities are in
    `clearing.realized_sell_quantities` -- the caller must have built
    `clearing` with households as sell_orders and the firm as the (single)
    buy_orders entry."""
    plan = _settlement_plan(clearing, households, firm, wage_rate_per_hour, "labor")
    return [
        firm.pay_wages(household, amount, step=step)
        for household, amount in plan
        if amount.is_positive()
    ]


def apply_goods_clearing_to_ledger(
    clearing: ClearingResult,
    firm: Firm,
    households: dict[str, Household],
    price_per_unit: Money,
    step: int = 0,
) -> list[Transaction]:
    """Charge each household for its realized (rationed) goods purchase via
    Household.consume, in integer minor units (floored, same rationale as
    apply_labor_clearing_to_ledger).

    Households are the *buyers* in this market (they demand goods; the
    firm supplies them), so their realized quantities are in
    `clearing.realized_buy_quantities` -- the caller must have built
    `clearing` with households as buy_orders and the firm as the (single)
    sell_orders entry."""
    plan = _settlement_plan(clearing, households, firm, price_per_unit, "goods")
    return [
        household.consume(firm, amount, step=step)
        for household, amount in plan
        if amount.is_positive()
    ]
