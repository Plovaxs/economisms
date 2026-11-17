from __future__ import annotations

import pytest

from prometheus.trading_readiness.kill_switch import KillSwitch, KillSwitchTrippedError


def test_a_fresh_kill_switch_defaults_to_not_tripped() -> None:
    switch = KillSwitch()
    assert not switch.is_tripped
    switch.check()  # does not raise


def test_tripping_sets_is_tripped_and_records_the_reason() -> None:
    switch = KillSwitch()
    switch.trip("simulated upstream timeout")
    assert switch.is_tripped
    assert switch.trips[0].reason == "simulated upstream timeout"


def test_check_raises_once_tripped() -> None:
    switch = KillSwitch()
    switch.trip("fault injected")
    with pytest.raises(KillSwitchTrippedError, match="fault injected"):
        switch.check()


def test_tripping_requires_a_non_empty_reason() -> None:
    switch = KillSwitch()
    with pytest.raises(ValueError, match="reason"):
        switch.trip("")


def test_re_tripping_is_idempotent_for_is_tripped_but_appends_to_history() -> None:
    switch = KillSwitch()
    switch.trip("first cause")
    switch.trip("second cause")
    assert switch.is_tripped
    assert [event.reason for event in switch.trips] == ["first cause", "second cause"]


def test_there_is_no_way_to_untrip_a_kill_switch() -> None:
    switch = KillSwitch()
    switch.trip("permanent")
    assert not hasattr(switch, "untrip")
    assert not hasattr(switch, "reset")
    assert not hasattr(switch, "clear")
    assert switch.is_tripped
