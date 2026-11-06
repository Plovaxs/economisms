from datetime import date

import numpy as np
import pytest

from prometheus.core.calendar import BusinessDayCalendar
from prometheus.core.ledger import LedgerIdentityViolation, Side
from prometheus.core.money import Money
from prometheus.econosim.economy import Economy
from prometheus.econosim.market_clearing import (
    apply_labor_clearing_to_ledger,
    clear_quantity_market,
)
from prometheus.econosim.step_hooks import StepContext, StepHooks
from prometheus.econosim.time_engine import MacroTimeEngine
from prometheus.stochastica.gbm import simulate_gbm_paths
from prometheus.titan.risk_metrics import historical_var
from prometheus.volterra.black_scholes import black_scholes_greeks, black_scholes_price
from prometheus.volterra.instruments import EuropeanOption
from prometheus.volterra.market import MarketSnapshot


def _funded_economy() -> tuple[Economy, object, object, object]:
    econ = Economy()
    firm = econ.add_firm("firm-1")
    hh1 = econ.add_household("hh-1")
    hh2 = econ.add_household("hh-2")
    hh1.receive_income(Money(10_000_00, "USD"))
    hh2.receive_income(Money(10_000_00, "USD"))
    hh1.consume(firm, Money(5_000_00, "USD"))  # seed the firm with cash
    return econ, firm, hh1, hh2


def test_no_hooks_leaves_all_new_fields_none() -> None:
    econ, *_ = _funded_economy()
    engine = MacroTimeEngine(econ, BusinessDayCalendar(), date(2026, 1, 1))
    result = engine.advance_step()
    assert result.actions is None
    assert result.settlement is None
    assert result.financial_step is None
    assert result.valuation_and_hedge is None
    assert result.portfolio_risk is None


def test_full_hook_wiring_against_real_subsystems() -> None:
    """Every hook calls the actual market-clearing / pricing / risk
    subsystems built in earlier PRs -- not a mock or a stub -- to prove
    MacroTimeEngine can genuinely orchestrate them, not just expose empty
    extension points."""
    econ, firm, hh1, hh2 = _funded_economy()
    households = {"hh-1": hh1, "hh-2": hh2}
    state = {"spot": 100.0}

    def compute_actions(ctx: StepContext):
        return {"firm_labor_demand": 15.0, "household_labor_supply": {"hh-1": 10.0, "hh-2": 10.0}}

    def clear_and_settle(ctx: StepContext, actions):
        clearing = clear_quantity_market(
            buy_orders={firm.agent_id: actions["firm_labor_demand"]},
            sell_orders=actions["household_labor_supply"],
        )
        apply_labor_clearing_to_ledger(
            clearing, households, firm, Money(1000, "USD"), step=ctx.step
        )
        return clearing

    def simulate_financial_step(ctx: StepContext, settlement):
        rng = np.random.default_rng(ctx.step)
        paths = simulate_gbm_paths(state["spot"], 0.05, 0.2, 1 / 12, n_steps=1, n_paths=1, rng=rng)
        state["spot"] = float(paths[0, -1])
        return state["spot"]

    def value_and_hedge(ctx: StepContext, financial_step, settlement):
        market = MarketSnapshot(
            as_of=ctx.step_date, spot=financial_step, risk_free_rate=0.05, volatility=0.2
        )
        option = EuropeanOption(strike=100.0, maturity=0.5, option_type="call")
        return {
            "price": black_scholes_price(market, option),
            "delta": black_scholes_greeks(market, option).delta,
        }

    def compute_portfolio_risk(ctx: StepContext, valuation_and_hedge, financial_step):
        rng = np.random.default_rng(ctx.step + 1000)
        pnl_samples = rng.normal(0, 1000.0, size=500)
        return historical_var(-pnl_samples, 0.95)

    hooks = StepHooks(
        compute_actions=compute_actions,
        clear_and_settle=clear_and_settle,
        simulate_financial_step=simulate_financial_step,
        value_and_hedge=value_and_hedge,
        compute_portfolio_risk=compute_portfolio_risk,
    )
    engine = MacroTimeEngine(econ, BusinessDayCalendar(), date(2026, 1, 1), hooks=hooks)

    results = [engine.advance_step() for _ in range(3)]

    for result in results:
        assert result.actions is not None
        assert isinstance(result.settlement.total_realized_quantity, float)
        assert isinstance(result.financial_step, float)
        assert "price" in result.valuation_and_hedge and "delta" in result.valuation_and_hedge
        assert isinstance(result.portfolio_risk, float)

    assert hh1.cash_balance != Money(5_000_00, "USD")  # wages were actually paid
    econ.check_integrity()


def test_hooks_receive_the_same_context_fields_advance_step_reports() -> None:
    econ, *_ = _funded_economy()
    captured: list[StepContext] = []

    hooks = StepHooks(compute_actions=lambda ctx: captured.append(ctx))
    engine = MacroTimeEngine(econ, BusinessDayCalendar(), date(2026, 1, 1), hooks=hooks)
    result = engine.advance_step()

    assert len(captured) == 1
    ctx = captured[0]
    assert ctx.step == result.step
    assert ctx.step_date == result.step_date
    assert ctx.released == result.released
    assert ctx.shocks == result.shocks
    assert ctx.economy is econ


def test_hook_results_thread_into_the_next_hook() -> None:
    econ, *_ = _funded_economy()
    received: dict = {}

    def compute_actions(ctx):
        return "actions-value"

    def clear_and_settle(ctx, actions):
        received["clear_and_settle_got"] = actions
        return "settlement-value"

    def simulate_financial_step(ctx, settlement):
        received["financial_step_got"] = settlement
        return "financial-value"

    def value_and_hedge(ctx, financial_step, settlement):
        received["value_and_hedge_got"] = (financial_step, settlement)
        return "valuation-value"

    def compute_portfolio_risk(ctx, valuation_and_hedge, financial_step):
        received["risk_got"] = (valuation_and_hedge, financial_step)
        return "risk-value"

    hooks = StepHooks(
        compute_actions=compute_actions,
        clear_and_settle=clear_and_settle,
        simulate_financial_step=simulate_financial_step,
        value_and_hedge=value_and_hedge,
        compute_portfolio_risk=compute_portfolio_risk,
    )
    engine = MacroTimeEngine(econ, BusinessDayCalendar(), date(2026, 1, 1), hooks=hooks)
    result = engine.advance_step()

    assert received["clear_and_settle_got"] == "actions-value"
    assert received["financial_step_got"] == "settlement-value"
    assert received["value_and_hedge_got"] == ("financial-value", "settlement-value")
    assert received["risk_got"] == ("valuation-value", "financial-value")
    assert result.portfolio_risk == "risk-value"


def test_partial_hooks_only_populate_configured_slots() -> None:
    econ, *_ = _funded_economy()
    hooks = StepHooks(compute_actions=lambda ctx: 42)
    engine = MacroTimeEngine(econ, BusinessDayCalendar(), date(2026, 1, 1), hooks=hooks)
    result = engine.advance_step()

    assert result.actions == 42
    assert result.settlement is None
    assert result.financial_step is None
    assert result.valuation_and_hedge is None
    assert result.portfolio_risk is None


def test_state_hash_reflects_ledger_mutations_made_by_hooks() -> None:
    """Step 8's snapshot/hash is taken AFTER steps 3-7 run, so a hook that
    posts a ledger transaction must change the resulting state_hash."""
    econ_a, firm_a, hh1_a, _ = _funded_economy()
    econ_b, _, _, _ = _funded_economy()

    def settle(ctx, actions):
        firm_a.pay_wages(hh1_a, Money(100_00, "USD"), step=ctx.step)

    hooks_mutating = StepHooks(clear_and_settle=settle)
    engine_a = MacroTimeEngine(
        econ_a, BusinessDayCalendar(), date(2026, 1, 1), hooks=hooks_mutating
    )
    engine_b = MacroTimeEngine(econ_b, BusinessDayCalendar(), date(2026, 1, 1))  # no hooks

    result_a = engine_a.advance_step()
    result_b = engine_b.advance_step()
    assert result_a.state_hash != result_b.state_hash


def test_hook_corruption_is_rejected_before_a_step_result_is_emitted() -> None:
    economy, *_ = _funded_economy()

    def corrupt(ctx: StepContext):
        ctx.economy.ledger.account("firm-1:deposit")._apply(Side.DEBIT, Money(1))

    engine = MacroTimeEngine(
        economy,
        BusinessDayCalendar(),
        date(2026, 1, 1),
        hooks=StepHooks(compute_actions=corrupt),
    )
    with pytest.raises(LedgerIdentityViolation):
        engine.advance_step()


@pytest.mark.parametrize("unset_slot", ["compute_actions", "value_and_hedge"])
def test_missing_hook_in_the_middle_still_threads_none_onward(unset_slot: str) -> None:
    econ, *_ = _funded_economy()
    calls: list[str] = []

    def mark(name):
        def _hook(*args):
            calls.append(name)
            return f"{name}-result"

        return _hook

    kwargs = {
        "compute_actions": mark("actions"),
        "clear_and_settle": mark("settle"),
        "simulate_financial_step": mark("financial"),
        "value_and_hedge": mark("value"),
        "compute_portfolio_risk": mark("risk"),
    }
    kwargs[unset_slot] = None
    hooks = StepHooks(**kwargs)
    engine = MacroTimeEngine(econ, BusinessDayCalendar(), date(2026, 1, 1), hooks=hooks)
    engine.advance_step()

    expected_calls = [
        name
        for name, key in [
            ("actions", "compute_actions"),
            ("settle", "clear_and_settle"),
            ("financial", "simulate_financial_step"),
            ("value", "value_and_hedge"),
            ("risk", "compute_portfolio_risk"),
        ]
        if key != unset_slot
    ]
    assert calls == expected_calls
