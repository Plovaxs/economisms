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

from dataclasses import dataclass

from prometheus.core.ledger import Transaction
from prometheus.core.money import Money
from prometheus.econosim.agents import Firm, Household


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
    if any(q < 0 for q in buy_orders.values()):
        raise ValueError("buy_orders quantities must be non-negative")
    if any(q < 0 for q in sell_orders.values()):
        raise ValueError("sell_orders quantities must be non-negative")

    total_demand = sum(buy_orders.values())
    total_supply = sum(sell_orders.values())
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
    transactions: list[Transaction] = []
    for household_id, realized_hours in clearing.realized_sell_quantities.items():
        if household_id not in households:
            raise KeyError(f"unknown household_id in clearing result: {household_id!r}")
        amount_minor = int(realized_hours * wage_rate_per_hour.minor_units)
        if amount_minor <= 0:
            continue
        amount = Money(amount_minor, wage_rate_per_hour.currency)
        transactions.append(firm.pay_wages(households[household_id], amount, step=step))
    return transactions


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
    transactions: list[Transaction] = []
    for household_id, realized_quantity in clearing.realized_buy_quantities.items():
        if household_id not in households:
            raise KeyError(f"unknown household_id in clearing result: {household_id!r}")
        amount_minor = int(realized_quantity * price_per_unit.minor_units)
        if amount_minor <= 0:
            continue
        amount = Money(amount_minor, price_per_unit.currency)
        transactions.append(households[household_id].consume(firm, amount, step=step))
    return transactions
