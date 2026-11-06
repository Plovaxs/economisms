import math
from datetime import date

import numpy as np
import pytest

from prometheus.hedging.online import OnlineHedgeAccount
from prometheus.hedging.rate_paths import rate_scheduled_delta, rate_scheduled_gbm
from prometheus.hedging.simulate import simulate_self_financing_hedge
from prometheus.volterra.black_scholes import black_scholes_greeks
from prometheus.volterra.instruments import EuropeanOption
from prometheus.volterra.market import MarketSnapshot


@pytest.mark.parametrize("option_type", ["call", "put"])
def test_changing_funding_rates_match_independent_cash_and_online_accounts(option_type):
    paths = np.array([[100.0, 105.0, 90.0, 115.0], [100.0, 95.0, 110.0, 85.0]])
    targets = np.array([[0.5, 0.6, 0.3], [0.4, 0.2, 0.7]])
    if option_type == "put":
        targets -= 1
    rates = np.array([[0.01, 0.08, -0.03], [0.02, -0.01, 0.15]])
    result = simulate_self_financing_hedge(
        paths, 1 / 12, 100.0, option_type, 99.0, 0.01, 8.0, targets, funding_rates=rates
    )
    for i in range(2):
        account = OnlineHedgeAccount(100.0, option_type, 0.0, 0.01, 1 / 12)
        account.initialize(8.0)
        cash, holdings, cost = 8.0, 0.0, 0.0
        for t in range(3):
            trade = targets[i, t] - holdings
            fee = 0.01 * abs(trade) * paths[i, t]
            cash = (cash - trade * paths[i, t] - fee) * math.exp(rates[i, t] / 12)
            cost += fee
            holdings = targets[i, t]
            account.rebalance(paths[i, t], holdings)
            account.accrue(rates[i, t])
        payoff = max((paths[i, -1] - 100.0) * (1 if option_type == "call" else -1), 0.0)
        manual_loss = -(cash + holdings * paths[i, -1] - payoff)
        assert result.terminal_loss[i] == pytest.approx(manual_loss, abs=1e-12)
        assert result.terminal_loss[i] == pytest.approx(-account.liquidate(paths[i, -1]))
        assert result.total_cost[i] == pytest.approx(cost)


def test_interval_schedule_matches_constant_rate_exactly():
    paths = np.array([[100.0, 101.0, 99.0], [100.0, 98.0, 102.0]])
    targets = np.array([[0.5, 0.6], [0.5, 0.4]])
    constant = simulate_self_financing_hedge(paths, 0.5, 100.0, "call", 0.03, 0.01, 8.0, targets)
    scheduled = simulate_self_financing_hedge(
        paths, 0.5, 100.0, "call", 0.03, 0.01, 8.0, targets, funding_rates=np.full(2, 0.03)
    )
    assert np.array_equal(constant.terminal_loss, scheduled.terminal_loss)


@pytest.mark.parametrize(
    "rates",
    [
        np.zeros(3),
        np.zeros((2, 3)),
        np.zeros((1, 2)),
        np.array([0.0, np.nan]),
        np.array([0.0, np.inf]),
    ],
)
def test_invalid_funding_schedule_is_rejected(rates):
    with pytest.raises(ValueError, match="funding_rates"):
        simulate_self_financing_hedge(
            np.ones((2, 3)), 0.5, 1.0, "call", 0.03, 0.0, 1.0, np.zeros((2, 2)), funding_rates=rates
        )


def test_gbm_uses_opening_rate_and_delta_only_current_rate():
    rates = np.array([0.03, 0.12, -0.01, 0.08])
    z = np.array([[0.3, -0.5, 0.2], [-0.2, 0.4, -0.6]])
    paths = rate_scheduled_gbm(100.0, 0.04, 0.2, 1 / 12, rates, z)
    for i in range(2):
        expected = 100.0
        for t in range(3):
            expected *= math.exp(
                (rates[t] + 0.04 - 0.5 * 0.2**2) / 12 + 0.2 * math.sqrt(1 / 12) * z[i, t]
            )
            assert paths[i, t + 1] == pytest.approx(expected)
    targets = rate_scheduled_delta(paths, 1 / 12, 100.0, 0.2, "call", rates)
    for i in range(2):
        for t in range(3):
            scalar = black_scholes_greeks(
                MarketSnapshot(date(2026, 1, 2), paths[i, t], rates[t], 0.2),
                EuropeanOption(100.0, (3 - t) / 12, "call"),
            )
            assert targets[i, t] == pytest.approx(scalar.delta)
    changed = rates.copy()
    changed[2:] = [0.5, -0.2]
    other = rate_scheduled_gbm(100.0, 0.04, 0.2, 1 / 12, changed, z)
    assert np.array_equal(paths[:, :3], other[:, :3])
    other_targets = rate_scheduled_delta(other, 1 / 12, 100.0, 0.2, "call", changed)
    assert np.array_equal(targets[:, :2], other_targets[:, :2])
    # A closing decision at expiry cannot alter any completed market interval or target.
    expiry_only = rates.copy()
    expiry_only[-1] = 0.9
    assert np.array_equal(paths, rate_scheduled_gbm(100.0, 0.04, 0.2, 1 / 12, expiry_only, z))
    assert np.array_equal(
        targets, rate_scheduled_delta(paths, 1 / 12, 100.0, 0.2, "call", expiry_only)
    )


@pytest.mark.parametrize(
    "rates,z",
    [
        (np.zeros(1), np.zeros((2, 0))),
        (np.array([0.03, np.nan]), np.zeros((2, 1))),
        (np.zeros(3), np.zeros((2, 1))),
        (np.zeros(3), np.full((2, 2), np.inf)),
        (np.zeros(3), np.zeros((0, 2))),
    ],
)
def test_invalid_rate_bank_inputs_are_rejected(rates, z):
    with pytest.raises(ValueError):
        rate_scheduled_gbm(100.0, 0.04, 0.2, 1 / 12, rates, z)
