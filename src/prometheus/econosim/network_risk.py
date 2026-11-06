"""Builds `titan.contagion`'s Eisenberg-Noe clearing inputs from a REAL
`Bank`/`CentralBankLedger` network on a shared `Ledger` -- the first
connection anywhere in this repository between ECONOSIM-X's simulated
banking system and TITAN's systemic-risk analytics.

Nodes: every bank passed in, plus the central bank ledger itself as one
additional node. This is not a special case bolted on afterward -- the
central bank's reserve liabilities TO banks, and the discount-window
loans banks owe IT, are genuine interbank-style obligations, so it is
simply one more node in the same clearing network.

Two interbank liability sources feed the matrix, both optional
independently: a bank's discount-window loan payable to the central bank
(and the central bank's matching reserve liability back to that bank),
always included; and, when an `InterbankMarket` is supplied, genuine
bilateral bank-to-bank loans read directly from its per-pair accounts --
closing what was, before this, a standing limitation of this module (every
off-diagonal bank<->bank entry was exactly zero with no way to represent
direct interbank lending at all). A bank's `loans_outstanding` (claims on
households/government) and its
own `reserves_account` balance are this network's "external assets" --
real money, but outside the interbank network being cleared. A bank's
`cb_settlement_balance` is deliberately NOT counted as an external asset:
it is already represented as the central bank's reserve-liability edge
TO that bank, and counting it again would double-count the exact same
claim once as an asset and once as a receivable to be cleared.

All values are in minor currency units (cents), matching `core.money.Money`'s
own convention -- no unit conversion is applied.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from prometheus.econosim.agents import Bank
from prometheus.econosim.central_bank_ledger import CentralBankLedger
from prometheus.econosim.interbank_market import InterbankMarket
from prometheus.titan.contagion import ClearingResult, eisenberg_noe_clearing


@dataclass(frozen=True, slots=True)
class ContagionNetwork:
    node_ids: tuple[str, ...]
    """One entry per bank, in the order given, followed by the central
    bank ledger's own agent_id as the final node."""
    liabilities: np.ndarray
    external_assets: np.ndarray


def build_contagion_network(
    banks: list[Bank],
    central_bank_ledger: CentralBankLedger,
    interbank_market: InterbankMarket | None = None,
) -> ContagionNetwork:
    if not banks:
        raise ValueError("at least one bank is required")
    agent_ids = [bank.agent_id for bank in banks]
    if len(set(agent_ids)) != len(agent_ids):
        raise ValueError("banks must have distinct agent_ids")

    node_ids = (*agent_ids, central_bank_ledger.agent_id)
    n = len(node_ids)
    cb_index = n - 1
    liabilities = np.zeros((n, n))
    external_assets = np.zeros(n)

    for i, bank in enumerate(banks):
        loan_payable = central_bank_ledger.loan_payable_of(bank)
        reserve_liability = central_bank_ledger.reserve_liability_to(bank)
        liabilities[i, cb_index] = float(loan_payable.minor_units)
        liabilities[cb_index, i] = float(reserve_liability.minor_units)
        reserves_balance = bank.ledger.account(bank.reserves_account).balance
        external_assets[i] = float((bank.loans_outstanding + reserves_balance).minor_units)

        if interbank_market is not None:
            for j, other_bank in enumerate(banks):
                if i == j:
                    continue
                # liabilities[i, j] = what bank i owes bank j = bank j's
                # receivable from bank i (bank j is the lender here).
                owed_to_other = interbank_market.exposure(lender=other_bank, borrower=bank)
                liabilities[i, j] = float(owed_to_other.minor_units)

    external_assets[cb_index] = float(central_bank_ledger.securities_holdings.minor_units)

    return ContagionNetwork(
        node_ids=node_ids, liabilities=liabilities, external_assets=external_assets
    )


def run_contagion_analysis(
    banks: list[Bank],
    central_bank_ledger: CentralBankLedger,
    interbank_market: InterbankMarket | None = None,
) -> tuple[ContagionNetwork, ClearingResult]:
    """Build the network from live ledger state and immediately clear it
    -- the one-call version of `build_contagion_network` followed by
    `titan.contagion.eisenberg_noe_clearing`, for callers that don't need
    the intermediate network for anything else."""
    network = build_contagion_network(banks, central_bank_ledger, interbank_market)
    result = eisenberg_noe_clearing(network.liabilities, network.external_assets)
    return network, result
