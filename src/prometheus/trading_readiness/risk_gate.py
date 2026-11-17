"""EXT-04: "define pre-trade credit, position and erroneous-order
controls" / "independent tests verify limits before an order is sent."
`PreTradeRiskGate.check` runs before `mock_broker` ever sees an order --
nothing in this package submits an order without going through this
gate first (see `shadow_trading.py`).
"""

from __future__ import annotations

from dataclasses import dataclass

from prometheus.core.money import Money
from prometheus.trading_readiness.orders import Order, Position


class RiskLimitViolation(ValueError):
    """Raised by `PreTradeRiskGate.check` naming every limit an order
    breaches, not just the first one found."""


@dataclass(frozen=True, slots=True)
class RiskLimits:
    max_order_quantity: int
    """An erroneous-order ("fat-finger") bound on a single order's own
    size, independent of price or existing position."""
    max_order_notional: Money
    """A credit bound on a single order's notional value."""
    max_position_quantity: int
    """A position bound on the resulting |quantity| after this order
    fills, independent of any other order."""

    def __post_init__(self) -> None:
        if self.max_order_quantity <= 0:
            raise ValueError("max_order_quantity must be positive")
        if self.max_order_notional.minor_units <= 0:
            raise ValueError("max_order_notional must be positive")
        if self.max_position_quantity <= 0:
            raise ValueError("max_position_quantity must be positive")


@dataclass(frozen=True, slots=True)
class PreTradeRiskGate:
    limits: RiskLimits

    def check(
        self, order: Order, book: Position | None, *, reference_price: Money | None = None
    ) -> None:
        violations: list[str] = []

        if order.quantity > self.limits.max_order_quantity:
            violations.append(
                f"order quantity {order.quantity} exceeds max_order_quantity "
                f"{self.limits.max_order_quantity}"
            )

        price = order.limit_price if order.limit_price is not None else reference_price
        if price is None:
            raise ValueError(
                "a market order needs an explicit reference_price to check its notional"
            )
        notional = price * order.quantity
        if notional.minor_units > self.limits.max_order_notional.minor_units:
            violations.append(
                f"order notional {notional} exceeds max_order_notional "
                f"{self.limits.max_order_notional}"
            )

        current_quantity = book.quantity if book is not None else 0
        signed_delta = order.quantity if order.side == "buy" else -order.quantity
        resulting_quantity = current_quantity + signed_delta
        if abs(resulting_quantity) > self.limits.max_position_quantity:
            violations.append(
                f"resulting position {resulting_quantity} would exceed "
                f"max_position_quantity {self.limits.max_position_quantity}"
            )

        if violations:
            raise RiskLimitViolation("; ".join(violations))
