"""Budget demand, monotone supply and bounded price discovery on integer ticks.

Quantities and residuals are exact Fractions. Demand is min(cap, budget/p);
supply is a capacity-limited linear schedule. These deliberately simple
rules guarantee monotone excess demand, allowing integer-tick bisection.
An adjacent-tick bracket or binding price bound is reported explicitly;
rationing quantities does not imply that desired demand equals supply.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from fractions import Fraction
from typing import Literal

from prometheus.core.money import CurrencyMismatchError, Money


def quantity(value: Fraction | int | float) -> Fraction:
    if isinstance(value, bool):
        raise ValueError("quantity must be a finite non-negative number")
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("quantity must be finite")
        value = Fraction(str(value))
    if not isinstance(value, (int, Fraction)) or value < 0:
        raise ValueError("quantity must be a finite non-negative number")
    return Fraction(value)


def _currency(price: Money, other: Money) -> None:
    if price.currency != other.currency:
        raise CurrencyMismatchError(price.currency, other.currency)


@dataclass(frozen=True, slots=True)
class BudgetDemand:
    budget: Money
    max_quantity: Fraction

    def __post_init__(self) -> None:
        if not isinstance(self.budget, Money) or self.budget.minor_units < 0:
            raise ValueError("demand budget must be non-negative Money")
        object.__setattr__(self, "max_quantity", quantity(self.max_quantity))

    def at(self, price: Money) -> Fraction:
        _currency(price, self.budget)
        if price.minor_units <= 0:
            raise ValueError("price must be positive")
        return min(self.max_quantity, Fraction(self.budget.minor_units, price.minor_units))


@dataclass(frozen=True, slots=True)
class LinearSupply:
    reference_price: Money
    reference_quantity: Fraction
    slope: Fraction
    capacity: Fraction

    def __post_init__(self) -> None:
        if not isinstance(self.reference_price, Money) or self.reference_price.minor_units <= 0:
            raise ValueError("reference price must be positive Money")
        for name in ("reference_quantity", "slope", "capacity"):
            object.__setattr__(self, name, quantity(getattr(self, name)))
        if self.reference_quantity > self.capacity:
            raise ValueError("reference quantity must not exceed capacity")

    def at(self, price: Money) -> Fraction:
        _currency(price, self.reference_price)
        if price.minor_units <= 0:
            raise ValueError("price must be positive")
        desired = self.reference_quantity + self.slope * (
            price.minor_units - self.reference_price.minor_units
        )
        return min(self.capacity, max(Fraction(0), desired))


@dataclass(frozen=True, slots=True)
class FilledOrder:
    agent_id: str
    desired: Fraction
    realized: Fraction

    def __post_init__(self) -> None:
        if not isinstance(self.agent_id, str) or not self.agent_id:
            raise ValueError("agent_id must be non-empty text")
        object.__setattr__(self, "desired", quantity(self.desired))
        object.__setattr__(self, "realized", quantity(self.realized))
        if self.realized > self.desired:
            raise ValueError("realized quantity exceeds desired quantity")


@dataclass(frozen=True, slots=True)
class MarketAllocation:
    price: Money
    buyers: tuple[FilledOrder, ...]
    sellers: tuple[FilledOrder, ...]

    @property
    def demand(self) -> Fraction:
        return sum((order.desired for order in self.buyers), Fraction(0))

    @property
    def supply(self) -> Fraction:
        return sum((order.desired for order in self.sellers), Fraction(0))

    @property
    def realized_quantity(self) -> Fraction:
        return min(self.demand, self.supply)

    @property
    def excess_demand(self) -> Fraction:
        return self.demand - self.supply

    def __post_init__(self) -> None:
        if not isinstance(self.price, Money) or self.price.minor_units <= 0:
            raise ValueError("allocation price must be positive Money")
        if not isinstance(self.buyers, tuple) or not isinstance(self.sellers, tuple):
            raise ValueError("allocation orders must be immutable tuples")
        buyer_ids = {order.agent_id for order in self.buyers}
        seller_ids = {order.agent_id for order in self.sellers}
        if len(buyer_ids) != len(self.buyers) or len(seller_ids) != len(self.sellers):
            raise ValueError("duplicate participant on a market side")
        if buyer_ids & seller_ids:
            raise ValueError("a participant cannot be on both market sides")
        for orders, total in ((self.buyers, self.demand), (self.sellers, self.supply)):
            for order in orders:
                expected = order.desired * self.realized_quantity / total if total else Fraction(0)
                if order.realized != expected:
                    raise ValueError("allocation must reconcile exact pro-rata quantities")


def clear_at_price(
    price: Money,
    buyers: Mapping[str, BudgetDemand],
    sellers: Mapping[str, LinearSupply],
) -> MarketAllocation:
    buy_quantities = {name: schedule.at(price) for name, schedule in sorted(buyers.items())}
    sell_quantities = {name: schedule.at(price) for name, schedule in sorted(sellers.items())}
    demand = sum(buy_quantities.values(), Fraction(0))
    supply = sum(sell_quantities.values(), Fraction(0))
    realized = min(demand, supply)
    return MarketAllocation(
        price,
        tuple(
            FilledOrder(name, desired, desired * realized / demand if demand else Fraction(0))
            for name, desired in buy_quantities.items()
        ),
        tuple(
            FilledOrder(name, desired, desired * realized / supply if supply else Fraction(0))
            for name, desired in sell_quantities.items()
        ),
    )


@dataclass(frozen=True, slots=True)
class PriceSearchConfig:
    floor: Money
    ceiling: Money
    quantity_tolerance: Fraction = Fraction(1, 1_000_000)
    max_evaluations: int = 32

    def __post_init__(self) -> None:
        if not isinstance(self.floor, Money) or not isinstance(self.ceiling, Money):
            raise ValueError("price bounds must be Money")
        _currency(self.floor, self.ceiling)
        if not 0 < self.floor.minor_units <= self.ceiling.minor_units:
            raise ValueError("price bounds must be positive and ordered")
        object.__setattr__(self, "quantity_tolerance", quantity(self.quantity_tolerance))
        if type(self.max_evaluations) is not int or self.max_evaluations < 3:
            raise ValueError("max_evaluations must be an integer >= 3")


@dataclass(frozen=True, slots=True)
class QuoteEvaluation:
    price: Money
    demand: Fraction
    supply: Fraction
    excess_demand: Fraction


PriceStatus = Literal[
    "cleared", "tick_limited", "floor_limited", "ceiling_limited", "iteration_limit", "no_trade"
]


@dataclass(frozen=True, slots=True)
class PriceSearchResult:
    allocation: MarketAllocation
    status: PriceStatus
    bracket: tuple[Money, Money]
    tolerance: Fraction
    evaluations: tuple[QuoteEvaluation, ...]


def discover_price(
    buyers: Mapping[str, BudgetDemand],
    sellers: Mapping[str, LinearSupply],
    config: PriceSearchConfig,
    *,
    initial_price: Money | None = None,
) -> PriceSearchResult:
    low, high = config.floor.minor_units, config.ceiling.minor_units
    quotes: dict[int, MarketAllocation] = {}

    def quote(tick: int) -> MarketAllocation:
        if tick not in quotes:
            quotes[tick] = clear_at_price(Money(tick, config.floor.currency), buyers, sellers)
        return quotes[tick]

    def result(selected: MarketAllocation, status: PriceStatus) -> PriceSearchResult:
        if abs(selected.excess_demand) <= config.quantity_tolerance:
            status = "cleared" if selected.realized_quantity > 0 else "no_trade"
        return PriceSearchResult(
            selected,
            status,
            (Money(low, config.floor.currency), Money(high, config.floor.currency)),
            config.quantity_tolerance,
            tuple(
                QuoteEvaluation(item.price, item.demand, item.supply, item.excess_demand)
                for item in quotes.values()
            ),
        )

    if initial_price is not None:
        _currency(config.floor, initial_price)
        if not low <= initial_price.minor_units <= high:
            raise ValueError("initial price must lie within the price bounds")
        initial = quote(initial_price.minor_units)
        if abs(initial.excess_demand) <= config.quantity_tolerance:
            return result(initial, "cleared")
    lower, upper = quote(low), quote(high)
    if lower.excess_demand <= config.quantity_tolerance:
        return result(lower, "floor_limited")
    if upper.excess_demand >= -config.quantity_tolerance:
        return result(upper, "ceiling_limited")
    if initial_price is not None:
        if initial.excess_demand > 0:
            low = initial_price.minor_units
        else:
            high = initial_price.minor_units
    while high - low > 1 and len(quotes) < config.max_evaluations:
        middle = (low + high) // 2
        current = quote(middle)
        if abs(current.excess_demand) <= config.quantity_tolerance:
            return result(current, "cleared")
        if current.excess_demand > 0:
            low = middle
        else:
            high = middle
    selected = min(
        (quote(low), quote(high)),
        key=lambda item: (abs(item.excess_demand), item.price.minor_units),
    )
    return result(selected, "tick_limited" if high - low <= 1 else "iteration_limit")
