import numpy as np
import pytest

from prometheus.hedging.baseline import black_scholes_delta_hedge_ratios
from prometheus.hedging.online import OnlineHedgeAccount
from prometheus.hedging.simulate import simulate_self_financing_hedge
from prometheus.stochastica.gbm import simulate_gbm_paths

STRIKE, MATURITY, R, SIGMA, S0 = 100.0, 1.0, 0.05, 0.2, 100.0
N_STEPS = 12
DT = MATURITY / N_STEPS
COST_RATE = 0.005
PREMIUM = 10.0


def test_update_before_initialize_raises() -> None:
    account = OnlineHedgeAccount(STRIKE, "call", R, COST_RATE, DT)
    with pytest.raises(RuntimeError):
        account.update(100.0, 0.5)


def test_liquidate_before_initialize_raises() -> None:
    account = OnlineHedgeAccount(STRIKE, "call", R, COST_RATE, DT)
    with pytest.raises(RuntimeError):
        account.liquidate(100.0)


def test_double_initialize_raises() -> None:
    account = OnlineHedgeAccount(STRIKE, "call", R, COST_RATE, DT)
    account.initialize(PREMIUM)
    with pytest.raises(RuntimeError):
        account.initialize(PREMIUM)


def test_zero_hedge_matches_naked_short_closed_form() -> None:
    """Reuses the same exact closed-form check as
    test_hedging_simulate.py::test_zero_hedge_ratios_reduce_to_a_naked_short_option_position,
    on the online account instead of the batch simulator."""
    account = OnlineHedgeAccount(STRIKE, "call", R, 0.0, DT)
    account.initialize(PREMIUM)
    for _ in range(N_STEPS):
        account.update(100.0, 0.0)  # holdings always zero, no trading
    spot_terminal = 123.45
    final_wealth = account.liquidate(spot_terminal)

    expected = PREMIUM * np.exp(R * MATURITY) - max(spot_terminal - STRIKE, 0.0)
    assert final_wealth == pytest.approx(expected)


@pytest.mark.parametrize("seed", [1, 2, 3])
@pytest.mark.parametrize("option_type", ["call", "put"])
def test_matches_batch_simulator_exactly_path_by_path(seed: int, option_type: str) -> None:
    rng = np.random.default_rng(seed)
    paths = simulate_gbm_paths(S0, R, SIGMA, MATURITY, N_STEPS, 10, rng)
    ratios = black_scholes_delta_hedge_ratios(paths, DT, STRIKE, MATURITY, R, SIGMA, option_type)  # type: ignore[arg-type]
    batch_result = simulate_self_financing_hedge(
        paths,
        DT,
        STRIKE,
        option_type,
        R,
        COST_RATE,
        PREMIUM,
        ratios,  # type: ignore[arg-type]
    )

    for i in range(10):
        account = OnlineHedgeAccount(STRIKE, option_type, R, COST_RATE, DT)  # type: ignore[arg-type]
        account.initialize(PREMIUM)
        for t in range(N_STEPS):
            account.update(paths[i, t], ratios[i, t])
        online_loss = -account.liquidate(paths[i, -1])

        assert online_loss == pytest.approx(batch_result.terminal_loss[i], abs=1e-9)
        assert account.total_cost == pytest.approx(batch_result.total_cost[i], abs=1e-9)
        assert account.total_turnover == pytest.approx(batch_result.total_turnover[i], abs=1e-9)


def test_history_records_one_entry_per_update() -> None:
    account = OnlineHedgeAccount(STRIKE, "call", R, COST_RATE, DT)
    account.initialize(PREMIUM)
    for t in range(5):
        account.update(100.0 + t, 0.5)
    assert len(account.history) == 5
    assert account.history[-1].spot == 104.0


def test_separate_trade_and_variable_rate_financing_have_exact_cash_flows() -> None:
    account = OnlineHedgeAccount(100.0, "call", 0.03, 0.01, 0.5)
    account.initialize(10.0)
    account.rebalance(100.0, 0.5)
    assert account.cash == pytest.approx(-40.5)
    account.accrue(0.1)
    account.rebalance(110.0, 0.25)
    cash = -40.5 * np.exp(0.05) + 27.5 - 0.275
    assert account.cash == pytest.approx(cash)
    account.accrue(-0.02)
    expected = cash * np.exp(-0.01) + 0.25 * 120.0 - 20.0
    assert account.terminal_loss(120.0) == pytest.approx(-expected)
    assert account.liquidate(120.0) == pytest.approx(expected)
    assert account.holdings == 0.0
    assert account.cash == pytest.approx(expected)
    assert account.total_cost == pytest.approx(0.775)


def test_invalid_trade_is_rejected_without_changing_cash_or_holdings() -> None:
    account = OnlineHedgeAccount(STRIKE, "call", R, COST_RATE, DT)
    account.initialize(PREMIUM)
    account.rebalance(100.0, 0.5)
    before = account.cash, account.holdings, account.total_cost, tuple(account.history)
    with pytest.raises(ValueError):
        account.update(float("nan"), 0.6)
    assert (account.cash, account.holdings, account.total_cost, tuple(account.history)) == before


def test_settled_account_cannot_trade_accrue_or_pay_the_payoff_again() -> None:
    account = OnlineHedgeAccount(STRIKE, "call", R, COST_RATE, DT)
    account.initialize(PREMIUM)
    account.liquidate(120.0)
    for action in (
        lambda: account.update(120.0, 0.5),
        lambda: account.accrue(),
        lambda: account.liquidate(120.0),
    ):
        with pytest.raises(RuntimeError, match="settled"):
            action()


@pytest.mark.parametrize(
    "overrides",
    [
        {"strike": 0.0},
        {"cost_rate": -0.01},
        {"risk_free_rate": float("inf")},
        {"dt": float("nan")},
        {"option_type": "invalid"},
    ],
)
def test_invalid_account_parameters_are_rejected(overrides) -> None:
    config = dict(strike=STRIKE, option_type="call", risk_free_rate=R, cost_rate=COST_RATE, dt=DT)
    with pytest.raises(ValueError):
        OnlineHedgeAccount(**(config | overrides))
