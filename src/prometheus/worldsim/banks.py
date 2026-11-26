"""A leveraged banking sector linked by interbank loans, with loan losses, capital rules and
contagion.

Each bank holds loans, securities (part equities, part bonds), cash and interbank claims, funded by
deposits, interbank borrowing and equity. Every month it books interest income, loan losses (which
rise as the output gap falls) and the securities' mark-to-market; interbank obligations then clear
with the repository's Eisenberg-Noe solver (`titan.contagion`), deposits being senior. A bank that
is insolvent or cannot pay its interbank obligations has failed, and failure is absorbing. A bank
under its capital trigger stops lending and sells part of its securities, which depresses next
month's equity prices (a fire sale); the world feeds that price impact back into the asset returns.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from prometheus.titan.contagion import eisenberg_noe_clearing
from prometheus.worldsim.config import BankParams


@dataclass(slots=True)
class BankState:
    loans: np.ndarray
    securities: np.ndarray
    cash: np.ndarray
    deposits: np.ndarray
    liabilities: np.ndarray  # liabilities[i, j]: what bank i owes bank j
    failed: np.ndarray

    @property
    def claims(self) -> np.ndarray:
        return np.asarray(self.liabilities.sum(axis=0), dtype=np.float64)

    @property
    def borrowed(self) -> np.ndarray:
        return np.asarray(self.liabilities.sum(axis=1), dtype=np.float64)

    @property
    def assets(self) -> np.ndarray:
        return np.asarray(self.loans + self.securities + self.cash + self.claims, dtype=np.float64)

    @property
    def equity(self) -> np.ndarray:
        return np.asarray(self.assets - self.deposits - self.borrowed, dtype=np.float64)


@dataclass(frozen=True, slots=True)
class BankStep:
    equity: np.ndarray
    capital_ratio: np.ndarray
    failed: np.ndarray
    constrained: np.ndarray
    new_failures: int
    contagion_defaults: int
    fire_sale_volume: float
    credit_crunch: float
    total_loans: float


def initial_banks(params: BankParams, rng: np.random.Generator) -> BankState:
    n = params.n_banks
    if params.interbank_counterparties >= n:
        raise ValueError("a bank needs fewer interbank counterparties than there are banks")
    liabilities = np.zeros((n, n))
    share = params.interbank_borrowed / params.interbank_counterparties
    for i in range(n):
        others = [j for j in range(n) if j != i]
        for j in rng.choice(others, size=params.interbank_counterparties, replace=False):
            liabilities[i, j] += share
    scale = 1.0 + 0.10 * rng.standard_normal(n)
    loans = params.loans * scale
    securities = params.securities * scale
    cash = np.full(n, params.cash)
    assets = loans + securities + cash + liabilities.sum(axis=0)
    # Deposits are a fixed share of each bank's assets, so every bank starts with positive equity.
    return BankState(
        loans=loans,
        securities=securities,
        cash=cash,
        deposits=assets * (params.deposit_funding / 100.0),
        liabilities=liabilities,
        failed=np.zeros(n, dtype=bool),
    )


def step_banks(
    state: BankState,
    params: BankParams,
    *,
    equity_return: float,
    bond_return: float,
    output_gap: float,
    market_size: float,
) -> BankStep:
    already_failed = state.failed.copy()
    default_rate = np.clip(
        params.base_default_rate * np.exp(-params.default_sensitivity * output_gap), 3e-4, 0.02
    )
    loss = state.loans * default_rate * params.loss_given_default
    income = state.loans * params.net_interest_margin
    security_return = (
        params.securities_equity_share * equity_return
        + (1.0 - params.securities_equity_share) * bond_return
    )
    state.loans = state.loans - loss
    state.cash = state.cash + income
    state.securities = state.securities * (1.0 + security_return)

    ratio_before = state.equity / np.maximum(state.assets, 1e-9)
    constrained = (ratio_before < params.capital_trigger) & ~state.failed
    growth = np.where(
        constrained | state.failed,
        0.0,
        params.loan_growth_base + params.loan_growth_slope * output_gap,
    )
    new_loans = state.loans * np.clip(growth, -0.01, 0.01)
    state.loans = state.loans + new_loans
    state.deposits = state.deposits + new_loans

    external_raw = state.loans + state.securities + state.cash - state.deposits
    clearing = eisenberg_noe_clearing(state.liabilities, np.maximum(external_raw, 0.0))
    full_payment_equity = external_raw + state.claims - state.borrowed
    insolvent = state.equity <= 0.0
    defaulted = np.asarray(clearing.defaulted, dtype=bool) | insolvent
    contagion = defaulted & (full_payment_equity >= 0.0) & ~already_failed
    state.failed = already_failed | defaulted

    sale = np.where(constrained & ~state.failed, params.fire_sale_fraction * state.securities, 0.0)
    state.securities = state.securities - sale
    state.cash = state.cash + sale
    equity = state.equity
    ratio = equity / np.maximum(state.assets, 1e-9)
    n = state.failed.size
    still_constrained = (ratio < params.capital_trigger) & ~state.failed
    return BankStep(
        equity=equity,
        capital_ratio=ratio,
        failed=state.failed.copy(),
        constrained=still_constrained,
        new_failures=int((state.failed & ~already_failed).sum()),
        contagion_defaults=int(contagion.sum()),
        fire_sale_volume=float(sale.sum()),
        credit_crunch=float((state.failed.sum() + still_constrained.sum()) / n),
        total_loans=float(np.where(state.failed, 0.0, state.loans).sum()),
    )
