from datetime import date

import numpy as np
import pytest

from prometheus.core.calendar import BusinessDayCalendar
from prometheus.core.money import Money
from prometheus.econosim.monetary_operations import (
    MonetaryOperationsConfig,
    MonetaryOperationsProcess,
)
from prometheus.econosim.shocks import ShockGenerator, ShockSpec
from prometheus.econosim.step_hooks import StepContext, StepHooks
from prometheus.econosim.time_engine import MacroTimeEngine


def _ctx(process: MonetaryOperationsProcess, step: int) -> StepContext:
    return StepContext(
        step=step,
        step_date=date(2026, 1, 2),
        released=(),
        shocks=(),
        economy=process.economy,
    )


@pytest.mark.parametrize(
    "field,value",
    [
        ("seed", -1),
        ("n_steps", 0),
        ("discount_window_start_step", 0),
        ("max_leverage", 0.0),
        ("max_leverage", -1.0),
        ("policy_rate_mean_reversion", -0.1),
        ("initial_policy_rate", float("nan")),
        ("bank_a_bond_holdings", Money(-1)),
    ],
)
def test_config_rejects_invalid_fields(field: str, value: object) -> None:
    with pytest.raises(ValueError):
        MonetaryOperationsConfig(**{field: value})


def test_config_rejects_discount_window_start_step_beyond_n_steps() -> None:
    with pytest.raises(ValueError):
        MonetaryOperationsConfig(n_steps=5, discount_window_start_step=6)


def test_config_rejects_non_date_start_date() -> None:
    with pytest.raises(ValueError):
        MonetaryOperationsConfig(start_date="2026-01-02")  # type: ignore[arg-type]


def test_config_rejects_boolean_rate_field() -> None:
    with pytest.raises(ValueError):
        MonetaryOperationsConfig(initial_policy_rate=True)  # type: ignore[arg-type]


def test_process_construction_registers_both_banks_with_the_ledger_backed_central_bank() -> None:
    process = MonetaryOperationsProcess(MonetaryOperationsConfig())
    assert process.bank_a.loans_outstanding == MonetaryOperationsConfig().bank_a_bond_holdings
    assert process.bank_b.loans_outstanding == Money.zero("USD")
    assert process.central_bank_ledger.settlement_balance_of(process.bank_a) == Money.zero("USD")
    assert process.central_bank_ledger.settlement_balance_of(process.bank_b) == Money.zero("USD")


def test_process_uses_one_unified_central_bank_for_both_rate_and_balance_sheet() -> None:
    """PR-041: this scenario no longer constructs a separate rate-only
    CentralBank -- central_bank_ledger is the one and only central-bank
    object, and it already tracks the policy rate."""
    config = MonetaryOperationsConfig()
    process = MonetaryOperationsProcess(config)
    assert process.central_bank_ledger.tracks_policy_rate is True
    assert process.central_bank_ledger.current_rate == config.initial_policy_rate
    assert not hasattr(process, "central_bank_rate")


def test_compute_actions_purchases_when_rate_falls() -> None:
    config = MonetaryOperationsConfig(initial_policy_rate=0.03, policy_rate_neutral=0.10)
    process = MonetaryOperationsProcess(config)
    # mean reversion pulls the rate UP toward a higher neutral -- rig a fall
    # instead with an explicit downward shock via the step's own shock list.
    from prometheus.econosim.shocks import Shock

    action = process.compute_actions(
        StepContext(
            step=1,
            step_date=date(2026, 1, 2),
            released=(),
            shocks=(Shock("s", 1, "policy_rate", -0.05),),
            economy=process.economy,
        )
    )
    assert action.rate_change < 0
    assert action.omo_side == "purchase"
    expected_amount = round(abs(action.rate_change) * config.omo_rate_sensitivity.minor_units)
    assert action.omo_amount == Money(expected_amount)


def test_compute_actions_sells_when_rate_rises() -> None:
    config = MonetaryOperationsConfig(initial_policy_rate=0.03, policy_rate_neutral=0.20)
    process = MonetaryOperationsProcess(config)
    action = process.compute_actions(_ctx(process, 1))
    assert action.rate_change > 0
    assert action.omo_side == "sell"


def test_compute_actions_omo_none_when_rate_unchanged() -> None:
    """Starting exactly at the neutral rate with no shocks, mean reversion
    contributes exactly zero and the rate is bit-for-bit unchanged."""
    config = MonetaryOperationsConfig(initial_policy_rate=0.03, policy_rate_neutral=0.03)
    process = MonetaryOperationsProcess(config)
    action = process.compute_actions(_ctx(process, 1))
    assert action.rate_change == 0.0
    assert action.omo_side == "none"
    assert action.omo_amount == Money.zero("USD")


def test_compute_actions_discount_window_lends_once_then_amortizes_then_stops() -> None:
    config = MonetaryOperationsConfig(
        discount_window_start_step=2,
        discount_window_principal=Money(10_000_00),
        discount_window_installment=Money(4_000_00),
    )
    process = MonetaryOperationsProcess(config)

    step1 = process.compute_actions(_ctx(process, 1))
    assert step1.discount_window_action == "none"

    step2 = process.compute_actions(_ctx(process, 2))
    assert step2.discount_window_action == "lend"
    assert step2.discount_window_amount == config.discount_window_principal
    process.clear_and_settle(_ctx(process, 2), step2)

    step3 = process.compute_actions(_ctx(process, 3))
    assert step3.discount_window_action == "repay"
    assert step3.discount_window_amount == Money(4_000_00)
    process.clear_and_settle(_ctx(process, 3), step3)

    step4 = process.compute_actions(_ctx(process, 4))
    assert step4.discount_window_action == "repay"
    assert step4.discount_window_amount == Money(4_000_00)
    process.clear_and_settle(_ctx(process, 4), step4)

    step5 = process.compute_actions(_ctx(process, 5))
    assert step5.discount_window_action == "repay"
    assert step5.discount_window_amount == Money(2_000_00)  # exact remainder, not overpaying
    process.clear_and_settle(_ctx(process, 5), step5)

    step6 = process.compute_actions(_ctx(process, 6))
    assert step6.discount_window_action == "none"


def test_compute_actions_schedules_interbank_transfer_on_the_configured_cadence() -> None:
    config = MonetaryOperationsConfig(interbank_transfer_every=3)
    process = MonetaryOperationsProcess(config)
    for step in range(1, 7):
        action = process.compute_actions(_ctx(process, step))
        if step % 3 == 0:
            assert action.interbank_transfer_amount == config.interbank_transfer_amount
        else:
            assert action.interbank_transfer_amount == Money.zero("USD")


def test_clear_and_settle_executes_purchase_and_moves_real_ledger_balances() -> None:
    from prometheus.econosim.monetary_operations import MonetaryAction

    config = MonetaryOperationsConfig(bank_a_bond_holdings=Money(100_000_00))
    process = MonetaryOperationsProcess(config)
    forced = MonetaryAction(
        step=1,
        policy_rate=0.03,
        rate_change=-0.01,
        omo_side="purchase",
        omo_amount=Money(30_000_00),
        discount_window_action="none",
        discount_window_amount=Money.zero("USD"),
        interbank_transfer_amount=Money.zero("USD"),
        interbank_loan_action="none",
        interbank_loan_amount=Money.zero("USD"),
    )
    settlement = process.clear_and_settle(_ctx(process, 1), forced)
    assert settlement.omo_executed
    assert settlement.omo_skipped_reason is None
    assert process.bank_a.loans_outstanding == Money(70_000_00)
    assert process.central_bank_ledger.settlement_balance_of(process.bank_a) == Money(30_000_00)
    assert process.central_bank_ledger.securities_holdings == Money(30_000_00)
    process.economy.check_integrity()


def test_clear_and_settle_skips_sell_gracefully_when_bank_lacks_bonds() -> None:
    from prometheus.econosim.monetary_operations import MonetaryAction

    config = MonetaryOperationsConfig(bank_a_bond_holdings=Money(1_000_00))
    process = MonetaryOperationsProcess(config)
    forced = MonetaryAction(
        step=1,
        policy_rate=0.05,
        rate_change=0.02,
        omo_side="sell",
        omo_amount=Money(50_000_00),
        discount_window_action="none",
        discount_window_amount=Money.zero("USD"),
        interbank_transfer_amount=Money.zero("USD"),
        interbank_loan_action="none",
        interbank_loan_amount=Money.zero("USD"),
    )
    settlement = process.clear_and_settle(_ctx(process, 1), forced)
    assert not settlement.omo_executed
    assert settlement.omo_skipped_reason is not None
    assert process.bank_a.loans_outstanding == config.bank_a_bond_holdings  # unchanged
    process.economy.check_integrity()


def test_clear_and_settle_skips_purchase_gracefully_when_bank_lacks_bonds_to_sell_to_cb() -> None:
    """A 'purchase' OMO buys bonds the bank must already hold (this ledger
    models the CB buying EXISTING bank-held bonds, not creating new ones);
    if the bank doesn't hold enough, the purchase itself must be skipped
    gracefully too, exactly like a 'sell' is."""
    from prometheus.econosim.monetary_operations import MonetaryAction

    config = MonetaryOperationsConfig(bank_a_bond_holdings=Money(1_00))
    process = MonetaryOperationsProcess(config)
    forced = MonetaryAction(
        step=1,
        policy_rate=0.02,
        rate_change=-0.01,
        omo_side="purchase",
        omo_amount=Money(50_000_00),
        discount_window_action="none",
        discount_window_amount=Money.zero("USD"),
        interbank_transfer_amount=Money.zero("USD"),
        interbank_loan_action="none",
        interbank_loan_amount=Money.zero("USD"),
    )
    settlement = process.clear_and_settle(_ctx(process, 1), forced)
    assert not settlement.omo_executed
    assert settlement.omo_skipped_reason is not None
    process.economy.check_integrity()


def test_clear_and_settle_skips_interbank_transfer_when_payer_balance_insufficient() -> None:
    from prometheus.econosim.monetary_operations import MonetaryAction

    process = MonetaryOperationsProcess(MonetaryOperationsConfig())
    forced = MonetaryAction(
        step=1,
        policy_rate=0.03,
        rate_change=0.0,
        omo_side="none",
        omo_amount=Money.zero("USD"),
        discount_window_action="none",
        discount_window_amount=Money.zero("USD"),
        interbank_transfer_amount=Money(1_00),
        interbank_loan_action="none",
        interbank_loan_amount=Money.zero("USD"),
    )
    settlement = process.clear_and_settle(_ctx(process, 1), forced)
    assert not settlement.interbank_transfer_executed
    assert settlement.interbank_transfer_skipped_reason is not None
    process.economy.check_integrity()


def test_discount_window_repayment_remaining_is_unchanged_after_a_skipped_repay() -> None:
    """A repay attempt that fails (insufficient settlement balance) must not
    silently advance the internal amortization schedule -- confirmed by
    draining bank_b's balance via an interbank transfer before its repay
    step, then checking the SAME amount is still owed afterward."""
    config = MonetaryOperationsConfig(
        discount_window_start_step=1,
        discount_window_principal=Money(10_000_00),
        discount_window_installment=Money(4_000_00),
        bank_a_bond_holdings=Money(200_000_00),
    )
    process = MonetaryOperationsProcess(config)
    cb = process.central_bank_ledger

    lend_action = process.compute_actions(_ctx(process, 1))
    process.clear_and_settle(_ctx(process, 1), lend_action)
    assert cb.loan_payable_of(process.bank_b) == Money(10_000_00)

    # drain bank_b's settlement balance entirely via a forced OMO-unrelated
    # interbank transfer from bank_b to bank_a (reusing the primitive directly)
    cb.settle_interbank_transfer(process.bank_b, process.bank_a, Money(10_000_00), step=2)
    assert cb.settlement_balance_of(process.bank_b) == Money.zero("USD")

    repay_action = process.compute_actions(_ctx(process, 2))
    assert repay_action.discount_window_action == "repay"
    settlement = process.clear_and_settle(_ctx(process, 2), repay_action)
    assert not settlement.discount_window_executed
    assert settlement.discount_window_skipped_reason is not None
    assert cb.loan_payable_of(process.bank_b) == Money(10_000_00)  # unchanged
    assert process._discount_window_remaining == Money(10_000_00)  # internal schedule intact


def test_full_engine_driven_run_keeps_ledger_identities_balanced_every_step() -> None:
    config = MonetaryOperationsConfig(n_steps=24)
    process = MonetaryOperationsProcess(config)
    rng = np.random.default_rng(0)
    shock_generator = ShockGenerator(
        rng, [ShockSpec(kind="policy_rate", mean=0.0, std=0.01, probability=1.0)]
    )
    engine = MacroTimeEngine(
        process.economy,
        BusinessDayCalendar(),
        config.start_date,
        shock_generator=shock_generator,
        hooks=StepHooks(
            compute_actions=process.compute_actions, clear_and_settle=process.clear_and_settle
        ),
    )

    steps = []
    for _ in range(config.n_steps):
        result = engine.advance_step()
        process.economy.check_integrity()
        steps.append(process.snapshot(result))

    assert len(steps) == config.n_steps
    assert all(isinstance(s.ledger_state_hash, str) and s.ledger_state_hash for s in steps)


def test_discount_window_fully_amortizes_to_zero_in_default_configuration() -> None:
    """The default principal (200,000) is an exact multiple of the
    installment (20,000): after enough steps the loan is fully, exactly
    repaid, not left with a lingering fractional balance."""
    config = MonetaryOperationsConfig(n_steps=15)
    process = MonetaryOperationsProcess(config)
    engine = MacroTimeEngine(
        process.economy,
        BusinessDayCalendar(),
        config.start_date,
        hooks=StepHooks(
            compute_actions=process.compute_actions, clear_and_settle=process.clear_and_settle
        ),
    )
    last_step = None
    for _ in range(config.n_steps):
        result = engine.advance_step()
        last_step = process.snapshot(result)
    assert last_step is not None
    assert last_step.bank_b_loan_payable == Money.zero("USD")


def test_bank_b_settlement_balance_reconciles_exactly_with_successful_transfers() -> None:
    """After the discount-window loan is fully repaid (net zero contribution
    to bank_b's settlement balance), bank_b's final balance must equal
    EXACTLY the count of successfully executed interbank transfers times
    the configured transfer amount -- an exact ledger reconciliation, not
    an approximate check."""
    config = MonetaryOperationsConfig(n_steps=24, interbank_transfer_every=3)
    process = MonetaryOperationsProcess(config)
    rng = np.random.default_rng(1)
    shock_generator = ShockGenerator(
        rng, [ShockSpec(kind="policy_rate", mean=0.0, std=0.015, probability=1.0)]
    )
    engine = MacroTimeEngine(
        process.economy,
        BusinessDayCalendar(),
        config.start_date,
        shock_generator=shock_generator,
        hooks=StepHooks(
            compute_actions=process.compute_actions, clear_and_settle=process.clear_and_settle
        ),
    )

    successful_transfers = 0
    last_step = None
    for _ in range(config.n_steps):
        result = engine.advance_step()
        step = process.snapshot(result)
        if step.settlement.interbank_transfer_executed:
            successful_transfers += 1
        last_step = step
    assert last_step is not None
    assert last_step.bank_b_loan_payable == Money.zero("USD")
    expected = Money(successful_transfers * config.interbank_transfer_amount.minor_units)
    assert last_step.bank_b_settlement_balance == expected


def test_same_seed_produces_identical_state_hashes() -> None:
    def run(seed: int) -> list[str]:
        config = MonetaryOperationsConfig(n_steps=12)
        process = MonetaryOperationsProcess(config)
        rng = np.random.default_rng(seed)
        shock_generator = ShockGenerator(
            rng, [ShockSpec(kind="policy_rate", mean=0.0, std=0.01, probability=1.0)]
        )
        engine = MacroTimeEngine(
            process.economy,
            BusinessDayCalendar(),
            config.start_date,
            shock_generator=shock_generator,
            hooks=StepHooks(
                compute_actions=process.compute_actions,
                clear_and_settle=process.clear_and_settle,
            ),
        )
        hashes = []
        for _ in range(config.n_steps):
            hashes.append(engine.advance_step().state_hash)
        return hashes

    assert run(42) == run(42)


def test_different_seeds_produce_different_state_hashes() -> None:
    def run(seed: int) -> list[str]:
        config = MonetaryOperationsConfig(n_steps=12)
        process = MonetaryOperationsProcess(config)
        rng = np.random.default_rng(seed)
        shock_generator = ShockGenerator(
            rng, [ShockSpec(kind="policy_rate", mean=0.0, std=0.02, probability=1.0)]
        )
        engine = MacroTimeEngine(
            process.economy,
            BusinessDayCalendar(),
            config.start_date,
            shock_generator=shock_generator,
            hooks=StepHooks(
                compute_actions=process.compute_actions,
                clear_and_settle=process.clear_and_settle,
            ),
        )
        hashes = []
        for _ in range(config.n_steps):
            hashes.append(engine.advance_step().state_hash)
        return hashes

    assert run(1) != run(2)


def test_config_rejects_invalid_policy_rate_shock_std() -> None:
    with pytest.raises(ValueError):
        MonetaryOperationsConfig(policy_rate_shock_std=-0.01)
    with pytest.raises(ValueError):
        MonetaryOperationsConfig(policy_rate_shock_std=float("inf"))


def test_from_dict_round_trips_every_field() -> None:
    from dataclasses import asdict

    config = MonetaryOperationsConfig(n_steps=7, seed=5, policy_rate_shock_std=0.02)
    payload = asdict(config)
    restored = MonetaryOperationsConfig.from_dict(payload)
    assert restored == config


def test_from_dict_rejects_incomplete_payload() -> None:
    from dataclasses import asdict

    payload = asdict(MonetaryOperationsConfig())
    del payload["n_steps"]
    with pytest.raises(ValueError):
        MonetaryOperationsConfig.from_dict(payload)


def test_from_dict_rejects_invalid_money_encoding() -> None:
    from dataclasses import asdict

    payload = asdict(MonetaryOperationsConfig())
    payload["bank_a_capital"] = {"minor_units": "not-an-int", "currency": "USD"}
    with pytest.raises(ValueError):
        MonetaryOperationsConfig.from_dict(payload)


def test_from_dict_decodes_iso_start_date_string() -> None:
    from dataclasses import asdict

    payload = asdict(MonetaryOperationsConfig())
    payload["start_date"] = "2026-03-01"
    restored = MonetaryOperationsConfig.from_dict(payload)
    assert restored.start_date == date(2026, 3, 1)


def test_config_rejects_interbank_loan_start_step_beyond_n_steps() -> None:
    with pytest.raises(ValueError):
        MonetaryOperationsConfig(n_steps=5, interbank_loan_start_step=6)


def test_config_rejects_invalid_contagion_check_every() -> None:
    with pytest.raises(ValueError):
        MonetaryOperationsConfig(contagion_check_every=0)


def test_compute_actions_interbank_loan_lends_once_then_amortizes_then_stops() -> None:
    config = MonetaryOperationsConfig(
        interbank_loan_start_step=2,
        interbank_loan_principal=Money(10_000_00),
        interbank_loan_installment=Money(4_000_00),
    )
    process = MonetaryOperationsProcess(config)

    step1 = process.compute_actions(_ctx(process, 1))
    assert step1.interbank_loan_action == "none"

    step2 = process.compute_actions(_ctx(process, 2))
    assert step2.interbank_loan_action == "lend"
    assert step2.interbank_loan_amount == config.interbank_loan_principal
    process.clear_and_settle(_ctx(process, 2), step2)

    step3 = process.compute_actions(_ctx(process, 3))
    assert step3.interbank_loan_action == "repay"
    assert step3.interbank_loan_amount == Money(4_000_00)
    process.clear_and_settle(_ctx(process, 3), step3)

    step4 = process.compute_actions(_ctx(process, 4))
    process.clear_and_settle(_ctx(process, 4), step4)

    step5 = process.compute_actions(_ctx(process, 5))
    assert step5.interbank_loan_action == "repay"
    assert step5.interbank_loan_amount == Money(2_000_00)  # exact remainder
    process.clear_and_settle(_ctx(process, 5), step5)

    step6 = process.compute_actions(_ctx(process, 6))
    assert step6.interbank_loan_action == "none"


def test_clear_and_settle_executes_interbank_loan_and_moves_real_ledger_balances() -> None:
    config = MonetaryOperationsConfig(interbank_loan_start_step=1)
    process = MonetaryOperationsProcess(config)
    action = process.compute_actions(_ctx(process, 1))
    assert action.interbank_loan_action == "lend"

    settlement = process.clear_and_settle(_ctx(process, 1), action)

    assert settlement.interbank_loan_executed
    assert settlement.interbank_loan_skipped_reason is None
    assert process.interbank_market.exposure(process.bank_a, process.bank_b) == (
        config.interbank_loan_principal
    )
    process.economy.check_integrity()


def test_clear_and_settle_skips_interbank_loan_gracefully_when_lender_lacks_capacity() -> None:
    """Unlike the discount-window 'lend' (unconditional CB money creation),
    a real InterbankMarket loan is capped by the lender's own leverage;
    exceeding it must be skipped and recorded, not allowed to crash the
    whole step."""
    from prometheus.econosim.monetary_operations import MonetaryAction

    config = MonetaryOperationsConfig(
        bank_a_capital=Money(10_00),
        max_leverage=1.0,
        interbank_loan_start_step=1,
        bank_a_bond_holdings=Money(0),
    )
    process = MonetaryOperationsProcess(config)
    forced = MonetaryAction(
        step=1,
        policy_rate=0.03,
        rate_change=0.0,
        omo_side="none",
        omo_amount=Money.zero("USD"),
        discount_window_action="none",
        discount_window_amount=Money.zero("USD"),
        interbank_transfer_amount=Money.zero("USD"),
        interbank_loan_action="lend",
        interbank_loan_amount=Money(1_000_000_00),  # far beyond bank_a's tiny capacity
    )
    settlement = process.clear_and_settle(_ctx(process, 1), forced)
    assert not settlement.interbank_loan_executed
    assert settlement.interbank_loan_skipped_reason is not None
    assert process.interbank_market.exposure(process.bank_a, process.bank_b) == Money.zero("USD")
    process.economy.check_integrity()


def test_clear_and_settle_skips_interbank_loan_repayment_when_borrower_lacks_funds() -> None:
    """Mirrors the discount-window equivalent: draining bank_b's reserves
    via a further loan out before its repayment step must be skipped and
    recorded, not raise."""
    config = MonetaryOperationsConfig(
        interbank_loan_start_step=1,
        interbank_loan_principal=Money(10_000_00),
        interbank_loan_installment=Money(4_000_00),
    )
    process = MonetaryOperationsProcess(config)
    lend_action = process.compute_actions(_ctx(process, 1))
    process.clear_and_settle(_ctx(process, 1), lend_action)

    bank_outside = process.economy.add_bank("bank_outside", max_leverage=50.0)
    bank_outside.capitalize(Money(10_00))
    bank_b_reserves = process.economy.ledger.account(process.bank_b.reserves_account).balance
    process.interbank_market.lend(process.bank_b, bank_outside, bank_b_reserves)

    repay_action = process.compute_actions(_ctx(process, 2))
    assert repay_action.interbank_loan_action == "repay"
    settlement = process.clear_and_settle(_ctx(process, 2), repay_action)

    assert not settlement.interbank_loan_executed
    assert settlement.interbank_loan_skipped_reason is not None
    assert process._interbank_loan_remaining == config.interbank_loan_principal  # unchanged


def test_periodic_contagion_check_reports_no_default_in_the_default_configuration() -> None:
    config = MonetaryOperationsConfig(n_steps=12, contagion_check_every=3)
    process = MonetaryOperationsProcess(config)
    engine_results = []
    for step in range(1, config.n_steps + 1):
        action = process.compute_actions(_ctx(process, step))
        settlement = process.clear_and_settle(_ctx(process, step), action)
        engine_results.append(settlement)

    checks = [s.contagion_check for s in engine_results if s.contagion_check is not None]
    assert len(checks) == config.n_steps // config.contagion_check_every
    assert all(not check.any_defaulted for check in checks)
    assert all(check.worst_creditor_loss == Money.zero("USD") for check in checks)


def test_contagion_check_is_skipped_on_steps_not_matching_the_cadence() -> None:
    config = MonetaryOperationsConfig(contagion_check_every=5)
    process = MonetaryOperationsProcess(config)
    action = process.compute_actions(_ctx(process, 3))
    settlement = process.clear_and_settle(_ctx(process, 3), action)
    assert settlement.contagion_check is None


def test_periodic_contagion_check_detects_a_genuine_default() -> None:
    """Directly engineer a real default (bank_b borrows from bank_a, then
    relends every bit of its reserves to a third bank outside the
    analyzed pair) and confirm the process's own periodic check -- the
    exact machinery wired into clear_and_settle -- reports it, rather
    than testing network_risk/contagion in isolation again."""
    from prometheus.econosim.monetary_operations import MonetaryAction

    config = MonetaryOperationsConfig(contagion_check_every=1, bank_a_bond_holdings=Money(0))
    process = MonetaryOperationsProcess(config)

    process.interbank_market.lend(process.bank_a, process.bank_b, Money(100_000_00))
    bank_outside = process.economy.add_bank("bank_outside", max_leverage=50.0)
    bank_outside.capitalize(Money(10_00))
    drained_amount = process.economy.ledger.account(process.bank_b.reserves_account).balance
    process.interbank_market.lend(process.bank_b, bank_outside, drained_amount)

    zero = Money.zero("USD")
    action = MonetaryAction(
        step=1,
        policy_rate=0.03,
        rate_change=0.0,
        omo_side="none",
        omo_amount=zero,
        discount_window_action="none",
        discount_window_amount=zero,
        interbank_transfer_amount=zero,
        interbank_loan_action="none",
        interbank_loan_amount=zero,
    )
    settlement = process.clear_and_settle(_ctx(process, 1), action)

    assert settlement.contagion_check is not None
    assert settlement.contagion_check.any_defaulted
    assert settlement.contagion_check.worst_creditor_loss == Money(100_000_00)


def test_snapshot_reports_bank_a_to_bank_b_interbank_exposure() -> None:
    from prometheus.econosim.time_engine import StepResult

    config = MonetaryOperationsConfig(interbank_loan_start_step=1)
    process = MonetaryOperationsProcess(config)
    action = process.compute_actions(_ctx(process, 1))
    settlement = process.clear_and_settle(_ctx(process, 1), action)

    result = StepResult(
        step=1,
        step_date=date(2026, 1, 2),
        released=(),
        shocks=(),
        state_hash="irrelevant",
        actions=action,
        settlement=settlement,
    )
    step = process.snapshot(result)
    assert step.bank_a_to_bank_b_interbank_exposure == config.interbank_loan_principal


def test_process_starts_unfrozen() -> None:
    process = MonetaryOperationsProcess(MonetaryOperationsConfig())
    assert process._risk_frozen is False


def test_a_detected_default_freezes_future_new_lending_but_not_repayment() -> None:
    """The circuit breaker: once the periodic check ever detects a
    default, a discount-window loan scheduled for a LATER step must never
    be extended, even though nothing about that specific loan request
    changed -- only the process's own risk state did."""
    config = MonetaryOperationsConfig(
        contagion_check_every=1,
        interbank_loan_start_step=1,
        discount_window_start_step=3,
        bank_a_bond_holdings=Money(0),
    )
    process = MonetaryOperationsProcess(config)

    action1 = process.compute_actions(_ctx(process, 1))
    settlement1 = process.clear_and_settle(_ctx(process, 1), action1)
    assert settlement1.interbank_loan_executed
    assert not process._risk_frozen

    bank_outside = process.economy.add_bank("bank_outside", max_leverage=50.0)
    bank_outside.capitalize(Money(10_00))
    drained = process.economy.ledger.account(process.bank_b.reserves_account).balance
    process.interbank_market.lend(process.bank_b, bank_outside, drained)

    action2 = process.compute_actions(_ctx(process, 2))
    settlement2 = process.clear_and_settle(_ctx(process, 2), action2)
    assert settlement2.contagion_check is not None
    assert settlement2.contagion_check.any_defaulted
    assert process._risk_frozen

    action3 = process.compute_actions(_ctx(process, 3))
    assert action3.discount_window_action == "none"
    settlement3 = process.clear_and_settle(_ctx(process, 3), action3)
    assert not settlement3.discount_window_executed
    assert process.central_bank_ledger.loan_payable_of(process.bank_b) == Money.zero("USD")


def test_frozen_state_does_not_block_amortization_of_existing_debt() -> None:
    """The freeze must only suspend NEW lending, never existing
    repayment -- a loan already extended before the freeze still
    amortizes exactly on schedule afterward."""
    config = MonetaryOperationsConfig(
        contagion_check_every=1,
        discount_window_start_step=1,
        discount_window_principal=Money(10_000_00),
        discount_window_installment=Money(5_000_00),
        interbank_loan_start_step=2,
        bank_a_bond_holdings=Money(0),
    )
    process = MonetaryOperationsProcess(config)

    lend_action = process.compute_actions(_ctx(process, 1))
    process.clear_and_settle(_ctx(process, 1), lend_action)
    assert process.central_bank_ledger.loan_payable_of(process.bank_b) == Money(10_000_00)

    # engineer a default via the (not-yet-triggered) interbank channel directly
    process.interbank_market.lend(process.bank_a, process.bank_b, Money(1_00))
    bank_outside = process.economy.add_bank("bank_outside", max_leverage=50.0)
    bank_outside.capitalize(Money(10_00))
    drained = process.economy.ledger.account(process.bank_b.reserves_account).balance
    process.interbank_market.lend(process.bank_b, bank_outside, drained)

    action2 = process.compute_actions(_ctx(process, 2))
    settlement2 = process.clear_and_settle(_ctx(process, 2), action2)
    assert settlement2.contagion_check is not None and settlement2.contagion_check.any_defaulted
    assert process._risk_frozen

    # the discount-window loan taken out BEFORE the freeze must still amortize
    assert action2.discount_window_action == "repay"
    assert settlement2.discount_window_executed
    assert process.central_bank_ledger.loan_payable_of(process.bank_b) == Money(5_000_00)


def test_snapshot_reports_risk_frozen_state() -> None:
    from prometheus.econosim.time_engine import StepResult

    config = MonetaryOperationsConfig(contagion_check_every=1, bank_a_bond_holdings=Money(0))
    process = MonetaryOperationsProcess(config)

    process.interbank_market.lend(process.bank_a, process.bank_b, Money(100_000_00))
    bank_outside = process.economy.add_bank("bank_outside", max_leverage=50.0)
    bank_outside.capitalize(Money(10_00))
    drained = process.economy.ledger.account(process.bank_b.reserves_account).balance
    process.interbank_market.lend(process.bank_b, bank_outside, drained)

    action = process.compute_actions(_ctx(process, 1))
    settlement = process.clear_and_settle(_ctx(process, 1), action)
    result = StepResult(
        step=1,
        step_date=date(2026, 1, 2),
        released=(),
        shocks=(),
        state_hash="irrelevant",
        actions=action,
        settlement=settlement,
    )
    step = process.snapshot(result)
    assert step.risk_frozen is True
