"""EXT-07: "implement latency/failure handling and manual intervention"
/ "fault injection proves controlled shutdown and operator escalation."
`FaultInjector.attempt_with_fault` configures `mock_broker` to raise a
simulated fault, attempts an order, and -- on that fault -- trips the
kill switch (controlled shutdown) and writes a surveillance-log
escalation entry (operator escalation), literally, not as a metaphor.
"""

from __future__ import annotations

from dataclasses import dataclass

from prometheus.trading_readiness.kill_switch import KillSwitch
from prometheus.trading_readiness.mock_broker import BrokerFault, InMemoryMockBroker
from prometheus.trading_readiness.orders import Order
from prometheus.trading_readiness.surveillance_log import SurveillanceLog


@dataclass(frozen=True, slots=True)
class FaultInjector:
    broker: InMemoryMockBroker
    kill_switch: KillSwitch
    surveillance: SurveillanceLog

    def attempt_with_fault(
        self, order: Order, fault: BrokerFault, *, actor: str = "fault_injection"
    ) -> None:
        """Configures `fault` on the broker, attempts `order`, and
        responds to the resulting `BrokerFault` by tripping the kill
        switch and recording a surveillance-log escalation -- the
        fault is handled here, not re-raised: callers check
        `kill_switch.is_tripped`/`surveillance.entries` afterward
        rather than catching an exception."""
        self.broker.configure_fault(fault)
        try:
            self.broker.submit_order(order)
        except BrokerFault as exc:
            reason = f"broker fault during order submission: {exc}"
            self.kill_switch.trip(reason)
            self.surveillance.record(order, "rejected", reason, actor=actor)
