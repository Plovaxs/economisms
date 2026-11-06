"""Single-path self-financing hedge account with explicit event timing.

Rebalance at the observed price, accrue cash over the next interval, then
settle at maturity. ``update`` combines rebalance and accrual for batch
simulator parity; event-driven callers use the two operations separately.
Terminal liquidation has no extra fee, matching the batch convention.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from prometheus.volterra.instruments import OptionType


def _finite(name: str, value: float, *, positive: bool = False) -> None:
    if not math.isfinite(value) or (positive and value <= 0):
        raise ValueError(f"{name} must be finite" + (" and positive" if positive else ""))


@dataclass(frozen=True, slots=True)
class HedgeStepRecord:
    spot: float
    target_holdings: float
    trade: float
    cost: float
    cash_after: float
    """Cash immediately after trading, before the following interval's interest."""


@dataclass(slots=True)
class OnlineHedgeAccount:
    strike: float
    option_type: OptionType
    risk_free_rate: float
    cost_rate: float
    dt: float
    holdings: float = field(default=0.0, init=False)
    cash: float = field(default=0.0, init=False)
    total_cost: float = field(default=0.0, init=False)
    total_turnover: float = field(default=0.0, init=False)
    history: list[HedgeStepRecord] = field(default_factory=list, init=False)
    _initialized: bool = field(default=False, init=False)
    _settled: bool = field(default=False, init=False)

    def __post_init__(self) -> None:
        _finite("strike", self.strike, positive=True)
        _finite("risk_free_rate", self.risk_free_rate)
        _finite("cost_rate", self.cost_rate)
        _finite("dt", self.dt, positive=True)
        if self.cost_rate < 0:
            raise ValueError("cost_rate must be non-negative")
        if self.option_type not in ("call", "put"):
            raise ValueError("option_type must be call or put")

    def _require_open(self) -> None:
        if not self._initialized:
            raise RuntimeError("initialize() must be called first")
        if self._settled:
            raise RuntimeError("account has already settled")

    def initialize(self, premium: float) -> None:
        if self._initialized:
            raise RuntimeError("initialize() must be called exactly once")
        _finite("premium", premium)
        self.cash = premium
        self._initialized = True

    def rebalance(self, spot: float, target_holdings: float) -> HedgeStepRecord:
        """Trade now, without advancing time or accruing interest."""
        self._require_open()
        _finite("spot", spot, positive=True)
        _finite("target_holdings", target_holdings)
        trade = target_holdings - self.holdings
        cost = self.cost_rate * abs(trade) * spot
        cash = self.cash - trade * spot - cost
        _finite("resulting cash", cash)
        self.cash = cash
        self.holdings = target_holdings
        self.total_cost += cost
        self.total_turnover += abs(trade)
        record = HedgeStepRecord(spot, target_holdings, trade, cost, cash)
        self.history.append(record)
        return record

    def accrue(self, risk_free_rate: float | None = None) -> None:
        """Finance cash over one dt, optionally at this interval's new rate."""
        self._require_open()
        rate = self.risk_free_rate if risk_free_rate is None else risk_free_rate
        _finite("risk_free_rate", rate)
        cash = self.cash * math.exp(rate * self.dt)
        _finite("resulting cash", cash)
        self.cash = cash

    def update(self, spot: float, target_holdings: float) -> HedgeStepRecord:
        """Rebalance at t and accrue to t + dt, as in the batch simulator."""
        record = self.rebalance(spot, target_holdings)
        self.accrue()
        return record

    def terminal_loss(self, spot_terminal: float) -> float:
        """Project settlement loss at a price without changing the account."""
        self._require_open()
        _finite("spot_terminal", spot_terminal, positive=True)
        payoff = (
            max(spot_terminal - self.strike, 0.0)
            if self.option_type == "call"
            else max(self.strike - spot_terminal, 0.0)
        )
        return -(self.cash + self.holdings * spot_terminal - payoff)

    def liquidate(self, spot_terminal: float) -> float:
        """Sell holdings, pay the payoff once, and close the account."""
        wealth = -self.terminal_loss(spot_terminal)
        self.cash = wealth
        self.holdings = 0.0
        self._settled = True
        return wealth
