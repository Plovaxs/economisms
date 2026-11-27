"""Every parameter of the world in one place, and the three scenarios."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Literal

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
    payout_ratio: float = 0.0
    """Share of a month's positive profit paid out as dividends by a bank above its capital
    trigger (paid from cash, never more than the cash it has). The default 0 keeps every earlier
    result: without it, retained earnings pile up and capital ratios drift to 30% and more."""


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
    heterogeneous: bool = False
    saving_rank_slope: float = 0.12
    top_return_premium: float = 0.0004
    top_income_growth: float = 0.0
    deposit_wealth_share: float = 0.15
    base_unemployment: float = 4.5
    okun: float = 0.5


BailoutMode = Literal["none", "liquidity", "recapitalise"]


@dataclass(frozen=True, slots=True)
class FirmParams:
    """Non-financial firms: leverage builds in booms and the default rate rises with it (Minsky)."""

    enabled: bool = False
    initial_leverage: float = 0.45
    leverage_build: float = 0.002
    leverage_bust: float = 0.004
    leverage_reversion: float = 0.02
    default_sensitivity: float = 6.0
    output_drag: float = 0.5


@dataclass(frozen=True, slots=True)
class FiscalParams:
    """A government: taxes, counter-cyclical spending, debt, a sovereign spread and austerity."""

    enabled: bool = False
    tax_rate: float = 0.30
    spending_share: float = 0.30
    countercyclical: float = 0.5
    multiplier: float = 0.8
    impulse_scale: float = 0.1
    initial_debt: float = 0.80
    trend_growth: float = 2.0
    spread_threshold: float = 0.90
    spread_slope: float = 0.03
    austerity_threshold: float = 1.20
    austerity_cut: float = 0.02
    gdp_scale: float = 1_500.0


@dataclass(frozen=True, slots=True)
class ForeignParams:
    """A foreign sector: an exchange rate with carry and jumps, pass-through, FX bank debt."""

    enabled: bool = False
    foreign_rate: float = 2.0
    carry_response: float = 0.5
    fx_volatility: tuple[float, float, float] = (0.01, 0.015, 0.03)
    crisis_depreciation: float = 0.08
    inflation_pass_through: float = 0.08
    trade_effect: float = 0.03
    equity_flight: float = 0.30
    bank_fx_debt_share: float = 0.15


@dataclass(frozen=True, slots=True)
class PolicyParams:
    """What the authorities do about failing banks."""

    mode: BailoutMode = "none"
    rescue_threshold: float = 0.03
    target_ratio: float = 0.06
    max_injection_share: float = 0.15
    moral_hazard: float = 0.02


SHOCK_KINDS = (
    "equity_crash",
    "rate_hike",
    "fx_crash",
    "bank_loss",
    "sovereign_default",
    "supply_shock",
    "demand_shock",
)


@dataclass(frozen=True, slots=True)
class Shock:
    """An exogenous one-off event at `month`, for impulse responses (it uses no random numbers)."""

    month: int
    kind: str
    size: float = 0.0

    def __post_init__(self) -> None:
        if self.kind not in SHOCK_KINDS:
            raise ValueError(f"unknown shock {self.kind!r}; choose from {SHOCK_KINDS}")
        if self.month < 1:
            raise ValueError("a shock needs month >= 1")


@dataclass(frozen=True, slots=True)
class LinkParams:
    """The feedback loops that make the sectors one system (all off unless `enabled`).

    Households become part of the world: their consumption drives output, bank failures hit their
    uninsured deposits, and their taxes and transfers move the government's budget. Depositors are
    insured and the state pays the insurance. Banks hold the government's bonds, so a sovereign
    default hits them. Firm distress raises unemployment, and the central bank can lean against
    firm leverage.
    """

    enabled: bool = False
    demand_coupling: float = 0.1
    market_portfolio: tuple[float, float, float, float] = (0.4, 0.3, 0.1, 0.2)
    firm_unemployment: float = 1.0
    deposit_insurance: bool = True
    insured_share: float = 0.8
    loan_recovery: float = 0.6
    top_depositor_share: float = 0.2
    bank_sovereign_share: float = 0.4
    sovereign_default: bool = True
    default_threshold: float = 1.5
    hazard_slope: float = 0.2
    haircut: float = 0.3
    exclusion_months: int = 24
    default_fx_jump: float = 0.15
    default_output_shock: float = -1.5
    default_spread_jump: float = 3.0
    spread_decay: float = 0.97
    financial_stability_phi: float = 0.0
    tax_progressivity: float = 0.0
    wealth_tax_rate: float = 0.0
    wealth_tax_threshold: float = 5.0


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
    firms: FirmParams = field(default_factory=FirmParams)
    fiscal: FiscalParams = field(default_factory=FiscalParams)
    foreign: ForeignParams = field(default_factory=ForeignParams)
    policy: PolicyParams = field(default_factory=PolicyParams)
    links: LinkParams = field(default_factory=LinkParams)

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


EXTENDED_SCENARIOS = ("volatile_full", "stressed_full")


def extended(config: WorldConfig, *, mode: BailoutMode = "none") -> WorldConfig:
    """`config` with firms, a government, a foreign sector and unequal households switched on."""
    return replace(
        config,
        name=f"{config.name}_full",
        firms=replace(config.firms, enabled=True),
        fiscal=replace(config.fiscal, enabled=True),
        foreign=replace(config.foreign, enabled=True),
        policy=replace(config.policy, mode=mode),
        households=replace(config.households, heterogeneous=True),
    )


def full_scenario(name: str, *, mode: BailoutMode = "none") -> WorldConfig:
    """`volatile_full` or `stressed_full`: the v1 scenario with every extension on."""
    if name not in EXTENDED_SCENARIOS:
        raise ValueError(f"unknown extended scenario {name!r}; choose from {EXTENDED_SCENARIOS}")
    return extended(scenario(name.removesuffix("_full")), mode=mode)


CONNECTED_SCENARIOS = (
    "volatile_connected",
    "stressed_connected",
    "sovereign_stress",
    "rising_inequality",
)


def connected(config: WorldConfig, *, mode: BailoutMode = "none") -> WorldConfig:
    """`config` fully extended (see `extended`) with the `LinkParams` feedback loops switched on."""
    base = extended(config, mode=mode)
    return replace(
        base,
        name=config.name + "_connected",
        links=replace(base.links, enabled=True),
    )


def connected_scenario(name: str, *, mode: BailoutMode = "none") -> WorldConfig:
    """Fully interconnected worlds.

    `volatile_connected` and `stressed_connected` are the v1 scenarios with every sector and loop
    on.
    `sovereign_stress` starts with public debt at 130% of GDP in an ordinary volatile economy, so
    the doom loop between the state and its banks is in play. `rising_inequality` adds forces that
    concentrate income and wealth (faster income growth and higher returns at the top) to a
    volatile economy.
    """
    if name == "volatile_connected":
        return connected(scenario("volatile"), mode=mode)
    if name == "stressed_connected":
        return connected(scenario("stressed"), mode=mode)
    if name == "sovereign_stress":
        base = connected(scenario("volatile"), mode=mode)
        return replace(
            base,
            name="sovereign_stress",
            fiscal=replace(base.fiscal, initial_debt=1.30),
        )
    if name == "rising_inequality":
        base = connected(scenario("volatile"), mode=mode)
        return replace(
            base,
            name="rising_inequality",
            households=replace(
                base.households,
                top_income_growth=8.0,
                top_return_premium=0.004,
            ),
        )
    raise ValueError(f"unknown connected scenario {name!r}; choose from {CONNECTED_SCENARIOS}")
