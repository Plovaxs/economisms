import math
from dataclasses import replace
from datetime import date

import pytest

from prometheus.hedging.comparison import HedgeComparisonSettings, OnlineHedgeComparison


def comparison(**settings):
    config = replace(
        HedgeComparisonSettings(
            n_train_paths=32, batch_size=16, n_train_epochs=2, risk_eval_n_paths=32
        ),
        **settings,
    )
    return OnlineHedgeComparison(
        config, n_steps=3, start_date=date(2026, 1, 2), initial_rate=0.03, seed=42
    )


@pytest.mark.parametrize("option_type", ["call", "put"])
def test_opening_rate_finances_each_interval_and_expiry_has_no_new_trade(option_type) -> None:
    model = comparison(option_type=option_type)
    cash = {"delta": model.initial_delta.cash_after, "mlp": model.initial_mlp.cash_after}
    holdings = {
        "delta": model.initial_delta.target_holdings,
        "mlp": model.initial_mlp.target_holdings,
    }
    costs = {"delta": model.initial_delta.cost, "mlp": model.initial_mlp.cost}
    for step, (opening, closing) in enumerate(
        zip((0.01, 0.07, -0.01), (0.07, -0.01, 0.04), strict=True), 1
    ):
        period = model.advance(step, opening)
        value = model.value_and_rebalance(step, date(2026, step + 1, 2), closing)
        risk = model.risk(step)
        assert model.risk(step) is risk
        assert period.physical_drift == opening + model.settings.equity_risk_premium
        for policy in ("delta", "mlp"):
            target = getattr(value, f"{policy}_holdings")
            trade = target - holdings[policy]
            cost = model.settings.cost_rate * abs(trade) * period.closing_spot
            cash[policy] = (
                cash[policy] * math.exp(opening / 12) - trade * period.closing_spot - cost
            )
            costs[policy] += cost
            holdings[policy] = target
            assert getattr(value, f"{policy}_cash") == pytest.approx(cash[policy], abs=1e-9)
            assert getattr(value, f"{policy}_cost") == pytest.approx(costs[policy])
        if step == 3:
            assert value.remaining_years == 0
            assert trade == 0
    delta, mlp = model.liquidate()
    for policy, wealth in (("delta", delta), ("mlp", mlp)):
        expected = cash[policy] + holdings[policy] * model.spot - value.option_value
        assert wealth == pytest.approx(expected)
        assert getattr(risk, f"{policy}_cvar") == pytest.approx(-wealth)
    with pytest.raises(ValueError):
        model.liquidate()


def test_financial_lifecycle_rejects_skipped_or_duplicate_phases() -> None:
    model = comparison()
    with pytest.raises(ValueError):
        model.value_and_rebalance(1, date(2026, 2, 2), 0.03)
    model.advance(1, 0.03)
    with pytest.raises(ValueError):
        model.advance(2, 0.03)
    with pytest.raises(ValueError):
        model.risk(1)
    model.value_and_rebalance(1, date(2026, 2, 2), 0.03)
    with pytest.raises(ValueError):
        model.value_and_rebalance(1, date(2026, 2, 2), 0.03)
    model.advance(2, 0.03)
    with pytest.raises(ValueError):
        model.risk(1)


@pytest.mark.parametrize(
    "overrides",
    [
        {"n_train_paths": 0},
        {"volatility": 0.0},
        {"cost_rate": -0.01},
        {"cvar_alpha": 1.0},
        {"learning_rate": float("inf")},
        {"option_type": "invalid"},
    ],
)
def test_invalid_comparison_settings_are_rejected(overrides) -> None:
    with pytest.raises(ValueError):
        replace(HedgeComparisonSettings(), **overrides)
