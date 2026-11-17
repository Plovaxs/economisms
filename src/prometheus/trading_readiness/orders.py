"""Order/Fill/Position/AccountStatement -- the shared vocabulary every
other module in this package is built on. Prices are `core.money.Money`
(reused unchanged, not reinvented): "a price per unit" is itself a
monetary amount, and `Money.__mul__`'s existing integer-scalar
multiplication gives exact notional-value arithmetic
(`fill_price * fill_quantity`) for free, with the same no-float-drift
discipline LED-02 already establishes for the ledger.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal, get_args

from prometheus.core.money import Money

Side = Literal["buy", "sell"]
OrderType = Literal["market", "limit"]
_SIDES = frozenset(get_args(Side))
_ORDER_TYPES = frozenset(get_args(OrderType))


def _require_positive_int(value: object, name: str) -> None:
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise ValueError(f"{name} must be a positive int, got {value!r}")


@dataclass(frozen=True, slots=True)
class Order:
    instrument: str
    side: Side
    quantity: int
    order_type: OrderType
    limit_price: Money | None = None

    def __post_init__(self) -> None:
        if not self.instrument:
            raise ValueError("instrument must not be empty")
        if self.side not in _SIDES:
            raise ValueError(f"side must be one of {sorted(_SIDES)}, got {self.side!r}")
        if self.order_type not in _ORDER_TYPES:
            raise ValueError(
                f"order_type must be one of {sorted(_ORDER_TYPES)}, got {self.order_type!r}"
            )
        _require_positive_int(self.quantity, "quantity")
        if self.order_type == "limit" and self.limit_price is None:
            raise ValueError("a limit order requires a limit_price")
        if self.order_type == "market" and self.limit_price is not None:
            raise ValueError("a market order must not carry a limit_price")
        if self.limit_price is not None and self.limit_price.minor_units <= 0:
            raise ValueError("limit_price must be positive")

    @property
    def notional(self) -> Money:
        """The order's notional value at its own limit price. Raises for
        a market order, which has no price to compute one from until it
        fills -- callers needing a pre-trade notional estimate for a
        market order must supply a reference price themselves (see
        `risk_gate.PreTradeRiskGate`, which takes one explicitly rather
        than guessing)."""
        if self.limit_price is None:
            raise ValueError("a market order has no price to compute notional from")
        return self.limit_price * self.quantity


@dataclass(frozen=True, slots=True)
class Fill:
    order: Order
    fill_price: Money
    fill_quantity: int
    at: datetime

    def __post_init__(self) -> None:
        if self.fill_price.minor_units <= 0:
            raise ValueError("fill_price must be positive")
        _require_positive_int(self.fill_quantity, "fill_quantity")
        if self.fill_quantity > self.order.quantity:
            raise ValueError(
                f"fill_quantity ({self.fill_quantity}) cannot exceed the order's "
                f"quantity ({self.order.quantity})"
            )

    @property
    def notional(self) -> Money:
        return self.fill_price * self.fill_quantity


@dataclass(frozen=True, slots=True)
class Position:
    instrument: str
    quantity: int
    """Signed: positive is long, negative is short, zero is flat -- no
    positivity constraint, unlike Order.quantity's magnitude-only sign."""
    average_price: Money

    def __post_init__(self) -> None:
        if not self.instrument:
            raise ValueError("instrument must not be empty")
        if not isinstance(self.quantity, int) or isinstance(self.quantity, bool):
            raise ValueError(f"quantity must be an int, got {self.quantity!r}")
        if self.average_price.minor_units < 0:
            raise ValueError("average_price must not be negative")


@dataclass(frozen=True, slots=True)
class AccountStatement:
    positions: tuple[Position, ...]
    cash: Money
    as_of: datetime

    def __post_init__(self) -> None:
        instruments = [p.instrument for p in self.positions]
        if len(instruments) != len(set(instruments)):
            raise ValueError("positions must not repeat the same instrument")

    def position_for(self, instrument: str) -> Position | None:
        for position in self.positions:
            if position.instrument == instrument:
                return position
        return None
