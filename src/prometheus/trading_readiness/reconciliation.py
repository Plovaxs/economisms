"""EXT-06: "implement real-time P&L, positions, and execution
reconciliation" / "independent broker statement and system positions
reconcile." "Independent broker statement" here means
`mock_broker.InMemoryMockBroker`'s own, independently-tracked
`AccountStatement` -- no real brokerage statement exists to reconcile
against.
"""

from __future__ import annotations

from dataclasses import dataclass

from prometheus.core.money import Money
from prometheus.trading_readiness.orders import AccountStatement


@dataclass(frozen=True, slots=True)
class PositionBreak:
    instrument: str
    system_quantity: int
    broker_quantity: int

    @property
    def delta(self) -> int:
        return self.system_quantity - self.broker_quantity


@dataclass(frozen=True, slots=True)
class CashBreak:
    system_cash: Money
    broker_cash: Money

    @property
    def delta(self) -> Money:
        return self.system_cash - self.broker_cash


@dataclass(frozen=True, slots=True)
class ReconciliationReport:
    position_breaks: tuple[PositionBreak, ...]
    cash_break: CashBreak | None

    @property
    def is_clean(self) -> bool:
        return not self.position_breaks and self.cash_break is None


def reconcile(system: AccountStatement, broker: AccountStatement) -> ReconciliationReport:
    instruments = sorted(
        {p.instrument for p in system.positions} | {p.instrument for p in broker.positions}
    )
    position_breaks = []
    for instrument in instruments:
        system_position = system.position_for(instrument)
        broker_position = broker.position_for(instrument)
        system_quantity = system_position.quantity if system_position is not None else 0
        broker_quantity = broker_position.quantity if broker_position is not None else 0
        if system_quantity != broker_quantity:
            position_breaks.append(PositionBreak(instrument, system_quantity, broker_quantity))
    cash_break = None if system.cash == broker.cash else CashBreak(system.cash, broker.cash)
    return ReconciliationReport(tuple(position_breaks), cash_break)
