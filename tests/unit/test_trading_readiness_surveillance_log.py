from __future__ import annotations

from datetime import date

import pytest

from prometheus.core.money import Money
from prometheus.trading_readiness.orders import Order
from prometheus.trading_readiness.surveillance_log import SurveillanceLog

_ORDER = Order("AAPL", "buy", 10, "limit", limit_price=Money(10_000))


def test_retention_until_is_required_at_construction() -> None:
    with pytest.raises(TypeError):
        SurveillanceLog()  # type: ignore[call-arg]


def test_an_accepted_attempt_is_recorded() -> None:
    log = SurveillanceLog(retention_until=date(2030, 1, 1))
    log.record(_ORDER, "accepted", "within all limits", actor="risk_gate")
    assert log.entries[0].decision == "accepted"


def test_a_rejected_attempt_is_also_recorded() -> None:
    log = SurveillanceLog(retention_until=date(2030, 1, 1))
    log.record(_ORDER, "rejected", "exceeds max_order_quantity", actor="risk_gate")
    assert log.entries[0].decision == "rejected"
    assert log.entries[0].reason == "exceeds max_order_quantity"


def test_every_attempt_is_recorded_in_order() -> None:
    log = SurveillanceLog(retention_until=date(2030, 1, 1))
    log.record(_ORDER, "accepted", "ok", actor="a")
    log.record(_ORDER, "rejected", "blocked", actor="b")
    log.record(_ORDER, "accepted", "ok again", actor="c")
    assert [e.decision for e in log.entries] == ["accepted", "rejected", "accepted"]


def test_an_entry_requires_a_non_empty_reason_and_actor() -> None:
    log = SurveillanceLog(retention_until=date(2030, 1, 1))
    with pytest.raises(ValueError, match="reason"):
        log.record(_ORDER, "accepted", "", actor="a")
    with pytest.raises(ValueError, match="actor"):
        log.record(_ORDER, "accepted", "ok", actor="")


def test_the_log_has_no_mutate_or_delete_method() -> None:
    log = SurveillanceLog(retention_until=date(2030, 1, 1))
    log.record(_ORDER, "accepted", "ok", actor="a")
    assert not hasattr(log, "delete")
    assert not hasattr(log, "clear")
    assert not hasattr(log, "remove")
    assert not hasattr(log, "update")
    assert len(log.entries) == 1
