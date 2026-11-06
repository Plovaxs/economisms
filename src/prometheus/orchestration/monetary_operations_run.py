"""A reproducible run of `econosim.monetary_operations`'s central-bank
StepHooks scenario (PR-028), with evidence export and replay support --
the orchestration wrapper PR-028 explicitly left undone, following the
exact pattern `economy_run.py` already uses for `price_economy.PriceEconomy`.

Policy-rate shocks are drawn from a dedicated named stream
(`SeedHierarchy(config.seed).stream("policy-rate-shocks")`), so the whole
run -- rate path, OMO/discount-window/interbank decisions, and every
resulting ledger balance -- is fully determined by `config.seed` alone.
"""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path
from typing import Any

from prometheus.core.calendar import BusinessDayCalendar
from prometheus.core.ledger import LedgerError
from prometheus.core.seeds import SeedHierarchy
from prometheus.econosim.agents import AgentError
from prometheus.econosim.monetary_operations import (
    MonetaryOperationsConfig,
    MonetaryOperationsProcess,
    MonetaryOperationsStep,
)
from prometheus.econosim.shocks import ShockGenerator, ShockSpec
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

MODEL_CONVENTION = "rate-driven-omo-discount-window-interbank-v1"

LIMITATIONS = (
    "Two banks, one ledger-backed central bank; OMO/discount-window/interbank sizes are "
    "specified schedules, not a profit-maximizing or learned monetary policy.",
    "The policy rate's step-over-step change sizes the OMO linearly; no term structure, "
    "no reserve-requirement enforcement, and no interest accrual on any balance (LED-05).",
    "A failed/infeasible operation (insufficient bonds, settlement balance, etc.) is "
    "skipped and recorded in that step's settlement, not retried, rescheduled or rolled back.",
    "Monthly dt is a business-day-snapped calendar label, not an actual/365 day-count basis.",
    "Standalone: no connection to titan.portfolio/covariance/factor_model or to any other "
    "StepHooks scenario's market, hedging or price-discovery state.",
)


@dataclass(frozen=True, slots=True)
class MonetaryOperationsRunResult:
    valid: bool
    invalid_reasons: tuple[str, ...]
    steps: tuple[MonetaryOperationsStep, ...]
    manifest: RunManifest
    evidence_bundle: dict[str, Any]


def run_monetary_operations(config: MonetaryOperationsConfig) -> MonetaryOperationsRunResult:
    process = MonetaryOperationsProcess(config)
    shock_rng = SeedHierarchy(config.seed).stream("policy-rate-shocks")
    shock_generator = ShockGenerator(
        shock_rng, [ShockSpec(kind="policy_rate", std=config.policy_rate_shock_std)]
    )
    engine = MacroTimeEngine(
        process.economy,
        BusinessDayCalendar(),
        config.start_date,
        shock_generator=shock_generator,
        hooks=StepHooks(
            compute_actions=process.compute_actions, clear_and_settle=process.clear_and_settle
        ),
    )
    steps: list[MonetaryOperationsStep] = []
    invalid_reasons: list[str] = []
    try:
        for _ in range(config.n_steps):
            steps.append(process.snapshot(engine.advance_step()))
    except (LedgerError, AgentError, ValueError, ArithmeticError) as exc:
        invalid_reasons.append(f"step {engine.clock.step_index}: {type(exc).__name__}: {exc}")

    payload = {
        "schema_version": 1,
        "accounting_convention": "central-bank-ledger-stephooks-v1",
        "model_convention": MODEL_CONVENTION,
        "config": asdict(config),
        "valid": not invalid_reasons,
        "invalid_reasons": invalid_reasons,
        "steps": [asdict(step) for step in steps],
        "diagnostic_final_ledger_hash": process.economy.ledger.snapshot(
            process.economy.step_index
        ).state_hash(),
        "limitations": LIMITATIONS,
    }
    manifest = RunManifest(
        new_run_id("pmth-monetary-ops"),
        now_iso(),
        config.seed,
        asdict(config),
        compute_result_hash(payload),
    )
    bundle = build_evidence_bundle(manifest, [], current_repository_gate_report())
    bundle["monetary_operations"] = payload
    return MonetaryOperationsRunResult(
        not invalid_reasons, tuple(invalid_reasons), tuple(steps), manifest, bundle
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--steps", type=int, default=12)
    parser.add_argument("--start-date", type=date.fromisoformat, default=date(2026, 1, 2))
    parser.add_argument("--policy-rate-shock-std", type=float, default=0.01)
    parser.add_argument("--interbank-transfer-every", type=int, default=3)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    try:
        config = MonetaryOperationsConfig(
            seed=args.seed,
            n_steps=args.steps,
            start_date=args.start_date,
            policy_rate_shock_std=args.policy_rate_shock_std,
            interbank_transfer_every=args.interbank_transfer_every,
        )
    except ValueError as exc:
        parser.error(str(exc))
    result = run_monetary_operations(config)
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        export_evidence_bundle(result.evidence_bundle, args.output)
    print(
        json.dumps(
            {
                "valid": result.valid,
                "completed_steps": len(result.steps),
                "invalid_reasons": result.invalid_reasons,
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
