import pytest

from prometheus.econosim.policy_rate import PolicyRateRule, simulate_policy_rate_path
from prometheus.econosim.shocks import Shock


def test_rejects_negative_mean_reversion_speed() -> None:
    with pytest.raises(ValueError):
        PolicyRateRule(neutral_rate=0.03, mean_reversion_speed=-0.1, dt=1 / 12)


def test_rejects_non_positive_dt() -> None:
    with pytest.raises(ValueError):
        PolicyRateRule(neutral_rate=0.03, mean_reversion_speed=0.5, dt=0.0)


def test_matches_exact_discrete_ou_closed_form_with_zero_shocks() -> None:
    """ECO-05: a known reaction-function scenario should reproduce its
    coefficients exactly. With no shocks, r_t = neutral + (r_0 - neutral) *
    (1 - kappa*dt)^t is the exact closed form for this Euler-discretized
    mean-reverting recursion."""
    kappa, dt, neutral, r0 = 0.5, 1 / 12, 0.03, 0.08
    rule = PolicyRateRule(neutral_rate=neutral, mean_reversion_speed=kappa, dt=dt)
    schedule: list[list[Shock]] = [[] for _ in range(24)]
    rates = simulate_policy_rate_path(rule, r0, schedule)

    closed_form = [neutral + (r0 - neutral) * (1 - kappa * dt) ** t for t in range(25)]
    for simulated, exact in zip(rates, closed_form, strict=True):
        assert simulated == pytest.approx(exact, abs=1e-12)


def test_path_length_matches_schedule_length_plus_one() -> None:
    rule = PolicyRateRule(neutral_rate=0.03, mean_reversion_speed=0.5, dt=1 / 12)
    rates = simulate_policy_rate_path(rule, 0.05, [[], [], []])
    assert len(rates) == 4


def test_policy_rate_shock_adds_exactly_its_magnitude_before_next_reversion() -> None:
    kappa, dt, neutral = 0.5, 1 / 12, 0.03
    rule = PolicyRateRule(neutral_rate=neutral, mean_reversion_speed=kappa, dt=dt)
    shock = Shock(shock_id="s1", step=2, kind="policy_rate", magnitude=0.01)
    rates = simulate_policy_rate_path(rule, neutral, [[], [shock], []])

    # starting exactly at the neutral rate, reversion contributes nothing
    # until a shock perturbs it away:
    assert rates[0] == neutral
    assert rates[1] == pytest.approx(neutral)  # no shock, already at neutral
    assert rates[2] == pytest.approx(neutral + shock.magnitude)
    expected_after_reversion = rates[2] + kappa * (neutral - rates[2]) * dt
    assert rates[3] == pytest.approx(expected_after_reversion)


def test_non_policy_rate_shocks_are_ignored() -> None:
    rule = PolicyRateRule(neutral_rate=0.03, mean_reversion_speed=0.5, dt=1 / 12)
    productivity_shock = Shock("s1", 1, "productivity", magnitude=5.0)
    rates_with_irrelevant_shock = simulate_policy_rate_path(rule, 0.03, [[productivity_shock]])
    rates_without = simulate_policy_rate_path(rule, 0.03, [[]])
    assert rates_with_irrelevant_shock == rates_without
