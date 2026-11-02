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
