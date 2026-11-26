"""Every parameter of the world in one place, and the three scenarios."""

from __future__ import annotations

from dataclasses import dataclass, field, replace

import numpy as np

REGIMES = ("expansion", "slowdown", "crisis")
ASSETS = ("equity", "bond", "real", "cash")
CRISIS = 2


def _matrix(rows: list[list[float]]) -> np.ndarray:
    return np.array(rows, dtype=np.float64)


@dataclass(frozen=True, slots=True)
class MacroParams:
    """Monthly dynamics. Inflation, rates and the output gap are in percent."""

    inflation_target: float = 2.0
    neutral_real_rate: float = 1.0
    output_persistence: float = 0.90
    rate_sensitivity: float = 0.05
    credit_crunch_drag: float = 0.40
    regime_output_shift: tuple[float, float, float] = (0.0, -0.10, -0.80)
    regime_output_vol: tuple[float, float, float] = (0.25, 0.35, 0.60)
    inflation_persistence: float = 0.85
    phillips_slope: float = 0.12
    inflation_vol: float = 0.25
    supply_shock_probability: float = 0.01
    supply_shock_size: float = 1.5
    taylor_phi_pi: float = 1.5
    taylor_phi_y: float = 0.5
    rate_smoothing: float = 0.80
    rate_max: float = 15.0
    bond_duration: float = 5.0


@dataclass(frozen=True, slots=True)
class MarketParams:
    """Monthly returns by regime: equity, long bond, real assets (cash follows the policy rate)."""

    mu: np.ndarray = field(
        default_factory=lambda: _matrix(
            [[0.008, 0.003, 0.004], [0.002, 0.004, 0.000], [-0.025, 0.007, -0.020]]
        )
    )
    sigma: np.ndarray = field(
        default_factory=lambda: _matrix(
            [[0.035, 0.015, 0.040], [0.050, 0.020, 0.055], [0.090, 0.025, 0.090]]
        )
    )
    equity_bond_corr: tuple[float, float, float] = (0.10, 0.00, -0.30)
    equity_real_corr: tuple[float, float, float] = (0.40, 0.50, 0.70)
    bond_real_corr: tuple[float, float, float] = (0.00, 0.00, -0.10)
    crisis_jump: tuple[float, float, float] = (-0.08, 0.02, -0.06)
    price_impact: float = 1.0
    market_size: float = 1_000.0


@dataclass(frozen=True, slots=True)
class BankParams:
    n_banks: int = 10
    interbank_counterparties: int = 3
    loans: float = 60.0
    securities: float = 25.0
    cash: float = 5.0
    interbank_borrowed: float = 10.0
    deposit_funding: float = 84.0
    securities_equity_share: float = 0.4
    net_interest_margin: float = 0.0025
    base_default_rate: float = 0.0012
    default_sensitivity: float = 0.35
    loss_given_default: float = 0.50
    loan_growth_base: float = 0.0015
    loan_growth_slope: float = 0.002
    capital_trigger: float = 0.05
    fire_sale_fraction: float = 0.10


@dataclass(frozen=True, slots=True)
class HouseholdParams:
    n_households: int = 1_000
    wealth_log_sigma: float = 1.9
    participation_rank: float = 0.40
    income_wealth_correlation: float = 0.5
    income_log_sigma: float = 0.8
    mean_monthly_income: float = 1.0
    consumption_rate: float = 0.92
    wealth_consumption: float = 0.001
    unemployment_benefit: float = 0.5
    base_unemployment: float = 4.5
    okun: float = 0.5


@dataclass(frozen=True, slots=True)
class WorldConfig:
    name: str = "volatile"
    n_months: int = 240
    transition: np.ndarray = field(
        default_factory=lambda: _matrix(
            [[0.975, 0.020, 0.005], [0.080, 0.890, 0.030], [0.100, 0.150, 0.750]]
        )
    )
    macro: MacroParams = field(default_factory=MacroParams)
    market: MarketParams = field(default_factory=MarketParams)
    banks: BankParams = field(default_factory=BankParams)
    households: HouseholdParams = field(default_factory=HouseholdParams)

    def __post_init__(self) -> None:
        if self.n_months < 24:
            raise ValueError("n_months must be at least 24")
        if not np.allclose(self.transition.sum(axis=1), 1.0):
            raise ValueError("every row of the transition matrix must sum to 1")


def scale_crisis_entry(transition: np.ndarray, factor: float) -> np.ndarray:
    """Multiply the chance of entering the crisis regime from expansion and slowdown by `factor`
    (at most 0.5), taking the difference from the probability of staying."""
    scaled = transition.copy()
    for row in (0, 1):
        other = 1.0 - transition[row, row] - transition[row, CRISIS]
        entry = min(transition[row, CRISIS] * factor, 0.5)
        scaled[row, CRISIS] = entry
        scaled[row, row] = 1.0 - entry - other
    return scaled


def scenario(name: str) -> WorldConfig:
    """`calm` (rare, mild crises), `volatile` (the default) and `stressed` (frequent crises, more
    leveraged and loss-prone banks, a deeper recession)."""
    base = WorldConfig()
    if name == "volatile":
        return base
    if name == "calm":
        return replace(
            base,
            name="calm",
            transition=scale_crisis_entry(base.transition, 0.4),
            macro=replace(base.macro, regime_output_shift=(0.0, -0.05, -0.40)),
        )
    if name == "stressed":
        return replace(
            base,
            name="stressed",
            transition=scale_crisis_entry(base.transition, 2.5),
            macro=replace(base.macro, regime_output_shift=(0.0, -0.15, -1.10)),
            banks=replace(
                base.banks, deposit_funding=86.0, loss_given_default=0.60, default_sensitivity=0.45
            ),
        )
    raise ValueError(f"unknown scenario {name!r}; choose calm, volatile or stressed")


SCENARIOS = ("calm", "volatile", "stressed")
