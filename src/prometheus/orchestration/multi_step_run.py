"""A reproducible monthly scenario executed through all five StepHooks.

Initial hedges trade at t=0. Each month applies the current policy rule,
settles labor/goods, moves the market and finances existing positions at
that interval's rate, then values and rehedges at the observed new spot.
At expiry valuation is the exact payoff and no new hedge is opened.

Conditional CVaR projects *portfolio losses* with frozen holdings, constant
current rates and physical GBM drift, without anticipating future shocks
or rehedging. It is a local diagnostic, not a full dynamic-policy forecast.
Monthly financial dt is 1/12 year, independent of business-day date snaps.
"""

from __future__ import annotations

import argparse
import json
import math
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass, field, fields, replace
from datetime import date
from pathlib import Path
from typing import Any

import numpy as np

from prometheus.core.calendar import BusinessDayCalendar
from prometheus.core.ledger import LedgerError
from prometheus.core.money import Money
from prometheus.core.seeds import SeedHierarchy
from prometheus.econosim.agents import AgentError, InsufficientFundsError
from prometheus.econosim.economy import Economy
from prometheus.econosim.market_clearing import (
    ClearingResult,
    apply_goods_clearing_to_ledger,
    apply_labor_clearing_to_ledger,
    clear_quantity_market,
)
from prometheus.econosim.policy_rate import PolicyRateRule
from prometheus.econosim.shocks import Shock
from prometheus.econosim.step_hooks import StepContext, StepHooks
from prometheus.econosim.time_engine import MacroTimeEngine
from prometheus.evidence.export import build_evidence_bundle, export_evidence_bundle
from prometheus.evidence.repository_status import (
    build_deep_hedge_model_card,
    current_repository_gate_report,
    policy_content_hash,
)
from prometheus.experiments.manifest import RunManifest, compute_result_hash, new_run_id, now_iso
from prometheus.hedging.baseline import black_scholes_delta_vectorized
from prometheus.hedging.deep_hedge import evaluate_policy_action, train_deep_hedge
from prometheus.hedging.online import HedgeStepRecord, OnlineHedgeAccount
from prometheus.stochastica.gbm import simulate_gbm_paths
from prometheus.titan.risk_metrics import historical_expected_shortfall
from prometheus.volterra.black_scholes import black_scholes_price
from prometheus.volterra.instruments import EuropeanOption, OptionType
from prometheus.volterra.market import MarketSnapshot

DT = 1.0 / 12.0
LIMITATIONS = (
    "Synthetic, single-asset GBM; one firm and two households; prices/wages are exogenous.",
    "Monthly dt=1/12; business-day dates are labels, not an actual/365 day-count basis.",
    "The current step's policy rate funds that entire interval; hedges use observed spots.",
    "Hedge accounts are separate from the economic ledger; there is no joint balance sheet.",
    "Conditional CVaR freezes holdings and the current rate, with physical GBM continuation; "
    "it does not simulate future rehedging, policy shocks or parameter uncertainty.",
    "Training uses constant initial-rate GBM; the scenario can change rates out of sample.",
    "Terminal liquidation is frictionless, matching the shared batch hedge convention.",
    "One realized path cannot establish policy superiority; no independent review exists.",
)


@dataclass(frozen=True, slots=True)
class MultiStepRunConfig:
    seed: int = 0
    start_date: date = date(2026, 1, 2)
    n_steps: int = 12
    initial_policy_rate: float = 0.03
    policy_rate_neutral: float = 0.03
    policy_rate_mean_reversion: float = 0.5
    policy_shock_step: int | None = 4
    policy_shock_bps: float = 100.0
    equity_risk_premium: float = 0.04
    volatility: float = 0.2
    spot0: float = 100.0
    strike: float = 100.0
    option_maturity_years: float | None = None
    option_type: OptionType = "call"
    cost_rate: float = 0.005
    firm_labor_demand_per_step: float = 18.0
    household_labor_supply_per_step: float = 10.0
    wage_rate_per_hour: Money = field(default_factory=lambda: Money(1000))
    goods_price: Money = field(default_factory=lambda: Money(100))
    firm_goods_supply_per_step: float = 1_000.0
    consumption_propensity: float = 1.0
    firm_seed_capital: Money = field(default_factory=lambda: Money(200_000))
    n_train_paths: int = 1_500
    n_train_epochs: int = 60
    cvar_alpha: float = 0.9
    risk_eval_n_paths: int = 2_000

    @property
    def maturity_years(self) -> float:
        return self.n_steps * DT

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> MultiStepRunConfig:
        """Decode the complete exported configuration, with no silent defaults."""
        if set(payload) != {item.name for item in fields(cls)}:
            raise ValueError("monthly replay requires exactly the complete configuration fields")
        values = dict(payload)
        try:
            if isinstance(values["start_date"], str):
                values["start_date"] = date.fromisoformat(values["start_date"])
            for name in ("wage_rate_per_hour", "goods_price", "firm_seed_capital"):
                if isinstance(values[name], Mapping):
                    values[name] = Money(**values[name])
            return cls(**values)
        except (TypeError, AttributeError) as exc:
            raise ValueError(f"invalid monthly replay configuration: {exc}") from exc

    def __post_init__(self) -> None:
        for name in ("seed", "n_steps", "n_train_paths", "n_train_epochs", "risk_eval_n_paths"):
            value = getattr(self, name)
            minimum = 0 if name == "seed" else 1
            if type(value) is not int or value < minimum:
                raise ValueError(f"{name} must be an integer >= {minimum}")
        if type(self.start_date) is not date:
            raise ValueError("start_date must be a date")
        if self.policy_shock_step is not None and (
            type(self.policy_shock_step) is not int
            or not 1 <= self.policy_shock_step <= self.n_steps
        ):
            raise ValueError("policy_shock_step must be None or an integer within [1, n_steps]")
        for name in (
            "initial_policy_rate",
            "policy_rate_neutral",
            "policy_rate_mean_reversion",
            "policy_shock_bps",
            "equity_risk_premium",
            "volatility",
            "spot0",
            "strike",
            "cost_rate",
            "firm_labor_demand_per_step",
            "household_labor_supply_per_step",
            "firm_goods_supply_per_step",
            "consumption_propensity",
            "cvar_alpha",
        ):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ValueError(f"{name} must be a finite number")
            if not math.isfinite(value):
                raise ValueError(f"{name} must be finite")
        for name in ("volatility", "spot0", "strike"):
            if getattr(self, name) <= 0:
                raise ValueError(f"{name} must be positive")
        for name in (
            "policy_rate_mean_reversion",
            "cost_rate",
            "firm_labor_demand_per_step",
            "household_labor_supply_per_step",
            "firm_goods_supply_per_step",
        ):
            if getattr(self, name) < 0:
                raise ValueError(f"{name} must be non-negative")
        if not 0 <= self.consumption_propensity <= 1:
            raise ValueError("consumption_propensity must be in [0, 1]")
        if not 0 < self.cvar_alpha < 1:
            raise ValueError("cvar_alpha must be in (0, 1)")
        for name in ("wage_rate_per_hour", "goods_price", "firm_seed_capital"):
            amount = getattr(self, name)
            if not isinstance(amount, Money) or amount.currency != "USD" or amount.minor_units <= 0:
                raise ValueError(f"{name} must be positive USD Money")
        if self.option_type not in ("call", "put"):
            raise ValueError("option_type must be call or put")
        if self.option_maturity_years is not None and (
            isinstance(self.option_maturity_years, bool)
            or not isinstance(self.option_maturity_years, (int, float))
            or not math.isfinite(self.option_maturity_years)
            or not math.isclose(self.option_maturity_years, self.maturity_years)
        ):
            raise ValueError("option_maturity_years must equal n_steps / 12")


@dataclass(frozen=True, slots=True)
class StepSummary:
    step: int
    step_date: date
    policy_rate: float
    spot: float
    remaining_years: float
    black_scholes_price: float
    delta_holdings: float
    mlp_holdings: float
    delta_cash: float
    mlp_cash: float
    delta_cost: float
    mlp_cost: float
    delta_turnover: float
    mlp_turnover: float
    delta_cvar: float
    mlp_cvar: float
    labor_realized_hours: float
    goods_realized_quantity: float
    labor_residual: float
    goods_residual: float
    firm_cash_minor: int
    household_cash_minor: tuple[int, ...]
    ledger_state_hash: str


@dataclass(frozen=True, slots=True)
class MultiStepRunResult:
    valid: bool
    invalid_reasons: tuple[str, ...]
    steps: tuple[StepSummary, ...]
    initial_premium: float
    initial_delta_hedge: HedgeStepRecord
    initial_mlp_hedge: HedgeStepRecord
    delta_final_wealth: float | None
    mlp_final_wealth: float | None
    manifest: RunManifest
    evidence_bundle: dict[str, Any]
    limitations: tuple[str, ...] = LIMITATIONS


@dataclass(frozen=True, slots=True)
class _Actions:
    labor_demand: float
    labor_supply: dict[str, float]


@dataclass(frozen=True, slots=True)
class _Settlement:
    labor: ClearingResult
    goods: ClearingResult


def _payoff(spot: np.ndarray, config: MultiStepRunConfig) -> np.ndarray:
    intrinsic = spot - config.strike if config.option_type == "call" else config.strike - spot
    return np.maximum(intrinsic, 0.0)


def run_multi_step_simulation(config: MultiStepRunConfig) -> MultiStepRunResult:
    """Run a complete scenario; failures retain completed steps and an invalid manifest.

    Failed steps are not rolled back or resumed. Their partial state is not
    reported as a completed step and no terminal wealth is published.
    """
    seeds = SeedHierarchy(config.seed)
    train_path_seed = int(seeds.stream("training-path-seed").integers(0, 2**32))
    policy_seed = int(seeds.stream("training-policy-seed").integers(0, 2**32))
    train_paths = simulate_gbm_paths(
        config.spot0,
        config.initial_policy_rate + config.equity_risk_premium,
        config.volatility,
        config.maturity_years,
        config.n_steps,
        config.n_train_paths,
        np.random.default_rng(train_path_seed),
    )
    calendar = BusinessDayCalendar()
    start = calendar.next_business_day(config.start_date)
    market0 = MarketSnapshot(start, config.spot0, config.initial_policy_rate, config.volatility)
    premium = black_scholes_price(
        market0, EuropeanOption(config.strike, config.maturity_years, config.option_type)
    )
    training = train_deep_hedge(
        train_paths,
        DT,
        config.strike,
        config.maturity_years,
        config.option_type,
        config.initial_policy_rate,
        config.cost_rate,
        premium,
        cvar_alpha=config.cvar_alpha,
        n_epochs=config.n_train_epochs,
        batch_size=min(256, config.n_train_paths),
        seed=policy_seed,
    )
    economy = Economy()
    firm = economy.add_firm("firm-1")
    households = {name: economy.add_household(name) for name in ("hh-1", "hh-2")}
    for household in households.values():
        household.receive_income(Money(100_000) + config.firm_seed_capital)
    households["hh-1"].consume(firm, config.firm_seed_capital)
    rule = PolicyRateRule(config.policy_rate_neutral, config.policy_rate_mean_reversion, DT)
    central_bank = economy.add_central_bank("fed", rule, config.initial_policy_rate)
    delta_account = OnlineHedgeAccount(
        config.strike, config.option_type, config.initial_policy_rate, config.cost_rate, DT
    )
    mlp_account = OnlineHedgeAccount(
        config.strike, config.option_type, config.initial_policy_rate, config.cost_rate, DT
    )
    delta_account.initialize(premium)
    mlp_account.initialize(premium)

    def rebalance(spot: float, remaining: float) -> None:
        delta_target = float(
            black_scholes_delta_vectorized(
                np.array([spot]),
                config.strike,
                central_bank.current_rate,
                config.volatility,
                remaining,
                config.option_type,
            )[0]
        )
        mlp_target = evaluate_policy_action(
            training.policy,
            spot,
            remaining / config.maturity_years,
            mlp_account.holdings,
            config.strike,
        )
        delta_account.rebalance(spot, delta_target)
        mlp_account.rebalance(spot, mlp_target)

    rebalance(config.spot0, config.maturity_years)
    initial_delta = delta_account.history[0]
    initial_mlp = mlp_account.history[0]
    spot = config.spot0
    step_summaries: list[StepSummary] = []
    invalid_reasons: list[str] = []

    def compute_actions(ctx: StepContext) -> _Actions:
        shocks = list(ctx.shocks)
        if ctx.step == config.policy_shock_step and config.policy_shock_bps != 0:
            shocks.append(
                Shock("known-shock", ctx.step, "policy_rate", config.policy_shock_bps / 10_000.0)
            )
        central_bank.step(shocks)
        return _Actions(
            config.firm_labor_demand_per_step,
            {name: config.household_labor_supply_per_step for name in households},
        )

    def clear_and_settle(ctx: StepContext, actions: _Actions) -> _Settlement:
        labor = clear_quantity_market({firm.agent_id: actions.labor_demand}, actions.labor_supply)
        # Preflight the entire wage bill before posting any household payment.
        wages = {
            name: int(hours * config.wage_rate_per_hour.minor_units)
            for name, hours in labor.realized_sell_quantities.items()
        }
        wage_bill = Money(sum(wages.values()))
        if firm.cash_balance < wage_bill:
            raise InsufficientFundsError(firm.agent_id, wage_bill, firm.cash_balance)
        apply_labor_clearing_to_ledger(
            labor, households, firm, config.wage_rate_per_hour, step=ctx.step
        )
        # Spend only realized, integer-rounded wage income, never desired wages.
        goods = clear_quantity_market(
            {
                name: (wage * config.consumption_propensity) / config.goods_price.minor_units
                for name, wage in wages.items()
            },
            {firm.agent_id: config.firm_goods_supply_per_step},
        )
        apply_goods_clearing_to_ledger(goods, firm, households, config.goods_price, step=ctx.step)
        return _Settlement(labor, goods)

    def simulate_financial_step(ctx: StepContext, settlement: _Settlement) -> float:
        nonlocal spot
        spot = float(
            simulate_gbm_paths(
                spot,
                central_bank.current_rate + config.equity_risk_premium,
                config.volatility,
                DT,
                n_steps=1,
                n_paths=1,
                rng=seeds.stream("financial-market"),
            )[0, -1]
        )
        delta_account.accrue(central_bank.current_rate)
        mlp_account.accrue(central_bank.current_rate)
        return spot

    def value_and_hedge(ctx: StepContext, price: float, settlement: _Settlement) -> float:
        remaining = (config.n_steps - ctx.step) * DT
        if remaining == 0:
            return float(_payoff(np.array([price]), config)[0])
        market = MarketSnapshot(ctx.step_date, price, central_bank.current_rate, config.volatility)
        value = black_scholes_price(
            market, EuropeanOption(config.strike, remaining, config.option_type)
        )
        rebalance(price, remaining)
        return value

    def compute_portfolio_risk(ctx: StepContext, value: float, price: float) -> tuple[float, float]:
        remaining = (config.n_steps - ctx.step) * DT
        if remaining == 0:
            return delta_account.terminal_loss(price), mlp_account.terminal_loss(price)
        terminal = simulate_gbm_paths(
            price,
            central_bank.current_rate + config.equity_risk_premium,
            config.volatility,
            remaining,
            n_steps=1,
            n_paths=config.risk_eval_n_paths,
            rng=seeds.stream(f"conditional-risk/{ctx.step}"),
        )[:, -1]
        payoff = _payoff(terminal, config)
        accrual = math.exp(central_bank.current_rate * remaining)
        delta_losses = payoff - delta_account.cash * accrual - delta_account.holdings * terminal
        mlp_losses = payoff - mlp_account.cash * accrual - mlp_account.holdings * terminal
        return (
            historical_expected_shortfall(delta_losses, config.cvar_alpha),
            historical_expected_shortfall(mlp_losses, config.cvar_alpha),
        )

    hooks = StepHooks(
        compute_actions,
        clear_and_settle,
        simulate_financial_step,
        value_and_hedge,
        compute_portfolio_risk,
    )
    engine = MacroTimeEngine(economy, calendar, start, hooks=hooks)
    try:
        with np.errstate(over="raise", invalid="raise", divide="raise"):
            for _ in range(config.n_steps):
                step = engine.advance_step()
                settlement: _Settlement = step.settlement
                step_summaries.append(
                    StepSummary(
                        step.step,
                        step.step_date,
                        central_bank.current_rate,
                        spot,
                        (config.n_steps - step.step) * DT,
                        step.valuation_and_hedge,
                        delta_account.holdings,
                        mlp_account.holdings,
                        delta_account.cash,
                        mlp_account.cash,
                        delta_account.total_cost,
                        mlp_account.total_cost,
                        delta_account.total_turnover,
                        mlp_account.total_turnover,
                        step.portfolio_risk[0],
                        step.portfolio_risk[1],
                        settlement.labor.total_realized_quantity,
                        settlement.goods.total_realized_quantity,
                        settlement.labor.clearing_residual,
                        settlement.goods.clearing_residual,
                        firm.cash_balance.minor_units,
                        tuple(hh.cash_balance.minor_units for hh in households.values()),
                        step.state_hash,
                    )
                )
    except (LedgerError, AgentError, ValueError, ArithmeticError) as exc:
        invalid_reasons.append(f"step {engine.clock.step_index}: {type(exc).__name__}: {exc}")

    valid = not invalid_reasons
    delta_wealth = delta_account.liquidate(spot) if valid else None
    mlp_wealth = mlp_account.liquidate(spot) if valid else None
    config_payload = asdict(config)
    config_payload["option_maturity_years"] = config.maturity_years
    payload = {
        "schema_version": 1,
        "accounting_convention": "trade-then-accrue-v1",
        "config": config_payload,
        "valid": valid,
        "invalid_reasons": invalid_reasons,
        "initial_premium": premium,
        "initial_delta_hedge": asdict(initial_delta),
        "initial_mlp_hedge": asdict(initial_mlp),
        "steps": [asdict(step) for step in step_summaries],
        "delta_final_wealth": delta_wealth,
        "mlp_final_wealth": mlp_wealth,
        "training_path_seed": train_path_seed,
        "training_policy_seed": policy_seed,
        "policy_content_hash": policy_content_hash(training.policy),
        "training_objective_history": training.objective_history,
        "limitations": LIMITATIONS,
    }
    manifest = RunManifest(
        new_run_id("pmth-multistep"),
        now_iso(),
        config.seed,
        config_payload,
        compute_result_hash(payload),
    )
    cards = []
    if mlp_wealth is not None:
        # A single realized loss is not a CVaR estimate or a held-out benchmark.
        card = build_deep_hedge_model_card(
            training.policy,
            config.n_train_paths,
            train_path_seed,
            -mlp_wealth,
            -mlp_wealth,
            config.cvar_alpha,
        )
        cards.append(
            replace(
                card,
                primary_metrics={"realized_terminal_loss": -mlp_wealth},
                metric_uncertainty_note=(
                    "One independent realized scenario, not an estimate of CVaR "
                    "or policy superiority. "
                    "Per-step conditional risk uses frozen holdings and constant current rates."
                ),
                training_data_summary=card.training_data_summary + f" Policy seed={policy_seed}.",
                failure_modes=card.failure_modes + LIMITATIONS,
            )
        )
    bundle = build_evidence_bundle(manifest, cards, current_repository_gate_report())
    bundle["simulation"] = payload
    return MultiStepRunResult(
        valid,
        tuple(invalid_reasons),
        tuple(step_summaries),
        premium,
        initial_delta,
        initial_mlp,
        delta_wealth,
        mlp_wealth,
        manifest,
        bundle,
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--steps", type=int, default=12)
    parser.add_argument("--start-date", type=date.fromisoformat, default=date(2026, 1, 2))
    parser.add_argument("--train-paths", type=int, default=1_500)
    parser.add_argument("--train-epochs", type=int, default=60)
    parser.add_argument("--risk-paths", type=int, default=2_000)
    parser.add_argument("--option-type", choices=("call", "put"), default="call")
    shock = parser.add_mutually_exclusive_group()
    shock.add_argument("--policy-shock-step", type=int)
    shock.add_argument("--no-shock", action="store_true")
    parser.add_argument("--policy-shock-bps", type=float, default=100.0)
    parser.add_argument("--output", type=Path, help="Export the full evidence bundle as JSON")
    args = parser.parse_args(argv)
    shock_step = (
        args.policy_shock_step if args.policy_shock_step is not None else min(4, args.steps)
    )
    try:
        config = MultiStepRunConfig(
            seed=args.seed,
            start_date=args.start_date,
            n_steps=args.steps,
            n_train_paths=args.train_paths,
            n_train_epochs=args.train_epochs,
            risk_eval_n_paths=args.risk_paths,
            option_type=args.option_type,
            policy_shock_step=None if args.no_shock else shock_step,
            policy_shock_bps=args.policy_shock_bps,
        )
    except ValueError as exc:
        parser.error(str(exc))
    result = run_multi_step_simulation(config)
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
                "evidence_path": str(args.output) if args.output is not None else None,
            },
            indent=2,
        )
    )
    return 0 if result.valid else 1


if __name__ == "__main__":
    raise SystemExit(main())
