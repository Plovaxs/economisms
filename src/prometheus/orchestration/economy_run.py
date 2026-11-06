"""A monthly economy with budget-feasible wage/goods price discovery.

One firm hires elastic household labor, produces physical inventory, then
sells goods against household spending budgets. Both prices are found by
bounded integer-tick bisection. Accounting settlement is atomic per market;
the complete multi-market step is not rolled back on a later failure.

This is a rule-based cash economy, not a competitive general-equilibrium
or profit-maximizing production model. Physical inventory has no monetary
valuation on the ledger. Financial pricing/hedging hooks are not used here.
"""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from datetime import date
from fractions import Fraction
from pathlib import Path
from typing import Any

from prometheus.core.calendar import BusinessDayCalendar
from prometheus.core.ledger import LedgerError
from prometheus.core.money import Money
from prometheus.econosim.agents import AgentError
from prometheus.econosim.price_economy import (
    EconomicActions as EconomicActions,
)
from prometheus.econosim.price_economy import (
    EconomicSettlement as EconomicSettlement,
)
from prometheus.econosim.price_economy import (
    EconomyRunConfig as EconomyRunConfig,
)
from prometheus.econosim.price_economy import (
    EconomyStep as EconomyStep,
)
from prometheus.econosim.price_economy import (
    PriceEconomy,
)
from prometheus.econosim.step_hooks import StepHooks
from prometheus.econosim.time_engine import MacroTimeEngine
from prometheus.evidence.export import build_evidence_bundle, export_evidence_bundle
from prometheus.evidence.repository_status import current_repository_gate_report
from prometheus.experiments.manifest import (
    RunManifest,
    compute_result_hash,
    json_default,
    new_run_id,
    now_iso,
)

LIMITATIONS = (
    "One firm; budget demand and linear supply are specified rules, not estimated preferences.",
    "A nominal payroll target is cash-capped, not chosen by profit maximization.",
    "Physical inventory is tracked exactly but has no monetary asset valuation on the ledger.",
    "Integer price ticks and price bounds can leave excess demand; rationing is reported.",
    "Market batches are atomic, but failed multi-market steps are not rolled back or resumed.",
    "No banking, monetary-policy optimization, price calibration or financial hedge integration.",
    "Monthly dates use the existing business-day clock, not an actual/365 day-count basis.",
)


@dataclass(frozen=True, slots=True)
class EconomyRunResult:
    valid: bool
    invalid_reasons: tuple[str, ...]
    steps: tuple[EconomyStep, ...]
    manifest: RunManifest
    evidence_bundle: dict[str, Any]


def run_economy(config: EconomyRunConfig) -> EconomyRunResult:
    process = PriceEconomy(config)
    economy = process.economy
    engine = MacroTimeEngine(
        economy,
        BusinessDayCalendar(),
        config.start_date,
        hooks=StepHooks(
            compute_actions=process.compute_actions, clear_and_settle=process.clear_and_settle
        ),
    )
    steps: list[EconomyStep] = []
    invalid_reasons: list[str] = []
    try:
        for _ in range(config.n_steps):
            steps.append(process.snapshot(engine.advance_step()))
    except (LedgerError, AgentError, ValueError, ArithmeticError) as exc:
        invalid_reasons.append(f"step {engine.clock.step_index}: {type(exc).__name__}: {exc}")
    payload = {
        "schema_version": 1,
        "accounting_convention": "atomic-market-settlement-v1",
        "model_convention": "budget-linear-schedules-v1",
        "config": asdict(config),
        "valid": not invalid_reasons,
        "invalid_reasons": invalid_reasons,
        "initial_injected_cash": asdict(process.injected),
        "initial_state_hash": process.initial_state_hash,
        "steps": [asdict(step) for step in steps],
        "final_inventory": process.inventory if not invalid_reasons else None,
        "diagnostic_final_ledger_hash": economy.ledger.snapshot(economy.step_index).state_hash(),
        "limitations": LIMITATIONS,
    }
    manifest = RunManifest(
        new_run_id("pmth-economy"),
        now_iso(),
        config.seed,
        asdict(config),
        compute_result_hash(payload),
    )
    bundle = build_evidence_bundle(manifest, [], current_repository_gate_report())
    bundle["economy"] = payload
    return EconomyRunResult(
        not invalid_reasons, tuple(invalid_reasons), tuple(steps), manifest, bundle
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--steps", type=int, default=12)
    parser.add_argument("--start-date", type=date.fromisoformat, default=date(2026, 1, 2))
    shock = parser.add_mutually_exclusive_group()
    shock.add_argument("--shock-step", type=int)
    shock.add_argument("--no-shock", action="store_true")
    parser.add_argument("--shock-multiplier", type=Fraction, default=Fraction(1, 2))
    parser.add_argument("--productivity-noise-std", type=float, default=0.0)
    parser.add_argument("--consumption-propensity", type=Fraction, default=Fraction(1))
    parser.add_argument("--firm-capital-minor", type=int, default=200_000)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    try:
        config = EconomyRunConfig(
            seed=args.seed,
            n_steps=args.steps,
            start_date=args.start_date,
            productivity_shock_step=None
            if args.no_shock
            else (args.shock_step if args.shock_step is not None else min(4, args.steps)),
            productivity_shock_multiplier=args.shock_multiplier,
            productivity_noise_std=args.productivity_noise_std,
            consumption_propensity=args.consumption_propensity,
            firm_capital=Money(args.firm_capital_minor),
        )
    except ValueError as exc:
        parser.error(str(exc))
    result = run_economy(config)
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        export_evidence_bundle(result.evidence_bundle, args.output)
    print(
        json.dumps(
            {
                "valid": result.valid,
                "completed_steps": len(result.steps),
                "invalid_reasons": result.invalid_reasons,
                "final_inventory": result.evidence_bundle["economy"]["final_inventory"],
                "result_hash": result.manifest.result_hash,
                "evidence_path": str(args.output) if args.output else None,
            },
            indent=2,
            default=json_default,
        )
    )
    return 0 if result.valid else 1


if __name__ == "__main__":
    raise SystemExit(main())
