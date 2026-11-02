"""Pluggable, strictly ordered callbacks for section 02's steps 3-7 (agent
decisions, market clearing, financial-step simulation, valuation/hedging,
portfolio risk), invoked by MacroTimeEngine.advance_step() in the causal
order the specification defines -- each hook only ever sees a StepContext
built from data already known as of that step, so a hook cannot
accidentally peek at a later step's prices or shocks.

This generalizes PR-011's one-off demo_run pipeline into something
MacroTimeEngine itself owns and calls every step, rather than a caller
re-implementing the loop by hand. It does NOT ship an opinion about what
steps 3-7 should actually compute -- that remains scenario-specific, the
same way demo_run.py hard-codes one scenario's choices. See
tests/unit/test_time_engine_hooks.py for a worked wiring of all five slots
against the real market-clearing/hedging/risk subsystems (not a mock).

Hook result types are intentionally `Any`: the engine never inspects what
a hook returns, it only threads each result to the next hook and records
it on StepResult -- there is nothing for the engine itself to type-check
at this boundary beyond "a callable was supplied." Each hook is optional;
an unset hook is skipped and its StepResult slot stays None.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from typing import Any

from prometheus.econosim.economy import Economy
from prometheus.econosim.pit import MacroObservation
from prometheus.econosim.shocks import Shock


@dataclass(frozen=True, slots=True)
class StepContext:
    step: int
    step_date: date
    released: tuple[MacroObservation, ...]
    shocks: tuple[Shock, ...]
    economy: Economy


@dataclass(frozen=True, slots=True)
class StepHooks:
    compute_actions: Callable[[StepContext], Any] | None = None
    """Step 3: agent decisions from observed state."""

    clear_and_settle: Callable[[StepContext, Any], Any] | None = None
    """Step 4: budget constraints, journal entries, market clearing.
    Receives (context, actions)."""

    simulate_financial_step: Callable[[StepContext, Any], Any] | None = None
    """Step 5: draw physical-measure shocks, update financial state.
    Receives (context, settlement)."""

    value_and_hedge: Callable[[StepContext, Any, Any], Any] | None = None
    """Step 6: risk-neutral valuation, hedge actions under cost.
    Receives (context, financial_step, settlement)."""

    compute_portfolio_risk: Callable[[StepContext, Any, Any], Any] | None = None
    """Step 7: realized P&L, conditional losses, constraints/limits.
    Receives (context, valuation_and_hedge, financial_step)."""
