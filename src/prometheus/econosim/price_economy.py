"""Reusable exact price-economy configuration, state and engine hooks."""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass, fields
from datetime import date
from fractions import Fraction
from typing import Any

from prometheus.core.money import Money
from prometheus.core.seeds import SeedHierarchy
from prometheus.econosim.economy import Economy
from prometheus.econosim.market_settlement import MarketSettlement, settle_market
from prometheus.econosim.price_discovery import (
    BudgetDemand,
    LinearSupply,
    PriceSearchConfig,
    PriceSearchResult,
    discover_price,
    quantity,
)
from prometheus.econosim.step_hooks import StepContext
from prometheus.econosim.time_engine import StepResult


def _fraction_from_dict(value: Any) -> Fraction:
    if isinstance(value, Mapping):
        if set(value) != {"numerator", "denominator"}:
            raise ValueError("rational values require numerator and denominator")
        if any(type(value[key]) is not int for key in value) or value["denominator"] <= 0:
            raise ValueError("rational components must be integers with a positive denominator")
        return quantity(Fraction(value["numerator"], value["denominator"]))
    return quantity(value)


@dataclass(frozen=True, slots=True)
class EconomyRunConfig:
    seed: int = 0
    start_date: date = date(2026, 1, 2)
    n_steps: int = 12
    n_households: int = 2
    firm_capital: Money = Money(200000)
    household_initial_cash: Money = Money(100000)
    payroll_target: Money = Money(18000)
    payroll_cash_fraction: Fraction = Fraction(1)
    max_labor_demand: Fraction = Fraction(24)
    household_labor_capacity: Fraction = Fraction(12)
    labor_supply_slope: Fraction = Fraction(1, 50)
    labor_reservation_wage: Money = Money(500)
    initial_wage: Money = Money(1000)
    wage_floor: Money = Money(500)
    wage_ceiling: Money = Money(2000)
    initial_goods_price: Money = Money(100)
    goods_floor: Money = Money(1)
    goods_ceiling: Money = Money(10000)
    goods_reservation_price: Money = Money(25)
    goods_supply_slope: Fraction = Fraction(2)
    household_goods_cap: Fraction = Fraction(1000)
    consumption_propensity: Fraction = Fraction(1)
    initial_inventory: Fraction = Fraction(0)
    productivity: Fraction = Fraction(10)
    productivity_shock_step: int | None = 4
    productivity_shock_multiplier: Fraction = Fraction(1, 2)
    productivity_noise_std: float = 0.0
    quantity_tolerance: Fraction = Fraction(1, 1000000)
    max_price_evaluations: int = 32
    require_price_resolution: bool = True

    def __post_init__(self) -> None:
        for name in ("seed", "n_steps", "n_households", "max_price_evaluations"):
            value = getattr(self, name)
            minimum = 0 if name == "seed" else 1
            if type(value) is not int or value < minimum:
                raise ValueError(f"{name} must be an integer >= {minimum}")
        if type(self.start_date) is not date or type(self.require_price_resolution) is not bool:
            raise ValueError("start_date must be a date and require_price_resolution a bool")
        for item in fields(self):
            value = getattr(self, item.name)
            if isinstance(item.default, Money):
                if not isinstance(value, Money) or value.currency != "USD" or value.minor_units < 0:
                    raise ValueError(f"{item.name} must be non-negative USD Money")
            elif isinstance(item.default, Fraction):
                object.__setattr__(self, item.name, quantity(value))
        if self.payroll_cash_fraction > 1 or self.consumption_propensity > 1:
            raise ValueError("cash/consumption fractions must be in [0, 1]")
        if self.productivity_shock_step is not None and (
            type(self.productivity_shock_step) is not int
            or not 1 <= self.productivity_shock_step <= self.n_steps
        ):
            raise ValueError("productivity_shock_step must be None or within [1, n_steps]")
        if (
            isinstance(self.productivity_noise_std, bool)
            or not isinstance(self.productivity_noise_std, (int, float))
            or (not math.isfinite(self.productivity_noise_std))
            or (self.productivity_noise_std < 0)
        ):
            raise ValueError("productivity_noise_std must be finite and non-negative")
        self.price_config("labor")
        self.price_config("goods")
        for initial, floor, ceiling in (
            (self.initial_wage, self.wage_floor, self.wage_ceiling),
            (self.initial_goods_price, self.goods_floor, self.goods_ceiling),
        ):
            if not floor <= initial <= ceiling:
                raise ValueError("initial quotes must lie within price bounds")
        if (
            not self.labor_reservation_wage.is_positive()
            or not self.goods_reservation_price.is_positive()
        ):
            raise ValueError("supply reference prices must be positive")

    def price_config(self, market: str) -> PriceSearchConfig:
        floor = self.wage_floor if market == "labor" else self.goods_floor
        ceiling = self.wage_ceiling if market == "labor" else self.goods_ceiling
        return PriceSearchConfig(
            floor, ceiling, self.quantity_tolerance, self.max_price_evaluations
        )

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> EconomyRunConfig:
        if set(payload) != {item.name for item in fields(cls)}:
            raise ValueError("economy replay requires exactly the complete configuration fields")
        values = dict(payload)
        try:
            for item in fields(cls):
                if isinstance(item.default, Money) and isinstance(values[item.name], Mapping):
                    values[item.name] = Money(**values[item.name])
                elif isinstance(item.default, Fraction):
                    values[item.name] = _fraction_from_dict(values[item.name])
            if isinstance(values["start_date"], str):
                values["start_date"] = date.fromisoformat(values["start_date"])
            return cls(**values)
        except (TypeError, AttributeError) as exc:
            raise ValueError(f"invalid economy replay configuration: {exc}") from exc


@dataclass(frozen=True, slots=True)
class EconomicActions:
    productivity: Fraction
    noise_factor: Fraction
    noise_clamped: bool
    payroll_cash_before: Money
    payroll_budget: Money
    payroll_budget_binding: bool


@dataclass(frozen=True, slots=True)
class EconomicSettlement:
    labor: PriceSearchResult
    wages: MarketSettlement
    goods: PriceSearchResult
    sales: MarketSettlement
    inventory_before: Fraction
    produced: Fraction
    inventory_after: Fraction


@dataclass(frozen=True, slots=True)
class EconomyStep:
    step: int
    step_date: date
    actions: EconomicActions
    settlement: EconomicSettlement
    firm_cash: Money
    household_cash: tuple[tuple[str, Money], ...]
    total_cash: Money
    total_equity: Money
    cumulative_production: Fraction
    cumulative_sales: Fraction
    ledger_state_hash: str


class PriceEconomy:
    def __init__(self, config: EconomyRunConfig):
        self.config = config
        self.economy = Economy()
        self.firm = self.economy.add_firm("firm-1")
        self.households = {
            f"hh-{index:04d}": self.economy.add_household(f"hh-{index:04d}")
            for index in range(1, self.config.n_households + 1)
        }
        if self.config.firm_capital.is_positive():
            self.firm.capitalize(self.config.firm_capital)
        if self.config.household_initial_cash.is_positive():
            for household in self.households.values():
                household.receive_income(self.config.household_initial_cash)
        self.injected = (
            self.config.firm_capital + self.config.household_initial_cash * self.config.n_households
        )
        self.initial_state_hash = self.economy.ledger.snapshot(0).state_hash()
        self.productivity = self.config.productivity
        self.inventory = self.config.initial_inventory
        self.wage = self.config.initial_wage
        self.goods_price = self.config.initial_goods_price
        self.cumulative_production = self.cumulative_sales = Fraction(0)
        self.rng = SeedHierarchy(self.config.seed).stream("productivity")
        self._action_step = self._settled_step = 0
        self._last_actions: EconomicActions | None = None
        self._last_settlement: EconomicSettlement | None = None

    def compute_actions(
        self, ctx: StepContext, *, payroll_target: Money | None = None
    ) -> EconomicActions:
        if ctx.economy is not self.economy or ctx.step != self._settled_step + 1:
            raise ValueError("price-economy context must match its next unsettled step")
        if ctx.step <= self._action_step:
            raise ValueError("economic actions have already been computed for this step")
        target = self.config.payroll_target if payroll_target is None else payroll_target
        if not isinstance(target, Money) or target.currency != "USD" or target.minor_units < 0:
            raise ValueError("payroll target must be non-negative USD Money")
        noise = float(self.rng.normal(0.0, self.config.productivity_noise_std))
        factor = Fraction(1) + Fraction(str(noise))
        clamped = factor < 0
        factor = max(Fraction(0), factor)
        self.productivity *= factor
        if ctx.step == self.config.productivity_shock_step:
            self.productivity *= self.config.productivity_shock_multiplier
        cash_cap = int(self.firm.cash_balance.minor_units * self.config.payroll_cash_fraction)
        budget = Money(min(target.minor_units, max(0, cash_cap)))
        actions = EconomicActions(
            self.productivity,
            factor,
            clamped,
            self.firm.cash_balance,
            budget,
            budget < target,
        )
        self._action_step, self._last_actions = ctx.step, actions
        return actions

    def require_resolution(self, result: PriceSearchResult) -> None:
        if self.config.require_price_resolution and result.status == "iteration_limit":
            raise ValueError("price search evaluation limit reached before a tick bracket")

    def clear_and_settle(self, ctx: StepContext, actions: EconomicActions) -> EconomicSettlement:
        if (
            ctx.economy is not self.economy
            or ctx.step != self._action_step
            or ctx.step <= self._settled_step
            or actions is not self._last_actions
        ):
            raise ValueError("settlement requires this step's own unused economic actions")
        labor = discover_price(
            {
                self.firm.agent_id: BudgetDemand(
                    actions.payroll_budget, self.config.max_labor_demand
                )
            },
            {
                name: LinearSupply(
                    self.config.labor_reservation_wage,
                    Fraction(0),
                    self.config.labor_supply_slope,
                    self.config.household_labor_capacity,
                )
                for name in self.households
            },
            self.config.price_config("labor"),
            initial_price=self.wage,
        )
        self.require_resolution(labor)
        wages = settle_market(labor.allocation, "labor", self.firm, self.households, step=ctx.step)
        produced = wages.realized_quantity * actions.productivity
        available = self.inventory + produced
        wage_income = {payment.household_id: payment.paid.minor_units for payment in wages.payments}
        goods = discover_price(
            {
                name: BudgetDemand(
                    Money(
                        min(
                            int(wage_income[name] * self.config.consumption_propensity),
                            household.cash_balance.minor_units,
                        )
                    ),
                    self.config.household_goods_cap,
                )
                for name, household in self.households.items()
            },
            {
                self.firm.agent_id: LinearSupply(
                    self.config.goods_reservation_price,
                    Fraction(0),
                    self.config.goods_supply_slope,
                    available,
                )
            },
            self.config.price_config("goods"),
            initial_price=self.goods_price,
        )
        self.require_resolution(goods)
        sales = settle_market(goods.allocation, "goods", self.firm, self.households, step=ctx.step)
        new_inventory = available - sales.realized_quantity
        if new_inventory < 0:
            raise ValueError("physical inventory conservation violated")
        result = EconomicSettlement(
            labor, wages, goods, sales, self.inventory, produced, new_inventory
        )
        self.inventory = new_inventory
        self.cumulative_production += produced
        self.cumulative_sales += sales.realized_quantity
        self.wage, self.goods_price = (labor.allocation.price, goods.allocation.price)
        self._settled_step = ctx.step
        self._last_settlement = result
        return result

    def snapshot(self, result: StepResult) -> EconomyStep:
        if (
            self._last_actions is None
            or self._last_settlement is None
            or result.step != self._settled_step
            or result.actions is not self._last_actions
            or result.settlement is not self._last_settlement
        ):
            raise ValueError("economic snapshot must describe the current completed settlement")
        if result.state_hash != self.economy.ledger.snapshot(result.step).state_hash():
            raise ValueError("economic snapshot hash differs from the current ledger")
        cash = self.firm.cash_balance + sum(
            (hh.cash_balance for hh in self.households.values()), Money(0)
        )
        equity = self.firm.net_worth + sum(
            (hh.net_worth for hh in self.households.values()), Money(0)
        )
        if cash != self.injected or equity != self.injected:
            raise ValueError("aggregate cash/equity conservation violated")
        if self.firm.cash_balance.is_negative() or any(
            hh.cash_balance.is_negative() for hh in self.households.values()
        ):
            raise ValueError("cash feasibility violated")
        if (
            self.config.initial_inventory + self.cumulative_production
            != self.inventory + self.cumulative_sales
        ):
            raise ValueError("cumulative physical-goods conservation violated")
        return EconomyStep(
            result.step,
            result.step_date,
            result.actions,
            result.settlement,
            self.firm.cash_balance,
            tuple(((name, hh.cash_balance) for name, hh in self.households.items())),
            cash,
            equity,
            self.cumulative_production,
            self.cumulative_sales,
            result.state_hash,
        )
