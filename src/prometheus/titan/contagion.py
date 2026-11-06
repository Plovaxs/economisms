"""Interbank network contagion (RISK-11): Eisenberg & Noe's (2001) fixed-
point clearing payment vector for a network of banks connected by
interbank liabilities, with limited liability and pro-rata (pari passu)
loss-sharing among a defaulting bank's creditors.

Setup: `liabilities[i, j]` is the nominal amount bank i owes bank j
(zero diagonal); `external_assets[i]` is bank i's assets from outside the
network. Each bank's total nominal obligation is `p_bar[i] =
liabilities[i, :].sum()`; the relative-liabilities matrix `Pi[i, j] =
liabilities[i, j] / p_bar[i]` is the fraction of i's total payment that
flows to creditor j once i pays pro-rata. The clearing payment vector p*
is the fixed point of

    p_i = min( p_bar_i, max(0, e_i + sum_j Pi[j, i] * p_j) )

-- each bank pays the lesser of what it owes and what it has available
(external assets plus what it actually receives from its own debtors).
`eisenberg_noe_clearing` computes it via the iteration p^0 = p_bar,
p^{k+1} = Phi(p^k): Eisenberg & Noe prove this sequence decreases
monotonically (Phi(p_bar) <= p_bar entrywise, and Phi is entrywise
non-decreasing, so by induction p^{k+1} <= p^k) and is bounded below by
zero, hence converges -- to the GREATEST clearing vector, which is the
economically meaningful one under their regularity conditions.

Known degeneracy, not fixed here: a pure liability cycle with no external
assets anywhere in the cycle (a "Ponzi" ring) has the trivial full-payment
vector as its greatest fixed point too, even though nothing ever actually
backs those payments -- this is acknowledged in Eisenberg & Noe's own
paper, not a bug in this implementation. This repository makes no attempt
to select a different (e.g. "least") clearing vector or to break such a
cycle via a sequential-default tie-breaking rule.

`network_concentration` adds a partial RISK-12 (concentration
decomposition) building block: the Herfindahl-Hirschman index of each
bank's outgoing (debtor) and incoming (creditor) interbank exposures.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


class ContagionError(Exception):
    """Base class for contagion-analysis errors."""


class ClearingNotConvergedError(ContagionError):
    def __init__(self, iterations: int, residual: float) -> None:
        super().__init__(
            f"Eisenberg-Noe clearing did not converge within {iterations} iterations "
            f"(residual={residual}); this indicates a numerical issue or too few "
            "iterations, not a structural non-existence -- the fixed point is proven "
            "to exist and this iteration is proven to converge to it"
        )
        self.iterations = iterations
        self.residual = residual


def _validate_network(
    liabilities: np.ndarray, external_assets: np.ndarray
) -> tuple[int, np.ndarray, np.ndarray]:
    liabilities = np.asarray(liabilities, dtype=float)
    external_assets = np.asarray(external_assets, dtype=float)
    if liabilities.ndim != 2 or liabilities.shape[0] != liabilities.shape[1]:
        raise ValueError("liabilities must be a square 2-D matrix")
    n = liabilities.shape[0]
    if external_assets.shape != (n,):
        raise ValueError(f"external_assets must have shape ({n},), got {external_assets.shape}")
    if np.any(liabilities < 0):
        raise ValueError("liabilities must be non-negative")
    if np.any(np.diag(liabilities) != 0):
        raise ValueError("liabilities must have a zero diagonal (a bank cannot owe itself)")
    if np.any(external_assets < 0):
        raise ValueError("external_assets must be non-negative")
    return n, liabilities, external_assets


@dataclass(frozen=True, slots=True)
class ClearingResult:
    payments: np.ndarray
    nominal_obligations: np.ndarray
    received: np.ndarray
    nominal_claims: np.ndarray
    defaulted: np.ndarray
    debtor_shortfall: np.ndarray
    creditor_loss: np.ndarray
    equity_after: np.ndarray
    iterations: int


def eisenberg_noe_clearing(
    liabilities: np.ndarray,
    external_assets: np.ndarray,
    max_iterations: int = 10_000,
    tol: float = 1e-10,
) -> ClearingResult:
    n, liabilities, external_assets = _validate_network(liabilities, external_assets)
    p_bar = liabilities.sum(axis=1)
    has_debt = p_bar > 0
    safe_p_bar = np.where(has_debt, p_bar, 1.0)
    relative_liabilities = np.where(has_debt[:, None], liabilities / safe_p_bar[:, None], 0.0)

    payments = p_bar.copy()
    residual = float("inf")
    iterations = 0
    for step in range(1, max_iterations + 1):
        iterations = step
        received = relative_liabilities.T @ payments
        next_payments = np.clip(external_assets + received, 0.0, p_bar)
        residual = float(np.max(np.abs(next_payments - payments))) if n > 0 else 0.0
        payments = next_payments
        if residual <= tol:
            break
    else:
        raise ClearingNotConvergedError(max_iterations, residual)

    received = relative_liabilities.T @ payments
    nominal_claims = liabilities.sum(axis=0)
    defaulted = payments < p_bar - tol
    debtor_shortfall = p_bar - payments
    creditor_loss = nominal_claims - received
    equity_after = np.maximum(0.0, external_assets + received) - payments

    return ClearingResult(
        payments=payments,
        nominal_obligations=p_bar,
        received=received,
        nominal_claims=nominal_claims,
        defaulted=defaulted,
        debtor_shortfall=debtor_shortfall,
        creditor_loss=creditor_loss,
        equity_after=equity_after,
        iterations=iterations,
    )


def _herfindahl_index(exposures: np.ndarray) -> float:
    total = exposures.sum()
    if total <= 0:
        return 0.0
    shares = exposures / total
    return float(np.sum(shares**2))


@dataclass(frozen=True, slots=True)
class NetworkConcentrationResult:
    debtor_concentration: np.ndarray
    creditor_concentration: np.ndarray


def network_concentration(liabilities: np.ndarray) -> NetworkConcentrationResult:
    """RISK-12 (partial): for each bank, the Herfindahl-Hirschman index
    (sum of squared counterparty shares, in [1/k, 1] for k counterparties,
    0 for a bank with no exposure at all) of its outgoing (debtor) and
    incoming (creditor) interbank exposures. 1.0 means fully concentrated
    in a single counterparty; 1/n_counterparties is the maximally diversified
    case among that many counterparties."""
    liabilities = np.asarray(liabilities, dtype=float)
    if liabilities.ndim != 2 or liabilities.shape[0] != liabilities.shape[1]:
        raise ValueError("liabilities must be a square 2-D matrix")
    if np.any(liabilities < 0):
        raise ValueError("liabilities must be non-negative")
    n = liabilities.shape[0]
    debtor_concentration = np.array([_herfindahl_index(liabilities[i, :]) for i in range(n)])
    creditor_concentration = np.array([_herfindahl_index(liabilities[:, j]) for j in range(n)])
    return NetworkConcentrationResult(debtor_concentration, creditor_concentration)
