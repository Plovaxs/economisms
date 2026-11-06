"""Economy: wires agents to a shared ledger and tracks a simulation step.

This is intentionally thin. Macro-step event ordering (known-at releases,
shock scheduling, calendar stepping) lives in econosim.time_engine, which
wraps an Economy rather than this class absorbing that responsibility
itself; advance_step() here only increments a counter and asserts the
ledger's accounting identities still hold.
"""

from __future__ import annotations

from prometheus.core.ledger import Ledger
from prometheus.econosim.agents import Bank, Firm, Government, Household
from prometheus.econosim.central_bank_ledger import CentralBankLedger
from prometheus.econosim.policy_rate import CentralBank, PolicyRateRule


class Economy:
    def __init__(self, currency: str = "USD") -> None:
        self.ledger = Ledger()
        self.currency = currency
        self.step_index = 0
        self.households: dict[str, Household] = {}
        self.firms: dict[str, Firm] = {}
        self.banks: dict[str, Bank] = {}
        self.governments: dict[str, Government] = {}
        self.central_banks: dict[str, CentralBank] = {}
        self.central_bank_ledgers: dict[str, CentralBankLedger] = {}

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

    def add_government(self, agent_id: str) -> Government:
        government = Government(self.ledger, agent_id, currency=self.currency)
        self.governments[agent_id] = government
        return government

    def add_central_bank(
        self, agent_id: str, rule: PolicyRateRule, initial_rate: float
    ) -> CentralBank:
        """Not ledger-backed (see policy_rate.CentralBank's docstring);
        tracked here only so a simulation has one place to find it, the
        same way it finds every other agent."""
        central_bank = CentralBank(agent_id=agent_id, rule=rule, current_rate=initial_rate)
        self.central_banks[agent_id] = central_bank
        return central_bank

    def add_central_bank_ledger(
        self,
        agent_id: str,
        rate_rule: PolicyRateRule | None = None,
        initial_rate: float | None = None,
    ) -> CentralBankLedger:
        """A genuinely ledger-backed central bank (reserve issuance, OMO,
        interbank settlement -- see econosim.central_bank_ledger).
        Optionally pass `rate_rule`/`initial_rate` to get ONE object that
        is both the policy-rate setter and the balance sheet (PR-041);
        omit both for a balance-sheet-only agent, as before. Separate from
        `add_central_bank`'s rate-only wrapper above either way -- a
        simulation that wants a bare rate process with no balance sheet
        still constructs that under its own agent_id."""
        central_bank_ledger = CentralBankLedger(
            self.ledger,
            agent_id,
            currency=self.currency,
            rate_rule=rate_rule,
            initial_rate=initial_rate,
        )
        self.central_bank_ledgers[agent_id] = central_bank_ledger
        return central_bank_ledger

    def check_integrity(self) -> None:
        """Raise LedgerIdentityViolation if any sector is out of balance."""
        self.ledger.check_identities(self.currency)

    def advance_step(self) -> int:
        self.check_integrity()
        self.step_index += 1
        return self.step_index
