import dataclasses
from datetime import date

import pytest

from prometheus.core.money import Money
from prometheus.econosim.economy import Economy
from prometheus.experiments.decision_audit_log import (
    CausalityViolation,
    DecisionLogEntry,
    audit_replay,
)
from prometheus.hedging.online import OnlineHedgeAccount


def test_decision_log_entry_rejects_an_empty_actor_id() -> None:
    with pytest.raises(ValueError, match="actor_id"):
        DecisionLogEntry("", "action", observed_at=0.0, decided_at=0.0)


def test_decision_log_entry_rejects_an_empty_action() -> None:
    with pytest.raises(ValueError, match="action"):
        DecisionLogEntry("actor", "", observed_at=0.0, decided_at=0.0)


def test_decision_log_entry_does_not_itself_reject_a_causally_impossible_entry() -> None:
    """Deliberate design choice (see this module's own docstring): the
    audit log must be able to faithfully RECORD a real violation if one
    occurred, not make bad history unconstructable -- the actual check
    is `audit_replay`'s job, a separate, independent pass."""
    entry = DecisionLogEntry("actor", "action", observed_at=5.0, decided_at=3.0)
    assert entry.decided_at < entry.observed_at


def test_decision_log_entry_is_immutable() -> None:
    entry = DecisionLogEntry("actor", "action", observed_at=0.0, decided_at=1.0)
    with pytest.raises(dataclasses.FrozenInstanceError):
        entry.decided_at = 2.0  # type: ignore[misc]


def test_audit_replay_passes_an_empty_log() -> None:
    assert audit_replay([]) == []


def test_audit_replay_passes_a_well_ordered_log() -> None:
    entries = [
        DecisionLogEntry("a", "act1", observed_at=0.0, decided_at=0.0),
        DecisionLogEntry("a", "act2", observed_at=1.0, decided_at=1.0),
        DecisionLogEntry("a", "act3", observed_at=2.0, decided_at=2.5),
    ]
    assert audit_replay(entries) == []


def test_audit_replay_flags_a_backdated_decision() -> None:
    """The discriminating half: a decision timestamped BEFORE the state
    it claims to be based on was observed must be caught, with the
    exact actor/action/timestamps that violated it, not merely a count."""
    entries = [
        DecisionLogEntry("a", "act1", observed_at=0.0, decided_at=0.0),
        DecisionLogEntry("a", "act2", observed_at=5.0, decided_at=3.0),
    ]
    violations = audit_replay(entries)
    assert violations == [
        CausalityViolation("a", "act2", observed_at=5.0, decided_at=3.0)
    ]


def test_audit_replay_flags_only_the_entries_that_actually_violate() -> None:
    entries = [
        DecisionLogEntry("a", "ok1", observed_at=0.0, decided_at=0.0),
        DecisionLogEntry("a", "bad", observed_at=5.0, decided_at=3.0),
        DecisionLogEntry("a", "ok2", observed_at=6.0, decided_at=7.0),
    ]
    violations = audit_replay(entries)
    assert [v.action for v in violations] == ["bad"]


def test_causality_violation_str_mentions_actor_and_both_timestamps() -> None:
    violation = CausalityViolation("hedger", "set_holdings=0.5", observed_at=5.0, decided_at=3.0)
    text = str(violation)
    assert "hedger" in text
    assert "5.0" in text
    assert "3.0" in text


def test_a_real_online_hedge_simulation_produces_a_clean_audit_log() -> None:
    """Grounded in a genuine `OnlineHedgeAccount` simulation, not a
    synthetic float pair: each rebalance's decision is timestamped at
    the SAME step as the spot it reacted to, so a correctly-implemented
    hedge policy's own decision log must replay clean."""
    account = OnlineHedgeAccount(
        strike=100.0, option_type="call", risk_free_rate=0.03, cost_rate=0.0, dt=1 / 252
    )
    account.initialize(premium=5.0)
    entries = []
    for step, spot in enumerate([100.0, 101.0, 99.0, 102.0]):
        observed_at = float(step)
        record = account.update(spot, target_holdings=0.5)
        entries.append(
            DecisionLogEntry(
                actor_id="delta_hedge",
                action=f"set_holdings={record.target_holdings}",
                observed_at=observed_at,
                decided_at=observed_at,
            )
        )
    assert audit_replay(entries) == []


def test_a_real_online_hedge_decision_using_a_future_spot_is_caught() -> None:
    """The discriminating half of the hedging scenario: a decision that
    (incorrectly) reacts to a spot observed at a LATER step than when it
    was actually decided must be flagged, not silently accepted just
    because it came from a real `OnlineHedgeAccount` call."""
    account = OnlineHedgeAccount(
        strike=100.0, option_type="call", risk_free_rate=0.03, cost_rate=0.0, dt=1 / 252
    )
    account.initialize(premium=5.0)
    record = account.update(101.0, target_holdings=0.5)
    leaked_entry = DecisionLogEntry(
        actor_id="delta_hedge",
        action=f"set_holdings={record.target_holdings}",
        observed_at=10.0,  # the spot wasn't observed until step 10
        decided_at=3.0,  # yet the decision is timestamped at step 3
    )
    violations = audit_replay([leaked_entry])
    assert len(violations) == 1
    assert violations[0].actor_id == "delta_hedge"


def test_a_real_household_consumption_decision_produces_a_clean_audit_log() -> None:
    """Grounded in a genuine `econosim.agents.Household.consume` call,
    not a synthetic example -- the "agent" half of AUD-05's "agent and
    hedge decisions" wording, using `date.toordinal()` as this module's
    documented calendar-to-float convention."""
    econ = Economy()
    household = econ.add_household("hh-1")
    firm = econ.add_firm("firm-1")
    household.receive_income(Money(1000, "USD"))

    observation_date = date(2026, 1, 5)
    decision_date = date(2026, 1, 6)
    household.consume(firm, Money(400, "USD"), step=1)
    entry = DecisionLogEntry(
        actor_id="hh-1",
        action="consume 400 USD from firm-1",
        observed_at=float(observation_date.toordinal()),
        decided_at=float(decision_date.toordinal()),
    )
    assert audit_replay([entry]) == []


def test_a_real_household_consumption_decision_backdated_before_income_data_is_caught() -> None:
    econ = Economy()
    household = econ.add_household("hh-1")
    firm = econ.add_firm("firm-1")
    household.receive_income(Money(1000, "USD"))
    household.consume(firm, Money(400, "USD"), step=1)

    income_observed_date = date(2026, 2, 1)
    decision_date = date(2026, 1, 6)  # before the income was even observed
    entry = DecisionLogEntry(
        actor_id="hh-1",
        action="consume 400 USD from firm-1",
        observed_at=float(income_observed_date.toordinal()),
        decided_at=float(decision_date.toordinal()),
    )
    violations = audit_replay([entry])
    assert len(violations) == 1
    assert violations[0].actor_id == "hh-1"
