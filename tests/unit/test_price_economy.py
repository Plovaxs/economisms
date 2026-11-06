from dataclasses import replace
from datetime import date

import pytest

from prometheus.core.calendar import BusinessDayCalendar
from prometheus.core.money import Money
from prometheus.econosim.economy import Economy
from prometheus.econosim.price_economy import EconomyRunConfig, PriceEconomy
from prometheus.econosim.step_hooks import StepContext, StepHooks
from prometheus.econosim.time_engine import MacroTimeEngine


def test_duplicate_actions_cannot_apply_the_productivity_shock_twice() -> None:
    process = PriceEconomy(EconomyRunConfig(n_steps=2, productivity_shock_step=1))
    ctx = StepContext(1, date(2026, 2, 2), (), (), process.economy)
    actions = process.compute_actions(ctx)
    assert actions.productivity == 5
    with pytest.raises(ValueError, match="already been computed"):
        process.compute_actions(ctx)
    assert process.productivity == 5
    before = process.economy.ledger.snapshot(1).state_hash()
    with pytest.raises(ValueError):
        process.clear_and_settle(ctx, replace(actions, payroll_budget=Money(1)))
    assert process.economy.ledger.snapshot(1).state_hash() == before
    process.clear_and_settle(ctx, actions)
    after = process.economy.ledger.snapshot(1).state_hash()
    with pytest.raises(ValueError):
        process.clear_and_settle(ctx, actions)
    assert process.economy.ledger.snapshot(1).state_hash() == after


def test_price_economy_rejects_a_context_from_another_ledger() -> None:
    process = PriceEconomy(EconomyRunConfig(n_steps=2, productivity_shock_step=None))
    ctx = StepContext(1, date(2026, 2, 2), (), (), Economy())
    with pytest.raises(ValueError, match="context must match"):
        process.compute_actions(ctx)


def test_snapshot_requires_the_actual_completed_settlement_and_ledger_hash() -> None:
    process = PriceEconomy(EconomyRunConfig(n_steps=2, productivity_shock_step=None))
    engine = MacroTimeEngine(
        process.economy,
        BusinessDayCalendar(),
        date(2026, 1, 2),
        hooks=StepHooks(
            compute_actions=process.compute_actions, clear_and_settle=process.clear_and_settle
        ),
    )
    step = engine.advance_step()
    assert process.snapshot(step).step == 1
    with pytest.raises(ValueError):
        process.snapshot(replace(step, settlement=None))
    with pytest.raises(ValueError, match="hash differs"):
        process.snapshot(replace(step, state_hash="fabricated"))
