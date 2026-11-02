"""Economy: wires agents to a shared ledger and tracks a simulation step.

This is intentionally thin. The macro time engine (known-at event releases,
shock scheduling, market-calendar stepping -- PR-003 in the roadmap) is not
implemented yet; advance_step() here only increments a counter and asserts
the ledger's accounting identities still hold.
"""

from __future__ import annotations

from prometheus.core.ledger import Ledger
from prometheus.econosim.agents import Bank, Firm, Household


class Economy:
    def __init__(self, currency: str = "USD") -> None:
        self.ledger = Ledger()
        self.currency = currency
        self.step_index = 0
        self.households: dict[str, Household] = {}
        self.firms: dict[str, Firm] = {}
        self.banks: dict[str, Bank] = {}

    def add_household(self, agent_id: str) -> Household:
        household = Household(self.ledger, agent_id, currency=self.currency)
        self.households[agent_id] = household
        return household

    def add_firm(self, agent_id: str) -> Firm:
        firm = Firm(self.ledger, agent_id, currency=self.currency)
        self.firms[agent_id] = firm
        return firm

    def add_bank(self, agent_id: str, max_leverage: float = 10.0) -> Bank:
        bank = Bank(self.ledger, agent_id, currency=self.currency, max_leverage=max_leverage)
        self.banks[agent_id] = bank
        return bank

    def check_integrity(self) -> None:
        """Raise LedgerIdentityViolation if any sector is out of balance."""
        self.ledger.check_identities(self.currency)

    def advance_step(self) -> int:
        self.check_integrity()
        self.step_index += 1
        return self.step_index
