"""`BrokerAdapter` -- the one connectivity "contract" this package
defines (EXT-03: "define broker/exchange connectivity") -- and
`InMemoryMockBroker`, deliberately the ONLY implementation that exists
anywhere in this repository's import graph (enforced by
`charter_guard.py`'s own test, not just claimed here). Entirely
in-process, in-memory, makes no network call of any kind, and supports
no real broker/exchange protocol -- it exists solely so the rest of
this package's mechanisms (`risk_gate`, `kill_switch`, `reconciliation`,
`fault_injection`, `shadow_trading`) have something real to run
against and be tested with.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Protocol

from prometheus.core.money import Money
from prometheus.trading_readiness.orders import AccountStatement, Fill, Order, Position


class BrokerAdapter(Protocol):
    def submit_order(self, order: Order, *, reference_price: Money | None = None) -> Fill: ...
    def positions(self) -> tuple[Position, ...]: ...
    def account_statement(self) -> AccountStatement: ...


class BrokerFault(ValueError):
    """Raised by `InMemoryMockBroker.submit_order` when configured (via
    `configure_fault`) to simulate a failure -- `fault_injection.py`'s
    one real use of this, never raised on its own."""


@dataclass(slots=True)
class InMemoryMockBroker:
    cash: Money
    _positions: dict[str, Position] = field(default_factory=dict, init=False)
    _fault: BrokerFault | None = field(default=None, init=False)
    _clock: Callable[[], datetime] = field(default=lambda: datetime.now(UTC), init=False)

    def configure_fault(self, fault: BrokerFault | None) -> None:
        """The only way `submit_order` ever raises `BrokerFault` --
        `fault_injection.py`'s sole call site for this."""
        self._fault = fault

    def submit_order(self, order: Order, *, reference_price: Money | None = None) -> Fill:
        if self._fault is not None:
            raise self._fault
        fill_price = order.limit_price if order.limit_price is not None else reference_price
        if fill_price is None:
            raise ValueError(
                "a market order requires an explicit reference_price -- this mock never invents one"
            )
        fill = Fill(
            order=order, fill_price=fill_price, fill_quantity=order.quantity, at=self._clock()
        )
        self._apply_fill(fill)
        return fill

    def positions(self) -> tuple[Position, ...]:
        return tuple(self._positions.values())

    def account_statement(self) -> AccountStatement:
        return AccountStatement(positions=self.positions(), cash=self.cash, as_of=self._clock())

    def _apply_fill(self, fill: Fill) -> None:
        order = fill.order
        signed_delta = fill.fill_quantity if order.side == "buy" else -fill.fill_quantity
        existing = self._positions.get(order.instrument)
        if existing is None:
            new_quantity, new_average_price = signed_delta, fill.fill_price
        else:
            new_quantity = existing.quantity + signed_delta
            same_direction = (existing.quantity >= 0 and signed_delta >= 0) or (
                existing.quantity <= 0 and signed_delta <= 0
            )
            if new_quantity == 0:
                new_average_price = Money(0, fill.fill_price.currency)
            elif same_direction:
                # Opening or adding to a position: exact weighted-average cost.
                total_cost = existing.average_price.minor_units * abs(
                    existing.quantity
                ) + fill.fill_price.minor_units * abs(signed_delta)
                new_average_price = Money(total_cost // abs(new_quantity), fill.fill_price.currency)
            elif abs(signed_delta) < abs(existing.quantity):
                # Partially closing: the remaining shares' cost basis is unchanged.
                new_average_price = existing.average_price
            else:
                # Reversed through zero in one fill: a disclosed simplification,
                # not precise per-lot accounting -- the new position's basis is
                # this fill's own price, not a split of the crossing fill.
                new_average_price = fill.fill_price
        self._positions[order.instrument] = Position(
            order.instrument, new_quantity, new_average_price
        )
        cash_delta = fill.notional if order.side == "sell" else -fill.notional
        self.cash = self.cash + cash_delta
