"""MacroTimeEngine: known-at releases, deterministic shocks, stepping, and
(given StepHooks) the full section-02 event order:
  1. Release information  -- only data eligible under the point-in-time
     predicate (as of the step's current date) is exposed.
  2. Apply external shocks -- drawn deterministically for the step about to
     begin (tagged exogenous_shock[t+1], matching section 3.1's notation).
  3-7. Agent decisions, market clearing, financial-step simulation,
     valuation/hedging, portfolio risk -- each optional, supplied by the
     caller as a StepHooks (see step_hooks.py); skipped entirely (the
     corresponding StepResult field stays None) when not configured.
  8. Commit next state     -- the ledger's accounting identities are
     reconfirmed, the clock advances one macro step (snapped to the next
     business day), and a content hash of the resulting ledger state is
     produced, capturing any mutation steps 3-7 made.

Without hooks this engine behaves exactly as it did before they existed
(steps 1/2/8 only); hooks are additive, not a breaking change to the
existing no-hooks behavior relied on by PR-003's original tests.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any

from prometheus.core.calendar import BusinessDayCalendar, add_months
from prometheus.econosim.economy import Economy
from prometheus.econosim.pit import MacroObservation, PointInTimeStore
from prometheus.econosim.shocks import Shock, ShockGenerator
from prometheus.econosim.step_hooks import StepContext, StepHooks


@dataclass
class MacroClock:
    calendar: BusinessDayCalendar
    start: date
    step_index: int = 0
    current_date: date = field(init=False)

    def __post_init__(self) -> None:
        self.current_date = self.calendar.next_business_day(self.start)

    def advance_macro_step(self) -> date:
        """One macro step = one calendar month, snapped forward to the next
        business day (section 02's suggested clock)."""
        self.step_index += 1
        target = add_months(self.current_date, 1)
        self.current_date = self.calendar.next_business_day(target)
        return self.current_date


@dataclass(frozen=True, slots=True)
class StepResult:
    step: int
    step_date: date
    released: tuple[MacroObservation, ...]
    shocks: tuple[Shock, ...]
    state_hash: str
    actions: Any = None
    settlement: Any = None
    financial_step: Any = None
    valuation_and_hedge: Any = None
    portfolio_risk: Any = None


class MacroTimeEngine:
    def __init__(
        self,
        economy: Economy,
        calendar: BusinessDayCalendar,
        start: date,
        shock_generator: ShockGenerator | None = None,
        point_in_time_store: PointInTimeStore | None = None,
        hooks: StepHooks | None = None,
    ) -> None:
        self.economy = economy
        self.clock = MacroClock(calendar, start)
        self.shock_generator = shock_generator
        self.store = point_in_time_store or PointInTimeStore()
        self.hooks = hooks
        self.shock_log: list[Shock] = []
        self.economy.step_index = self.clock.step_index

    def released_observations(self) -> tuple[MacroObservation, ...]:
        return self.store.all_eligible_as_of(self.clock.current_date)

    def advance_step(self) -> StepResult:
        # Fail closed before doing anything else this step (ECO-16): a
        # corrupted ledger must not silently continue accruing more steps.
        self.economy.check_integrity()

        # Advance the clock first, then release information and draw shocks
        # as of the *new* date/step -- release and shocks in a StepResult
        # always describe the same moment as that result's step_date.
        step_date = self.clock.advance_macro_step()
        self.economy.step_index = self.clock.step_index

        released = self.released_observations()

        shocks = (
            self.shock_generator.draw_for_step(self.clock.step_index)
            if self.shock_generator
            else []
        )
        self.shock_log.extend(shocks)

        actions = settlement = financial_step = valuation_and_hedge = portfolio_risk = None
        if self.hooks is not None:
            context = StepContext(
                step=self.economy.step_index,
                step_date=step_date,
                released=released,
                shocks=tuple(shocks),
                economy=self.economy,
            )
            if self.hooks.compute_actions is not None:
                actions = self.hooks.compute_actions(context)
            if self.hooks.clear_and_settle is not None:
                settlement = self.hooks.clear_and_settle(context, actions)
            if self.hooks.simulate_financial_step is not None:
                financial_step = self.hooks.simulate_financial_step(context, settlement)
            if self.hooks.value_and_hedge is not None:
                valuation_and_hedge = self.hooks.value_and_hedge(
                    context, financial_step, settlement
                )
            if self.hooks.compute_portfolio_risk is not None:
                portfolio_risk = self.hooks.compute_portfolio_risk(
                    context, valuation_and_hedge, financial_step
                )

        # Steps 3-7 (if any ran) may have posted new ledger transactions;
        # the snapshot/hash below is taken after them, not before, so it
        # reflects everything that happened this step.
        snapshot = self.economy.ledger.snapshot(self.economy.step_index)
        return StepResult(
            step=self.economy.step_index,
            step_date=step_date,
            released=released,
            shocks=tuple(shocks),
            state_hash=snapshot.state_hash(),
            actions=actions,
            settlement=settlement,
            financial_step=financial_step,
            valuation_and_hedge=valuation_and_hedge,
            portfolio_risk=portfolio_risk,
        )
