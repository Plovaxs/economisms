"""Stateful delta/MLP comparison with explicit opening and closing rates.

Advance a period at its opening rate; value/rebalance at its closing rate.
Conditional risk freezes the closing rate and current holdings. Economic
ledger transactions remain separate from these floating-point accounts.
Black-Scholes marks assume a flat closing rate to expiry; endogenous future
rate changes are not solved under a joint stochastic-rate Q model.
"""

from __future__ import annotations

import hashlib
import math
from dataclasses import asdict, dataclass
from datetime import date
from typing import Any

import numpy as np

from prometheus.core.seeds import SeedHierarchy
from prometheus.evidence.repository_status import policy_content_hash
from prometheus.hedging.baseline import black_scholes_delta_vectorized
from prometheus.hedging.deep_hedge import evaluate_policy_action, train_deep_hedge
from prometheus.hedging.online import OnlineHedgeAccount
from prometheus.stochastica.gbm import simulate_gbm_paths
from prometheus.titan.risk_metrics import historical_expected_shortfall
from prometheus.volterra.black_scholes import black_scholes_price
from prometheus.volterra.instruments import EuropeanOption, OptionType
from prometheus.volterra.market import MarketSnapshot

DT = 1.0 / 12.0


@dataclass(frozen=True, slots=True)
class HedgeComparisonSettings:
    spot0: float = 100.0
    strike: float = 100.0
    option_type: OptionType = "call"
    volatility: float = 0.2
    equity_risk_premium: float = 0.04
    cost_rate: float = 0.005
    cvar_alpha: float = 0.9
    n_train_paths: int = 1_500
    n_train_epochs: int = 60
    batch_size: int = 256
    learning_rate: float = 0.01
    turnover_penalty: float = 0.0
    risk_eval_n_paths: int = 2_000

    def __post_init__(self) -> None:
        for name in ("n_train_paths", "n_train_epochs", "batch_size", "risk_eval_n_paths"):
            if type(getattr(self, name)) is not int or getattr(self, name) < 1:
                raise ValueError(f"{name} must be a positive integer")
        if self.batch_size > self.n_train_paths:
            raise ValueError("batch_size must not exceed n_train_paths")
        for name in (
            "spot0",
            "strike",
            "volatility",
            "equity_risk_premium",
            "cost_rate",
            "cvar_alpha",
            "learning_rate",
            "turnover_penalty",
        ):
            value = getattr(self, name)
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(value)
            ):
                raise ValueError(f"{name} must be finite numeric data")
        if min(self.spot0, self.strike, self.volatility, self.learning_rate) <= 0:
            raise ValueError("spot, strike, volatility and learning rate must be positive")
        if min(self.cost_rate, self.turnover_penalty) < 0 or not 0 < self.cvar_alpha < 1:
            raise ValueError("costs/penalty must be non-negative and cvar_alpha in (0, 1)")
        if self.option_type not in ("call", "put"):
            raise ValueError("option_type must be call or put")


@dataclass(frozen=True, slots=True)
class FinancialPeriod:
    step: int
    opening_spot: float
    closing_spot: float
    funding_rate: float
    physical_drift: float


@dataclass(frozen=True, slots=True)
class HedgeValuation:
    step: int
    remaining_years: float
    closing_rate: float
    option_value: float
    delta_holdings: float
    mlp_holdings: float
    delta_cash: float
    mlp_cash: float
    delta_cost: float
    mlp_cost: float
    delta_turnover: float
    mlp_turnover: float


@dataclass(frozen=True, slots=True)
class ConditionalHedgeRisk:
    delta_cvar: float
    mlp_cvar: float
    remaining_years: float
    frozen_rate: float


class OnlineHedgeComparison:
    def __init__(
        self,
        settings: HedgeComparisonSettings,
        *,
        n_steps: int,
        start_date: date,
        initial_rate: float,
        seed: int,
    ) -> None:
        if type(n_steps) is not int or n_steps < 1 or not math.isfinite(initial_rate):
            raise ValueError("positive n_steps and a finite initial rate are required")
        self.settings, self.n_steps = settings, n_steps
        self.maturity = n_steps * DT
        self.streams = SeedHierarchy(seed)
        self.path_seed = int(self.streams.stream("training-path-seed").integers(0, 2**32))
        self.policy_seed = int(self.streams.stream("training-policy-seed").integers(0, 2**32))
        self.premium = float(
            black_scholes_price(
                MarketSnapshot(start_date, settings.spot0, initial_rate, settings.volatility),
                EuropeanOption(settings.strike, self.maturity, settings.option_type),
            )
        )
        paths = simulate_gbm_paths(
            settings.spot0,
            initial_rate + settings.equity_risk_premium,
            settings.volatility,
            self.maturity,
            n_steps,
            settings.n_train_paths,
            np.random.default_rng(self.path_seed),
        )
        self.training = train_deep_hedge(
            paths,
            DT,
            settings.strike,
            self.maturity,
            settings.option_type,
            initial_rate,
            settings.cost_rate,
            self.premium,
            cvar_alpha=settings.cvar_alpha,
            turnover_penalty=settings.turnover_penalty,
            n_epochs=settings.n_train_epochs,
            batch_size=settings.batch_size,
            learning_rate=settings.learning_rate,
            seed=self.policy_seed,
        )
        self.training_metadata: dict[str, Any] = {
            "settings": asdict(settings),
            "n_steps": n_steps,
            "initial_rate": initial_rate,
            "maturity_years": self.maturity,
            "initial_premium": self.premium,
            "path_seed": self.path_seed,
            "policy_seed": self.policy_seed,
            "training_data_sha256": hashlib.sha256(
                paths.astype("<f8", copy=False).tobytes()
            ).hexdigest(),
            "training_data_encoding": "row-major float64 little-endian",
            "policy_content_hash": policy_content_hash(self.training.policy),
            "objective_history": self.training.objective_history,
        }
        self.delta = OnlineHedgeAccount(
            settings.strike, settings.option_type, initial_rate, settings.cost_rate, DT
        )
        self.mlp = OnlineHedgeAccount(
            settings.strike, settings.option_type, initial_rate, settings.cost_rate, DT
        )
        self.delta.initialize(self.premium)
        self.mlp.initialize(self.premium)
        self.spot = settings.spot0
        self._advanced = self._valued = 0
        self._last_risk: ConditionalHedgeRisk | None = None
        self._closing_rate = initial_rate
        self._closed = False
        self._rebalance(self.maturity, initial_rate)
        self.initial_delta = self.delta.history[0]
        self.initial_mlp = self.mlp.history[0]

    def _rebalance(self, remaining: float, rate: float) -> None:
        target = float(
            black_scholes_delta_vectorized(
                np.array([self.spot]),
                self.settings.strike,
                rate,
                self.settings.volatility,
                remaining,
                self.settings.option_type,
            )[0]
        )
        action = evaluate_policy_action(
            self.training.policy,
            self.spot,
            remaining / self.maturity,
            self.mlp.holdings,
            self.settings.strike,
        )
        self.delta.rebalance(self.spot, target)
        self.mlp.rebalance(self.spot, action)

    def advance(self, step: int, funding_rate: float) -> FinancialPeriod:
        if (
            type(step) is not int
            or self._closed
            or step != self._advanced + 1
            or self._valued != self._advanced
            or step > self.n_steps
        ):
            raise ValueError("financial advance requires the next unprocessed period")
        if not math.isfinite(funding_rate):
            raise ValueError("funding rate must be finite")
        before = self.spot
        drift = funding_rate + self.settings.equity_risk_premium
        self.spot = float(
            simulate_gbm_paths(
                before,
                drift,
                self.settings.volatility,
                DT,
                1,
                1,
                self.streams.stream("financial-market"),
            )[0, -1]
        )
        self.delta.accrue(funding_rate)
        self.mlp.accrue(funding_rate)
        self._advanced = step
        self._last_risk = None
        return FinancialPeriod(step, before, self.spot, funding_rate, drift)

    def value_and_rebalance(
        self, step: int, step_date: date, closing_rate: float
    ) -> HedgeValuation:
        if self._closed or step != self._advanced or self._valued >= step:
            raise ValueError("valuation must follow exactly one financial advance")
        if not math.isfinite(closing_rate):
            raise ValueError("closing rate must be finite")
        remaining = (self.n_steps - step) * DT
        if remaining:
            price = float(
                black_scholes_price(
                    MarketSnapshot(step_date, self.spot, closing_rate, self.settings.volatility),
                    EuropeanOption(self.settings.strike, remaining, self.settings.option_type),
                )
            )
            self._rebalance(remaining, closing_rate)
        else:
            price = float(self._payoff(np.array([self.spot]))[0])
        self._valued = step
        self._closing_rate = closing_rate
        return HedgeValuation(
            step,
            remaining,
            closing_rate,
            price,
            self.delta.holdings,
            self.mlp.holdings,
            self.delta.cash,
            self.mlp.cash,
            self.delta.total_cost,
            self.mlp.total_cost,
            self.delta.total_turnover,
            self.mlp.total_turnover,
        )

    def _payoff(self, spot: np.ndarray) -> np.ndarray:
        intrinsic = (
            spot - self.settings.strike
            if self.settings.option_type == "call"
            else self.settings.strike - spot
        )
        return np.maximum(intrinsic, 0.0)

    def risk(self, step: int) -> ConditionalHedgeRisk:
        if self._closed or step < 1 or step != self._valued or step != self._advanced:
            raise ValueError("risk must follow valuation of the current period")
        if self._last_risk is not None:
            return self._last_risk
        closing_rate = self._closing_rate
        remaining = (self.n_steps - step) * DT
        if not remaining:
            self._last_risk = ConditionalHedgeRisk(
                self.delta.terminal_loss(self.spot),
                self.mlp.terminal_loss(self.spot),
                0.0,
                closing_rate,
            )
            return self._last_risk
        terminal = simulate_gbm_paths(
            self.spot,
            closing_rate + self.settings.equity_risk_premium,
            self.settings.volatility,
            remaining,
            1,
            self.settings.risk_eval_n_paths,
            self.streams.stream(f"conditional-risk/{step}"),
        )[:, -1]
        payoff = self._payoff(terminal)
        accrual = math.exp(closing_rate * remaining)
        self._last_risk = ConditionalHedgeRisk(
            historical_expected_shortfall(
                payoff - self.delta.cash * accrual - self.delta.holdings * terminal,
                self.settings.cvar_alpha,
            ),
            historical_expected_shortfall(
                payoff - self.mlp.cash * accrual - self.mlp.holdings * terminal,
                self.settings.cvar_alpha,
            ),
            remaining,
            closing_rate,
        )
        return self._last_risk

    def liquidate(self) -> tuple[float, float]:
        if self._closed or self._valued != self.n_steps:
            raise ValueError("liquidation requires exactly one completed expiry valuation")
        wealth = self.delta.liquidate(self.spot), self.mlp.liquidate(self.spot)
        self._closed = True
        return wealth
