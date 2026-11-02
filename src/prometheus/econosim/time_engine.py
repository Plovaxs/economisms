"""MacroTimeEngine: known-at releases, deterministic shocks, and stepping.

Implements steps 1, 2 and 8 of the section-02 event order:
  1. Release information  -- only data eligible under the point-in-time
     predicate (as of the step's current date) is exposed.
  2. Apply external shocks -- drawn deterministically for the step about to
     begin (tagged exogenous_shock[t+1], matching section 3.1's notation).
  8. Commit next state     -- the ledger's accounting identities are
     reconfirmed, the clock advances one macro step (snapped to the next
     business day), and a content hash of the resulting ledger state is
     produced.

Steps 3-7 (agent decisions, market clearing, financial-step simulation,
valuation/hedging, portfolio risk) belong to subsystems not built yet
(learned agent policies, STOCHASTICA, VOLTERRA, TITAN) and are intentionally
not implemented here.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from prometheus.core.calendar import BusinessDayCalendar, add_months
from prometheus.econosim.economy import Economy
from prometheus.econosim.pit import MacroObservation, PointInTimeStore
from prometheus.econosim.shocks import Shock, ShockGenerator


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


class MacroTimeEngine:
    def __init__(
        self,
        economy: Economy,
        calendar: BusinessDayCalendar,
        start: date,
        shock_generator: ShockGenerator | None = None,
        point_in_time_store: PointInTimeStore | None = None,
    ) -> None:
        self.economy = economy
        self.clock = MacroClock(calendar, start)
        self.shock_generator = shock_generator
        self.store = point_in_time_store or PointInTimeStore()
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

        snapshot = self.economy.ledger.snapshot(self.economy.step_index)
        return StepResult(
            step=self.economy.step_index,
            step_date=step_date,
            released=released,
            shocks=tuple(shocks),
            state_hash=snapshot.state_hash(),
        )
