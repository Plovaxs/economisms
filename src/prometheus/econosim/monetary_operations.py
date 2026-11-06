"""Wires `central_bank_ledger.CentralBankLedger` into the real StepHooks
event order (ECO-05/ECO-09, extending PR-026): a two-bank economy where a
rate decision each step -- `policy_rate.PolicyRateRule`, the same rule used
everywhere else -- drives an open-market operation sized to the rate's
change, a fixed discount-window loan taken out once and amortized on a
schedule, and a periodic interbank reserve transfer. This is the first
scenario anywhere in this repository that exercises all three
`CentralBankLedger` channels (OMO, discount window, interbank settlement)
together, across simulated time, through `MacroTimeEngine.advance_step()`
-- not standalone calls in a single test, the way PR-026 introduced them.

PR-033/034 extend this with a genuine DIRECT interbank loan
(`econosim.interbank_market.InterbankMarket`, bank_a lending to bank_b,
amortized on its own independent schedule) and a periodic systemic-risk
check: every `contagion_check_every` steps, `econosim.network_risk.run_contagion_analysis`
clears the live two-bank-plus-central-bank network and the result's
default flags are recorded directly in that step's settlement -- genuine
continuous risk monitoring inside a running simulation, not a one-off
offline analysis. PR-036 makes that check ACT, not just observe: once it
ever detects a default, a one-way circuit breaker suspends NEW
discount-window and interbank lending for the rest of the run (existing
debt still amortizes normally; OMO and interbank transfers, not new
unsecured credit, are unaffected) -- a deliberately limited risk response,
not a full shutdown, decided from the PREVIOUS step's check result so a
step's own lending decision never uses information only available at the
end of that same step. PR-041 (econosim.central_bank_ledger) replaces
this scenario's original two-object split -- a bare rate-only
`policy_rate.CentralBank` deciding the rate alongside a separate
`CentralBankLedger` executing operations -- with ONE unified
`CentralBankLedger` that is both, constructed with `rate_rule`/
`initial_rate`; `step_rate` on that same object is what `compute_actions`
calls each step.

Rule, not policy optimization: the OMO/lending/transfer sizes below are
specified schedules, exactly like every other "rule-based, not learned"
reaction function in this repository (policy_rate.PolicyRateRule itself,
monetary_feedback's Taylor-style rule). Any step whose requested operation
cannot be executed (insufficient bond holdings to sell, insufficient
settlement balance to transfer or repay) is skipped and recorded, not
silently clamped or allowed to raise and halt the run -- ledger identities
are reconfirmed every step regardless (ECO-16).
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass, fields
from datetime import date
from typing import Any

from prometheus.core.money import Money
from prometheus.econosim.agents import CreditLimitExceededError, InsufficientFundsError
from prometheus.econosim.central_bank_ledger import CentralBankLedger
from prometheus.econosim.economy import Economy
from prometheus.econosim.interbank_market import InterbankMarket
from prometheus.econosim.network_risk import run_contagion_analysis
from prometheus.econosim.policy_rate import PolicyRateRule
from prometheus.econosim.step_hooks import StepContext
from prometheus.econosim.time_engine import StepResult

DT = 1.0 / 12.0


@dataclass(frozen=True, slots=True)
class MonetaryOperationsConfig:
    seed: int = 0
    start_date: date = date(2026, 1, 2)
    n_steps: int = 12
    bank_a_capital: Money = Money(1_000_000_00)
    bank_b_capital: Money = Money(1_000_000_00)
    bank_a_bond_holdings: Money = Money(500_000_00)
    max_leverage: float = 50.0
    initial_policy_rate: float = 0.03
    policy_rate_neutral: float = 0.03
    policy_rate_mean_reversion: float = 0.5
    omo_rate_sensitivity: Money = Money(5_000_000_00)
    """Dollar size of an OMO per 1.0 (100 percentage points) of rate change
    in a single step."""
    discount_window_principal: Money = Money(200_000_00)
    discount_window_start_step: int = 1
    discount_window_installment: Money = Money(20_000_00)
    interbank_transfer_every: int = 3
    interbank_transfer_amount: Money = Money(50_000_00)
    policy_rate_shock_std: float = 0.01
    """Standard deviation of the per-step 'policy_rate'-kind shock an
    orchestration runner draws to drive non-trivial OMO activity; the core
    process itself (compute_actions) is agnostic to how `ctx.shocks` is
    produced -- a direct `StepContext` can supply any shocks, or none."""
    interbank_loan_start_step: int = 2
    interbank_loan_principal: Money = Money(150_000_00)
    interbank_loan_installment: Money = Money(15_000_00)
    """A direct bank_a->bank_b loan (InterbankMarket, PR-033), amortized on
    its own schedule exactly like the discount-window loan above but on a
    completely separate instrument and capital pool."""
    contagion_check_every: int = 6
    """How often (in steps) to run a live systemic-risk check
    (network_risk.run_contagion_analysis) against the current two-bank-
    plus-central-bank network."""

    def __post_init__(self) -> None:
        for name in ("seed", "n_steps", "interbank_transfer_every", "contagion_check_every"):
            value = getattr(self, name)
            minimum = 0 if name == "seed" else 1
            if type(value) is not int or value < minimum:
                raise ValueError(f"{name} must be an integer >= {minimum}")
        if type(self.start_date) is not date:
            raise ValueError("start_date must be a date")
        for step_name in ("discount_window_start_step", "interbank_loan_start_step"):
            step_value = getattr(self, step_name)
            if type(step_value) is not int or not 1 <= step_value <= self.n_steps:
                raise ValueError(f"{step_name} must be an integer within [1, n_steps]")
        for name in (
            "bank_a_capital",
            "bank_b_capital",
            "bank_a_bond_holdings",
            "omo_rate_sensitivity",
            "discount_window_principal",
            "discount_window_installment",
            "interbank_transfer_amount",
            "interbank_loan_principal",
            "interbank_loan_installment",
        ):
            amount = getattr(self, name)
            if not isinstance(amount, Money) or amount.currency != "USD" or amount.minor_units < 0:
                raise ValueError(f"{name} must be non-negative USD Money")
        for name in ("initial_policy_rate", "policy_rate_neutral", "policy_rate_mean_reversion"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ValueError(f"{name} must be a finite number")
            if not math.isfinite(value):
                raise ValueError(f"{name} must be finite")
        if self.policy_rate_mean_reversion < 0:
            raise ValueError("policy_rate_mean_reversion must be non-negative")
        if self.max_leverage <= 0:
            raise ValueError("max_leverage must be positive")
        if (
            isinstance(self.policy_rate_shock_std, bool)
            or not isinstance(self.policy_rate_shock_std, (int, float))
            or not math.isfinite(self.policy_rate_shock_std)
            or self.policy_rate_shock_std < 0
        ):
            raise ValueError("policy_rate_shock_std must be finite and non-negative")

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> MonetaryOperationsConfig:
        """Decode the complete exported configuration, with no silent
        defaults -- the same contract as EconomyRunConfig.from_dict."""
        if set(payload) != {item.name for item in fields(cls)}:
            raise ValueError(
                "monetary operations replay requires exactly the complete configuration fields"
            )
        values = dict(payload)
        try:
            if isinstance(values["start_date"], str):
                values["start_date"] = date.fromisoformat(values["start_date"])
            for name in (
                "bank_a_capital",
                "bank_b_capital",
                "bank_a_bond_holdings",
                "omo_rate_sensitivity",
                "discount_window_principal",
                "discount_window_installment",
                "interbank_transfer_amount",
                "interbank_loan_principal",
                "interbank_loan_installment",
            ):
                if isinstance(values[name], Mapping):
                    values[name] = Money(**values[name])
            return cls(**values)
        except (TypeError, AttributeError) as exc:
            raise ValueError(f"invalid monetary operations replay configuration: {exc}") from exc


@dataclass(frozen=True, slots=True)
class MonetaryAction:
    step: int
    policy_rate: float
    rate_change: float
    omo_side: str
    omo_amount: Money
    discount_window_action: str
    discount_window_amount: Money
    interbank_transfer_amount: Money
    interbank_loan_action: str
    interbank_loan_amount: Money


@dataclass(frozen=True, slots=True)
class ContagionCheckSummary:
    """A JSON-safe (no numpy arrays) summary of one
    `network_risk.run_contagion_analysis` call -- enough to flag a problem
    in an exported evidence payload without embedding the full
    `titan.contagion.ClearingResult` (whose fields are numpy arrays)."""

    node_ids: tuple[str, ...]
    any_defaulted: bool
    worst_creditor_loss: Money


@dataclass(frozen=True, slots=True)
class MonetarySettlement:
    step: int
    omo_executed: bool
    omo_skipped_reason: str | None
    discount_window_executed: bool
    discount_window_skipped_reason: str | None
    interbank_transfer_executed: bool
    interbank_transfer_skipped_reason: str | None
    interbank_loan_executed: bool
    interbank_loan_skipped_reason: str | None
    contagion_check: ContagionCheckSummary | None


@dataclass(frozen=True, slots=True)
class MonetaryOperationsStep:
    step: int
    step_date: date
    action: MonetaryAction
    settlement: MonetarySettlement
    bank_a_loans_outstanding: Money
    bank_a_settlement_balance: Money
    bank_b_settlement_balance: Money
    bank_b_loan_payable: Money
    cb_securities_holdings: Money
    cb_loans_to_banks_outstanding: Money
    bank_a_to_bank_b_interbank_exposure: Money
    risk_frozen: bool
    ledger_state_hash: str


class MonetaryOperationsProcess:
    """Owns the two-bank economy and ONE unified `CentralBankLedger`
    (PR-041) that is both the policy-rate setter and the ledger-backed
    balance sheet -- `econosim.policy_rate.CentralBank`'s bare rate
    process is no longer separately constructed here; `step_rate` on the
    same object that executes OMO/discount-window/interbank operations
    replaces the old two-object split this scenario originally shipped
    with (PR-028). `compute_actions`/`clear_and_settle` are bound
    methods, passed directly as `StepHooks` callbacks -- the exact
    pattern `price_economy.PriceEconomy` already uses for its own two
    hooks."""

    def __init__(self, config: MonetaryOperationsConfig) -> None:
        self.config = config
        self.economy = Economy()
        self.government = self.economy.add_government("gov")
        self.bank_a = self.economy.add_bank("bank_a", max_leverage=config.max_leverage)
        self.bank_b = self.economy.add_bank("bank_b", max_leverage=config.max_leverage)
        self.bank_a.capitalize(config.bank_a_capital)
        self.bank_b.capitalize(config.bank_b_capital)
        if config.bank_a_bond_holdings.is_positive():
            self.government.issue_bonds(self.bank_a, config.bank_a_bond_holdings)

        rule = PolicyRateRule(
            config.policy_rate_neutral, config.policy_rate_mean_reversion, DT
        )
        self.central_bank_ledger: CentralBankLedger = self.economy.add_central_bank_ledger(
            "cb", rate_rule=rule, initial_rate=config.initial_policy_rate
        )
        self.central_bank_ledger.register_bank(self.bank_a)
        self.central_bank_ledger.register_bank(self.bank_b)
        self._discount_window_remaining = Money.zero(self.economy.currency)

        self.interbank_market = InterbankMarket(self.economy.ledger)
        self._interbank_loan_remaining = Money.zero(self.economy.currency)
        self._risk_frozen = False
        """A one-way circuit breaker (ECO-16-style fail closed, applied to
        credit risk): set once the periodic contagion check (PR-034) ever
        detects a default, and never automatically cleared. While frozen,
        no NEW discount-window or interbank loan is extended -- existing
        debt still amortizes normally, and OMO/interbank-transfer (not new
        unsecured credit) are unaffected, a deliberately limited scope,
        not a full risk shutdown. The freeze is decided from the PREVIOUS
        step's check result, never the current step's -- a decision this
        step cannot use information only available at the end of this
        same step (no lookahead)."""

    def compute_actions(self, ctx: StepContext) -> MonetaryAction:
        previous_rate = self.central_bank_ledger.current_rate
        assert previous_rate is not None  # guaranteed by __init__'s rate_rule/initial_rate
        new_rate = self.central_bank_ledger.step_rate(list(ctx.shocks))
        rate_change = new_rate - previous_rate

        omo_amount_minor = round(abs(rate_change) * self.config.omo_rate_sensitivity.minor_units)
        omo_amount = Money(omo_amount_minor, self.economy.currency)
        if omo_amount_minor == 0:
            omo_side = "none"
        elif rate_change < 0:
            omo_side = "purchase"
        else:
            omo_side = "sell"

        zero = Money.zero(self.economy.currency)
        if ctx.step == self.config.discount_window_start_step and not self._risk_frozen:
            discount_window_action = "lend"
            discount_window_amount = self.config.discount_window_principal
        elif self._discount_window_remaining.is_positive():
            discount_window_action = "repay"
            discount_window_amount = min(
                self.config.discount_window_installment, self._discount_window_remaining
            )
        else:
            discount_window_action = "none"
            discount_window_amount = zero

        interbank_transfer_amount = (
            self.config.interbank_transfer_amount
            if ctx.step % self.config.interbank_transfer_every == 0
            else zero
        )

        if ctx.step == self.config.interbank_loan_start_step and not self._risk_frozen:
            interbank_loan_action = "lend"
            interbank_loan_amount = self.config.interbank_loan_principal
        elif self._interbank_loan_remaining.is_positive():
            interbank_loan_action = "repay"
            interbank_loan_amount = min(
                self.config.interbank_loan_installment, self._interbank_loan_remaining
            )
        else:
            interbank_loan_action = "none"
            interbank_loan_amount = zero

        return MonetaryAction(
            step=ctx.step,
            policy_rate=new_rate,
            rate_change=rate_change,
            omo_side=omo_side,
            omo_amount=omo_amount,
            discount_window_action=discount_window_action,
            discount_window_amount=discount_window_amount,
            interbank_transfer_amount=interbank_transfer_amount,
            interbank_loan_action=interbank_loan_action,
            interbank_loan_amount=interbank_loan_amount,
        )

    def clear_and_settle(self, ctx: StepContext, action: MonetaryAction) -> MonetarySettlement:
        cb = self.central_bank_ledger

        omo_executed = False
        omo_skipped_reason: str | None = None
        if action.omo_side == "purchase":
            try:
                cb.purchase_government_bonds(self.bank_a, action.omo_amount, step=ctx.step)
                omo_executed = True
            except ValueError as exc:
                omo_skipped_reason = str(exc)
        elif action.omo_side == "sell":
            try:
                cb.sell_government_bonds(self.bank_a, action.omo_amount, step=ctx.step)
                omo_executed = True
            except (ValueError, InsufficientFundsError) as exc:
                omo_skipped_reason = str(exc)

        discount_window_executed = False
        discount_window_skipped_reason: str | None = None
        if action.discount_window_action == "lend":
            cb.lend_to_bank(self.bank_b, action.discount_window_amount, step=ctx.step)
            self._discount_window_remaining = (
                self._discount_window_remaining + action.discount_window_amount
            )
            discount_window_executed = True
        elif action.discount_window_action == "repay":
            try:
                cb.repay_central_bank_loan(
                    self.bank_b, action.discount_window_amount, step=ctx.step
                )
                self._discount_window_remaining = (
                    self._discount_window_remaining - action.discount_window_amount
                )
                discount_window_executed = True
            except InsufficientFundsError as exc:
                discount_window_skipped_reason = str(exc)

        interbank_transfer_executed = False
        interbank_transfer_skipped_reason: str | None = None
        if action.interbank_transfer_amount.is_positive():
            try:
                cb.settle_interbank_transfer(
                    self.bank_a, self.bank_b, action.interbank_transfer_amount, step=ctx.step
                )
                interbank_transfer_executed = True
            except InsufficientFundsError as exc:
                interbank_transfer_skipped_reason = str(exc)

        interbank_loan_executed = False
        interbank_loan_skipped_reason: str | None = None
        if action.interbank_loan_action == "lend":
            # Unlike the discount window's "lend" above (the central bank
            # creates reserves unconditionally, with no capacity check),
            # a real InterbankMarket loan is capped by the lender's own
            # capital/leverage AND its actual reserves -- both can fail,
            # and must be skipped gracefully like every other channel,
            # not allowed to crash the run.
            try:
                self.interbank_market.lend(
                    self.bank_a, self.bank_b, action.interbank_loan_amount, step=ctx.step
                )
                self._interbank_loan_remaining = (
                    self._interbank_loan_remaining + action.interbank_loan_amount
                )
                interbank_loan_executed = True
            except (InsufficientFundsError, CreditLimitExceededError) as exc:
                interbank_loan_skipped_reason = str(exc)
        elif action.interbank_loan_action == "repay":
            try:
                self.interbank_market.repay(
                    self.bank_a, self.bank_b, action.interbank_loan_amount, step=ctx.step
                )
                self._interbank_loan_remaining = (
                    self._interbank_loan_remaining - action.interbank_loan_amount
                )
                interbank_loan_executed = True
            except InsufficientFundsError as exc:
                interbank_loan_skipped_reason = str(exc)

        contagion_check: ContagionCheckSummary | None = None
        if ctx.step % self.config.contagion_check_every == 0:
            network, result = run_contagion_analysis(
                [self.bank_a, self.bank_b], cb, self.interbank_market
            )
            contagion_check = ContagionCheckSummary(
                node_ids=network.node_ids,
                any_defaulted=bool(result.defaulted.any()),
                worst_creditor_loss=Money(round(float(result.creditor_loss.max()))),
            )
            if contagion_check.any_defaulted:
                self._risk_frozen = True

        return MonetarySettlement(
            step=ctx.step,
            omo_executed=omo_executed,
            omo_skipped_reason=omo_skipped_reason,
            discount_window_executed=discount_window_executed,
            discount_window_skipped_reason=discount_window_skipped_reason,
            interbank_transfer_executed=interbank_transfer_executed,
            interbank_transfer_skipped_reason=interbank_transfer_skipped_reason,
            interbank_loan_executed=interbank_loan_executed,
            interbank_loan_skipped_reason=interbank_loan_skipped_reason,
            contagion_check=contagion_check,
        )

    def snapshot(self, result: StepResult) -> MonetaryOperationsStep:
        cb = self.central_bank_ledger
        return MonetaryOperationsStep(
            step=result.step,
            step_date=result.step_date,
            action=result.actions,
            settlement=result.settlement,
            bank_a_loans_outstanding=self.bank_a.loans_outstanding,
            bank_a_settlement_balance=cb.settlement_balance_of(self.bank_a),
            bank_b_settlement_balance=cb.settlement_balance_of(self.bank_b),
            bank_b_loan_payable=cb.loan_payable_of(self.bank_b),
            cb_securities_holdings=cb.securities_holdings,
            cb_loans_to_banks_outstanding=cb.loans_to_banks_outstanding,
            bank_a_to_bank_b_interbank_exposure=self.interbank_market.exposure(
                self.bank_a, self.bank_b
            ),
            risk_frozen=self._risk_frozen,
            ledger_state_hash=result.state_hash,
        )
