import pytest

from prometheus.econosim.economy import Economy
from prometheus.econosim.policy_rate import PolicyRateRule
from prometheus.econosim.shocks import Shock


def test_economy_add_central_bank_tracks_it_by_id() -> None:
    econ = Economy()
    rule = PolicyRateRule(neutral_rate=0.03, mean_reversion_speed=0.5, dt=1 / 12)
    central_bank = econ.add_central_bank("fed", rule, initial_rate=0.03)
    assert econ.central_banks["fed"] is central_bank
    assert central_bank.current_rate == 0.03


def test_step_matches_the_same_closed_form_as_the_free_function() -> None:
    """CentralBank.step must behave identically to
    policy_rate.simulate_policy_rate_path's underlying recursion -- it is a
    thin stateful wrapper, not a separate implementation."""
    kappa, dt, neutral, r0 = 0.5, 1 / 12, 0.03, 0.08
    rule = PolicyRateRule(neutral_rate=neutral, mean_reversion_speed=kappa, dt=dt)
    econ = Economy()
    central_bank = econ.add_central_bank("fed", rule, initial_rate=r0)

    for t in range(1, 13):
        central_bank.step([])
        expected = neutral + (r0 - neutral) * (1 - kappa * dt) ** t
        assert central_bank.current_rate == pytest.approx(expected, abs=1e-12)


def test_step_applies_policy_rate_shocks() -> None:
    rule = PolicyRateRule(neutral_rate=0.03, mean_reversion_speed=0.5, dt=1 / 12)
    econ = Economy()
    central_bank = econ.add_central_bank("fed", rule, initial_rate=0.03)
    shock = Shock("s1", 1, "policy_rate", magnitude=0.02)

    new_rate = central_bank.step([shock])
    assert new_rate == pytest.approx(0.05)
    assert central_bank.current_rate == pytest.approx(0.05)


def test_economy_add_central_bank_ledger_tracks_it_by_id_and_opens_a_real_balance_sheet() -> None:
    """Unlike add_central_bank (a bare rate wrapper), add_central_bank_ledger
    constructs a ledger-backed agent whose accounts actually exist on the
    shared Economy ledger."""
    econ = Economy()
    central_bank_ledger = econ.add_central_bank_ledger("cb")
    assert econ.central_bank_ledgers["cb"] is central_bank_ledger
    assert econ.ledger.account(central_bank_ledger.securities_holdings_account) is not None
    assert central_bank_ledger.securities_holdings.is_zero()


def test_economy_can_hold_both_central_bank_kinds_under_different_ids() -> None:
    econ = Economy()
    rule = PolicyRateRule(neutral_rate=0.03, mean_reversion_speed=0.5, dt=1 / 12)
    rate_only = econ.add_central_bank("fed", rule, initial_rate=0.03)
    ledger_backed = econ.add_central_bank_ledger("fed_balance_sheet")
    assert econ.central_banks["fed"] is rate_only
    assert econ.central_bank_ledgers["fed_balance_sheet"] is ledger_backed
    assert rate_only.agent_id != ledger_backed.agent_id


def test_economy_can_build_a_single_unified_central_bank_via_add_central_bank_ledger() -> None:
    """add_central_bank_ledger's rate_rule/initial_rate kwargs, exercised
    through the Economy factory method itself (PR-041), not just by
    constructing CentralBankLedger directly."""
    econ = Economy()
    rule = PolicyRateRule(neutral_rate=0.03, mean_reversion_speed=0.5, dt=1 / 12)
    unified = econ.add_central_bank_ledger("cb", rate_rule=rule, initial_rate=0.04)
    assert econ.central_bank_ledgers["cb"] is unified
    assert unified.tracks_policy_rate is True
    assert unified.current_rate == 0.04
    assert unified.step_rate([]) == pytest.approx(rule.step(0.04, []))
