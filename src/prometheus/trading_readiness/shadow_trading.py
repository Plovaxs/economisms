"""EXT-10: "conduct paper/shadow trading over institution-approved
period" / "live-like environment with no actual order placement."
`ShadowTradingSession.run` runs a sequence of orders through
`risk_gate` and `mock_broker` only -- by construction (confirmed by
`mock_broker.py`'s own test, that `InMemoryMockBroker` is the only
`BrokerAdapter` anywhere in this repository's import graph), zero real
order placement can occur. "Institution-approved period" is not met --
there is no institution to approve one.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from prometheus.core.money import Money
from prometheus.trading_readiness.mock_broker import InMemoryMockBroker
from prometheus.trading_readiness.orders import Fill, Order
from prometheus.trading_readiness.risk_gate import PreTradeRiskGate


@dataclass(frozen=True, slots=True)
class ShadowTradingSession:
    risk_gate: PreTradeRiskGate
    broker: InMemoryMockBroker

    def run(
        self, orders: Sequence[Order], *, reference_prices: dict[str, Money] | None = None
    ) -> tuple[Fill, ...]:
        """Every order is risk-checked against the broker's own current
        book before it is ever submitted -- a risk-gate rejection stops
        that order (raising, same as `PreTradeRiskGate.check` itself)
        rather than silently skipping it."""
        prices = reference_prices or {}
        fills: list[Fill] = []
        for order in orders:
            book = self.broker.account_statement().position_for(order.instrument)
            reference_price = prices.get(order.instrument)
            self.risk_gate.check(order, book, reference_price=reference_price)
            fills.append(self.broker.submit_order(order, reference_price=reference_price))
        return tuple(fills)
