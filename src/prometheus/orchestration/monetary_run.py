"""A causal price-economy -> published inflation/output -> policy -> hedge loop.

The opening rate funds the entire interval and sets physical market drift.
The closing policy decision uses only already-published macro observations;
it sets valuation and the rate for the next interval. Lagged opening rates
also scale the firm's desired nominal payroll through a declared behavioral
channel. No financial-account interest is injected into the economic ledger.
"""

from __future__ import annotations

import argparse
import json
import math
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass, field, fields, replace
from fractions import Fraction
from pathlib import Path
from typing import Any

import numpy as np

from prometheus.core.calendar import BusinessDayCalendar
from prometheus.core.ledger import LedgerError
from prometheus.core.money import Money
from prometheus.econosim.agents import AgentError
from prometheus.econosim.monetary_feedback import (
    InflationOutputRule,
    PolicyDecision,
    publish_macro_observation,
    published_macro_signal,
)
from prometheus.econosim.pit import MacroObservation, PointInTimeStore
from prometheus.econosim.price_economy import (
    EconomicActions,
    EconomicSettlement,
    EconomyRunConfig,
    EconomyStep,
    PriceEconomy,
)
from prometheus.econosim.step_hooks import StepContext, StepHooks
from prometheus.econosim.time_engine import MacroTimeEngine, StepResult
from prometheus.evidence.export import build_evidence_bundle, export_evidence_bundle
from prometheus.evidence.repository_status import (
    build_deep_hedge_model_card,
    current_repository_gate_report,
)
from prometheus.experiments.manifest import RunManifest, compute_result_hash, new_run_id, now_iso
from prometheus.hedging.comparison import (
    ConditionalHedgeRisk,
    FinancialPeriod,
    HedgeComparisonSettings,
    HedgeValuation,
    OnlineHedgeComparison,
)

LIMITATIONS = (
    "Synthetic one-firm economy and single-asset GBM; no empirical calibration/identification.",
    "Inflation is an annualized log change of traded model-good prices, not CPI.",
    "Potential output is a configured physical reference, not an estimated GDP/output gap.",
    "The payroll rate channel is a demand rule; it does not post loan/interest transactions.",
    "Economic cash/equity and floating-point hedge accounts remain separate balance sheets.",
    "The bounded feedback rule has no optimizing policy or central-bank balance sheet.",
    "Conditional CVaR freezes holdings and rates; future macro/policy updates are omitted.",
    "Black-Scholes marks freeze the closing rate to expiry; no stochastic-rate Q model is solved.",
    "MLP training uses constant-initial-rate GBM; feedback rates can shift outside that setting.",
    "One realized trajectory is not evidence of policy superiority or statistical significance.",
    "Failed steps halt without rollback; atomicity covers individual economic market batches.",
    "Latest published macro observations can remain stale when no new goods trades occur.",
)


@dataclass(frozen=True, slots=True)
class MonetaryRunConfig:
    seed: int = 0
    economy: EconomyRunConfig = field(default_factory=EconomyRunConfig)
    policy: InflationOutputRule = field(default_factory=InflationOutputRule)
    hedge: HedgeComparisonSettings = field(default_factory=HedgeComparisonSettings)
    initial_rate: float = 0.03
    publication_lag_months: int = 1
    inflation_window_months: int = 12
    potential_output: float = 180.0
    payroll_rate_sensitivity: float = 2.0

    def __post_init__(self) -> None:
        for name in ("seed", "publication_lag_months", "inflation_window_months"):
            minimum = 0 if name == "seed" else 1
            value = getattr(self, name)
            if type(value) is not int or value < minimum:
                raise ValueError(f"{name} must be an integer >= {minimum}")
        if not isinstance(self.economy, EconomyRunConfig) or not isinstance(
            self.policy, InflationOutputRule
        ):
            raise ValueError("economy and policy must be their typed configuration objects")
        if not isinstance(self.hedge, HedgeComparisonSettings):
            raise ValueError("hedge must be HedgeComparisonSettings")
        for name in ("initial_rate", "potential_output", "payroll_rate_sensitivity"):
            value = getattr(self, name)
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(value)
            ):
                raise ValueError(f"{name} must be finite numeric data")
        if self.potential_output <= 0 or self.payroll_rate_sensitivity < 0:
            raise ValueError("potential output must be positive and rate sensitivity non-negative")
        if not self.policy.rate_floor <= self.initial_rate <= self.policy.rate_ceiling:
            raise ValueError("initial_rate must lie within policy bounds")

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> MonetaryRunConfig:
        if set(payload) != {item.name for item in fields(cls)}:
            raise ValueError("monetary replay requires exactly the complete configuration fields")
        values = dict(payload)
        try:
            values["economy"] = EconomyRunConfig.from_dict(values["economy"])
            for key, model in (("policy", InflationOutputRule), ("hedge", HedgeComparisonSettings)):
                if set(values[key]) != {item.name for item in fields(model)}:
                    raise ValueError(f"monetary replay requires the complete {key} configuration")
                values[key] = model(**values[key])
            return cls(**values)
        except (TypeError, AttributeError) as exc:
            raise ValueError(f"invalid monetary replay configuration: {exc}") from exc


@dataclass(frozen=True, slots=True)
class MonetaryActions:
    policy: PolicyDecision
    economic: EconomicActions
    adjusted_payroll_target: Money
    payroll_multiplier: Fraction


@dataclass(frozen=True, slots=True)
class MonetaryStep:
    step: int
    economic: EconomyStep
    policy: PolicyDecision
    adjusted_payroll_target: Money
    payroll_multiplier: Fraction
    new_publications: tuple[MacroObservation, ...]
    financial: FinancialPeriod
    valuation: HedgeValuation
    risk: ConditionalHedgeRisk


@dataclass(frozen=True, slots=True)
class MonetaryRunResult:
    valid: bool
    invalid_reasons: tuple[str, ...]
    steps: tuple[MonetaryStep, ...]
    delta_final_wealth: float | None
    mlp_final_wealth: float | None
    manifest: RunManifest
    evidence_bundle: dict[str, Any]


@dataclass(frozen=True, slots=True)
class MonetaryMacroStep:
    step: int
    economic: EconomyStep
    policy: PolicyDecision
    adjusted_payroll_target: Money
    payroll_multiplier: Fraction
    new_publications: tuple[MacroObservation, ...]


class MonetaryProcess:
    """One shared causal macro implementation for online and batch experiments."""

    def __init__(self, config: MonetaryRunConfig) -> None:
        self.config = config
        self.process = PriceEconomy(config.economy)
        self.calendar = BusinessDayCalendar()
        self.store = PointInTimeStore()
        self.rate = config.initial_rate
        self.latest_actions: MonetaryActions | None = None
        self.latest_publications: tuple[MacroObservation, ...] = ()
        self.publication_ledger: list[MacroObservation] = []
        self.stage = "step_initialization"
        self.engine = MacroTimeEngine(
            self.process.economy,
            self.calendar,
            config.economy.start_date,
            point_in_time_store=self.store,
            hooks=StepHooks(self.compute_actions, self.clear_and_settle),
        )

    def compute_actions(self, ctx: StepContext) -> MonetaryActions:
        self.stage = "published_policy_and_economic_actions"
        signal = published_macro_signal(
            ctx.released,
            as_of=ctx.step_date,
            decision_step=ctx.step,
            window_months=self.config.inflation_window_months,
            potential_output=self.config.potential_output,
        )
        decision = self.config.policy.decide(self.rate, signal)
        multiplier = Fraction(
            str(
                math.exp(
                    -self.config.payroll_rate_sensitivity
                    * (self.rate - self.config.policy.neutral_rate)
                )
            )
        )
        target = Money(int(self.config.economy.payroll_target.minor_units * multiplier))
        economic = self.process.compute_actions(ctx, payroll_target=target)
        self.latest_actions = MonetaryActions(decision, economic, target, multiplier)
        self.rate = decision.next_rate
        return self.latest_actions

    def clear_and_settle(self, ctx: StepContext, actions: MonetaryActions) -> EconomicSettlement:
        self.stage = "economic_settlement_and_publication"
        settlement = self.process.clear_and_settle(ctx, actions.economic)
        self.latest_publications = publish_macro_observation(
            self.store,
            self.calendar,
            step=ctx.step,
            observed_at=ctx.step_date,
            lag_months=self.config.publication_lag_months,
            price=settlement.goods.allocation.price,
            produced=settlement.produced,
            trade_quantity=settlement.sales.realized_quantity,
        )
        self.publication_ledger.extend(self.latest_publications)
        return settlement

    def snapshot(self, step: StepResult) -> MonetaryMacroStep:
        self.stage = "economic_invariants"
        actions: MonetaryActions = step.actions
        economic = self.process.snapshot(replace(step, actions=actions.economic))
        return MonetaryMacroStep(
            step.step,
            economic,
            actions.policy,
            actions.adjusted_payroll_target,
            actions.payroll_multiplier,
            self.latest_publications,
        )


@dataclass(frozen=True, slots=True)
class MonetaryMacroPath:
    valid: bool
    invalid_reasons: tuple[str, ...]
    steps: tuple[MonetaryMacroStep, ...]


def run_monetary_macro_path(config: MonetaryRunConfig) -> MonetaryMacroPath:
    """Run the exact same macro hooks without training or financial Monte Carlo.

    In this specified model macro outcomes do not depend on hedge wealth or
    market randomness, so a bank can share its macro path across all hedges.
    """
    macro = MonetaryProcess(config)
    steps = []
    reasons = []
    try:
        with np.errstate(over="raise", invalid="raise", divide="raise"):
            for _ in range(config.economy.n_steps):
                macro.stage = "step_initialization"
                steps.append(macro.snapshot(macro.engine.advance_step()))
    except (LedgerError, AgentError, ValueError, ArithmeticError) as exc:
        reasons.append(
            f"step {macro.engine.clock.step_index} / {macro.stage}: {type(exc).__name__}: {exc}"
        )
    return MonetaryMacroPath(not reasons, tuple(reasons), tuple(steps))


def run_monetary_simulation(config: MonetaryRunConfig) -> MonetaryRunResult:
    macro = MonetaryProcess(config)
    process, calendar = macro.process, macro.calendar
    financial = OnlineHedgeComparison(
        config.hedge,
        n_steps=config.economy.n_steps,
        start_date=calendar.next_business_day(config.economy.start_date),
        initial_rate=config.initial_rate,
        seed=config.seed,
    )

    def simulate_financial_step(
        ctx: StepContext, settlement: EconomicSettlement
    ) -> FinancialPeriod:
        macro.stage = "financial_transition"
        if macro.latest_actions is None:
            raise ValueError("financial transition requires current policy actions")
        return financial.advance(ctx.step, macro.latest_actions.policy.previous_rate)

    def value_and_hedge(
        ctx: StepContext, period: FinancialPeriod, settlement: EconomicSettlement
    ) -> HedgeValuation:
        macro.stage = "closing_valuation_and_hedge"
        return financial.value_and_rebalance(ctx.step, ctx.step_date, macro.rate)

    def risk(
        ctx: StepContext, value: HedgeValuation, period: FinancialPeriod
    ) -> ConditionalHedgeRisk:
        macro.stage = "conditional_risk"
        return financial.risk(ctx.step)

    engine = macro.engine
    engine.hooks = StepHooks(
        macro.compute_actions,
        macro.clear_and_settle,
        simulate_financial_step,
        value_and_hedge,
        risk,
    )
    steps = []
    invalid_reasons = []
    try:
        with np.errstate(over="raise", invalid="raise", divide="raise"):
            for _ in range(config.economy.n_steps):
                macro.stage = "step_initialization"
                step = engine.advance_step()
                observed = macro.snapshot(step)
                steps.append(
                    MonetaryStep(
                        step.step,
                        observed.economic,
                        observed.policy,
                        observed.adjusted_payroll_target,
                        observed.payroll_multiplier,
                        observed.new_publications,
                        step.financial_step,
                        step.valuation_and_hedge,
                        step.portfolio_risk,
                    )
                )
    except (LedgerError, AgentError, ValueError, ArithmeticError) as exc:
        invalid_reasons.append(
            f"step {engine.clock.step_index} / {macro.stage}: {type(exc).__name__}: {exc}"
        )
    valid = not invalid_reasons
    delta_wealth, mlp_wealth = financial.liquidate() if valid else (None, None)
    payload = {
        "schema_version": 1,
        "accounting_convention": "opening-rate-finance-v1",
        "model_convention": "published-price-policy-feedback-v1",
        "config": asdict(config),
        "valid": valid,
        "invalid_reasons": invalid_reasons,
        "initial_injected_cash": asdict(process.injected),
        "initial_state_hash": process.initial_state_hash,
        "training": financial.training_metadata,
        "initial_delta_hedge": asdict(financial.initial_delta),
        "initial_mlp_hedge": asdict(financial.initial_mlp),
        "steps": [asdict(step) for step in steps],
        "publication_ledger": [asdict(item) for item in macro.publication_ledger],
        "delta_final_wealth": delta_wealth,
        "mlp_final_wealth": mlp_wealth,
        "limitations": LIMITATIONS,
    }
    manifest = RunManifest(
        new_run_id("pmth-monetary"),
        now_iso(),
        config.seed,
        asdict(config),
        compute_result_hash(payload),
    )
    cards = []
    if mlp_wealth is not None:
        card = build_deep_hedge_model_card(
            financial.training.policy,
            config.hedge.n_train_paths,
            financial.path_seed,
            -mlp_wealth,
            -mlp_wealth,
            config.hedge.cvar_alpha,
        )
        cards.append(
            replace(
                card,
                primary_metrics={"realized_terminal_loss": -mlp_wealth},
                training_data_summary=card.training_data_summary
                + f" Policy seed={financial.policy_seed}.",
                metric_uncertainty_note=(
                    "One realized coupled macro-financial path. This is not a sample CVaR estimate "
                    "or policy superiority. Conditional CVaR freezes current holdings/rates."
                ),
                failure_modes=card.failure_modes + LIMITATIONS,
            )
        )
    bundle = build_evidence_bundle(manifest, cards, current_repository_gate_report())
    bundle["monetary"] = payload
    return MonetaryRunResult(
        valid, tuple(invalid_reasons), tuple(steps), delta_wealth, mlp_wealth, manifest, bundle
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--steps", type=int, default=12)
    parser.add_argument("--publication-lag", type=int, default=1)
    parser.add_argument("--payroll-rate-sensitivity", type=float, default=2.0)
    parser.add_argument("--train-paths", type=int, default=1_500)
    parser.add_argument("--train-epochs", type=int, default=60)
    parser.add_argument("--batch-size", type=int, default=256)
    parser.add_argument("--risk-paths", type=int, default=2_000)
    parser.add_argument("--no-productivity-shock", action="store_true")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    try:
        config = MonetaryRunConfig(
            seed=args.seed,
            economy=EconomyRunConfig(
                seed=args.seed,
                n_steps=args.steps,
                productivity_shock_step=None if args.no_productivity_shock else min(4, args.steps),
            ),
            hedge=HedgeComparisonSettings(
                n_train_paths=args.train_paths,
                n_train_epochs=args.train_epochs,
                batch_size=args.batch_size,
                risk_eval_n_paths=args.risk_paths,
            ),
            publication_lag_months=args.publication_lag,
            payroll_rate_sensitivity=args.payroll_rate_sensitivity,
        )
    except ValueError as exc:
        parser.error(str(exc))
    result = run_monetary_simulation(config)
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        export_evidence_bundle(result.evidence_bundle, args.output)
    print(
        json.dumps(
            {
                "valid": result.valid,
                "completed_steps": len(result.steps),
                "invalid_reasons": result.invalid_reasons,
                "delta_final_wealth": result.delta_final_wealth,
                "mlp_final_wealth": result.mlp_final_wealth,
                "result_hash": result.manifest.result_hash,
                "evidence_path": str(args.output) if args.output else None,
            },
            indent=2,
        )
    )
    return 0 if result.valid else 1


if __name__ == "__main__":
    raise SystemExit(main())
