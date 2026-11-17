from __future__ import annotations

from datetime import date

import pytest

from prometheus.core.money import Money
from prometheus.trading_readiness.fault_injection import FaultInjector
from prometheus.trading_readiness.kill_switch import KillSwitch
from prometheus.trading_readiness.mock_broker import BrokerFault, InMemoryMockBroker
from prometheus.trading_readiness.orders import Order
from prometheus.trading_readiness.surveillance_log import SurveillanceLog

_ORDER = Order("AAPL", "buy", 10, "limit", limit_price=Money(10_000))


def _injector() -> tuple[FaultInjector, KillSwitch, SurveillanceLog]:
    kill_switch = KillSwitch()
    surveillance = SurveillanceLog(retention_until=date(2030, 1, 1))
    injector = FaultInjector(InMemoryMockBroker(cash=Money(1_000_000)), kill_switch, surveillance)
    return injector, kill_switch, surveillance


@pytest.mark.parametrize(
    "fault_description",
    ["simulated timeout", "simulated disconnect", "simulated erroneous fill"],
)
def test_each_fault_kind_trips_the_kill_switch(fault_description: str) -> None:
    injector, kill_switch, _ = _injector()
    injector.attempt_with_fault(_ORDER, BrokerFault(fault_description))
    assert kill_switch.is_tripped
    assert fault_description in kill_switch.trips[0].reason


def test_each_fault_kind_writes_a_surveillance_escalation() -> None:
    injector, _, surveillance = _injector()
    injector.attempt_with_fault(_ORDER, BrokerFault("simulated timeout"))
    assert len(surveillance.entries) == 1
    entry = surveillance.entries[0]
    assert entry.decision == "rejected"
    assert "simulated timeout" in entry.reason
    assert entry.actor == "fault_injection"


def test_the_fault_is_handled_not_propagated_to_the_caller() -> None:
    injector, _, _ = _injector()
    injector.attempt_with_fault(_ORDER, BrokerFault("simulated timeout"))  # does not raise


def test_a_clean_order_with_no_fault_configured_does_not_trip_anything() -> None:
    kill_switch = KillSwitch()
    surveillance = SurveillanceLog(retention_until=date(2030, 1, 1))
    broker = InMemoryMockBroker(cash=Money(1_000_000))
    broker.submit_order(_ORDER)
    assert not kill_switch.is_tripped
    assert surveillance.entries == ()
