"""Self-financing discrete-time hedge simulation.

HDG-01: wealth and terminal loss with explicit cash financing. The hedger
has written (sold) one option and receives `initial_premium` in cash at
t=0; cash accrues interest at `risk_free_rate` between rehedges; every
trade both moves cash by -trade_size * price and pays a proportional
transaction cost. At maturity, remaining holdings are liquidated at the
terminal price and the option's payoff is paid out. This is a single,
shared simulator used for every hedging policy in this package (baseline
and learned alike) so that no policy can appear to outperform another by
using a different accounting convention (HDG-13).
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from prometheus.volterra.instruments import OptionType


@dataclass(frozen=True, slots=True)
class HedgeSimulationResult:
    terminal_loss: np.ndarray
    total_cost: np.ndarray
    total_turnover: np.ndarray
    holdings_path: np.ndarray


def simulate_self_financing_hedge(
    price_paths: np.ndarray,
    dt: float,
    strike: float,
    option_type: OptionType,
    risk_free_rate: float,
    cost_rate: float,
    initial_premium: float,
    hedge_ratios: np.ndarray,
    *,
    funding_rates: np.ndarray | None = None,
) -> HedgeSimulationResult:
    """Trade at each interval's opening, then accrue at its funding rate.

    ``funding_rates`` optionally supplies one rate per interval (shape
    ``(n_steps,)``) or per path/interval (``(n_paths, n_steps)``). It is a
    realized funding schedule, never an input to hedge decisions. The
    scalar rate retains the original constant-rate behavior when omitted.
    """
    n_paths, n_plus_1 = price_paths.shape
    n_steps = n_plus_1 - 1
    if hedge_ratios.shape != (n_paths, n_steps):
        raise ValueError(
            f"hedge_ratios must have shape {(n_paths, n_steps)}, got {hedge_ratios.shape}"
        )
    if cost_rate < 0:
        raise ValueError("cost_rate must be non-negative")
    if dt <= 0:
        raise ValueError("dt must be positive")

    holdings = np.zeros(n_paths)
    cash = np.full(n_paths, float(initial_premium))
    total_cost = np.zeros(n_paths)
    total_turnover = np.zeros(n_paths)
    holdings_path = np.empty((n_paths, n_steps + 1))
    if funding_rates is None:
        cash_accrual = np.full((n_steps,), np.exp(risk_free_rate * dt))
    else:
        rates = np.asarray(funding_rates, dtype=float)
        if rates.shape not in ((n_steps,), (n_paths, n_steps)) or not np.all(np.isfinite(rates)):
            raise ValueError("funding_rates require finite interval or path/interval rates")
        cash_accrual = np.exp(rates * dt)
    if not np.all(np.isfinite(cash_accrual)):
        raise ValueError("funding rates produce non-finite accrual")

    for t in range(n_steps):
        s_t = price_paths[:, t]
        target = hedge_ratios[:, t]
        trade = target - holdings
        cost = cost_rate * np.abs(trade) * s_t

        # Trade at t, then finance the resulting cash over [t, t + dt].
        accrual = cash_accrual[t] if cash_accrual.ndim == 1 else cash_accrual[:, t]
        cash = (cash - trade * s_t - cost) * accrual
        holdings = target

        total_cost += cost
        total_turnover += np.abs(trade)
        holdings_path[:, t] = holdings

    holdings_path[:, n_steps] = holdings  # held unchanged through to liquidation

    s_terminal = price_paths[:, -1]
    if option_type == "call":
        payoff = np.maximum(s_terminal - strike, 0.0)
    else:
        payoff = np.maximum(strike - s_terminal, 0.0)

    final_wealth = cash + holdings * s_terminal - payoff
    terminal_loss = -final_wealth

    return HedgeSimulationResult(
        terminal_loss=terminal_loss,
        total_cost=total_cost,
        total_turnover=total_turnover,
        holdings_path=holdings_path,
    )
