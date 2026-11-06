import pytest

from prometheus.core.ledger import Ledger, Sector
from prometheus.core.money import Money
from prometheus.econosim.agents import Bank, Government, InsufficientFundsError
from prometheus.econosim.central_bank_ledger import (
    BankAlreadyRegisteredError,
    CentralBankLedger,
    NoPolicyRateRuleError,
    UnregisteredBankError,
)
from prometheus.econosim.policy_rate import CentralBank, PolicyRateRule
from prometheus.econosim.shocks import Shock


def usd(major_units: float) -> Money:
    return Money(int(round(major_units * 100)), "USD")


def _bank_own_balance_sheet(
    ledger: Ledger, bank: Bank, cb: CentralBankLedger
) -> dict[str, Money]:
    """Manually sum only THIS bank's own accounts (including its two
    central-bank-linked ones) -- unlike `Ledger.balance_sheet`, which sums
    an entire sector across every agent instance sharing it. Used to prove
    each individual bank stays balanced, not just the BANK sector in
    aggregate."""
    assets = bank.loans_outstanding + ledger.account(bank.reserves_account).balance
    assets += cb.settlement_balance_of(bank)
    liabilities = ledger.account(bank.deposits_account).balance
    liabilities += cb.loan_payable_of(bank)
    equity = bank.capital
    return {
        "assets": assets,
        "liabilities": liabilities,
        "equity": equity,
        "residual": assets - liabilities - equity,
    }


@pytest.fixture
def setup() -> tuple[Ledger, Bank, Bank, Government, CentralBankLedger]:
    ledger = Ledger()
    bank_a = Bank(ledger, "bank_a", max_leverage=50.0)
    bank_b = Bank(ledger, "bank_b", max_leverage=50.0)
    gov = Government(ledger, "gov")
    cb = CentralBankLedger(ledger, "cb")
    bank_a.capitalize(usd(1000))
    bank_b.capitalize(usd(1000))
    cb.register_bank(bank_a)
    cb.register_bank(bank_b)
    return ledger, bank_a, bank_b, gov, cb


def test_register_bank_opens_zero_balance_linked_accounts(
    setup: tuple[Ledger, Bank, Bank, Government, CentralBankLedger],
) -> None:
    ledger, bank_a, _, _, cb = setup
    assert cb.settlement_balance_of(bank_a) == Money.zero("USD")
    assert cb.reserve_liability_to(bank_a) == Money.zero("USD")
    assert cb.loan_payable_of(bank_a) == Money.zero("USD")


def test_register_bank_twice_raises(
    setup: tuple[Ledger, Bank, Bank, Government, CentralBankLedger],
) -> None:
    _, bank_a, _, _, cb = setup
    with pytest.raises(BankAlreadyRegisteredError):
        cb.register_bank(bank_a)


def test_unregistered_bank_raises(
    setup: tuple[Ledger, Bank, Bank, Government, CentralBankLedger],
) -> None:
    ledger, _, _, _, _ = setup
    outsider = Bank(ledger, "outsider", max_leverage=50.0)
    cb_other = CentralBankLedger(ledger, "cb_other")
    with pytest.raises(UnregisteredBankError):
        cb_other.purchase_government_bonds(outsider, usd(10))


def test_purchase_government_bonds_moves_bonds_for_reserves(
    setup: tuple[Ledger, Bank, Bank, Government, CentralBankLedger],
) -> None:
    ledger, bank_a, _, gov, cb = setup
    gov.issue_bonds(bank_a, usd(500))
    loans_before = bank_a.loans_outstanding

    cb.purchase_government_bonds(bank_a, usd(300))

    assert bank_a.loans_outstanding == loans_before - usd(300)
    assert cb.settlement_balance_of(bank_a) == usd(300)
    assert cb.securities_holdings == usd(300)
    assert cb.reserve_liability_to(bank_a) == usd(300)
    ledger.check_identities("USD")


def test_purchase_government_bonds_rejects_amount_exceeding_bank_loans(
    setup: tuple[Ledger, Bank, Bank, Government, CentralBankLedger],
) -> None:
    _, bank_a, _, gov, cb = setup
    gov.issue_bonds(bank_a, usd(100))
    with pytest.raises(ValueError):
        cb.purchase_government_bonds(bank_a, usd(200))


def test_purchase_government_bonds_rejects_non_positive_amount(
    setup: tuple[Ledger, Bank, Bank, Government, CentralBankLedger],
) -> None:
    _, bank_a, _, _, cb = setup
    with pytest.raises(ValueError):
        cb.purchase_government_bonds(bank_a, usd(0))


def test_sell_government_bonds_is_the_exact_reverse_of_purchase(
    setup: tuple[Ledger, Bank, Bank, Government, CentralBankLedger],
) -> None:
    ledger, bank_a, _, gov, cb = setup
    gov.issue_bonds(bank_a, usd(500))
    loans_before = bank_a.loans_outstanding

    cb.purchase_government_bonds(bank_a, usd(300))
    cb.sell_government_bonds(bank_a, usd(300))

    assert bank_a.loans_outstanding == loans_before
    assert cb.settlement_balance_of(bank_a) == Money.zero("USD")
    assert cb.securities_holdings == Money.zero("USD")
    assert cb.reserve_liability_to(bank_a) == Money.zero("USD")
    ledger.check_identities("USD")


def test_sell_government_bonds_rejects_non_positive_amount(
    setup: tuple[Ledger, Bank, Bank, Government, CentralBankLedger],
) -> None:
    _, bank_a, _, _, cb = setup
    with pytest.raises(ValueError):
        cb.sell_government_bonds(bank_a, usd(0))


def test_sell_government_bonds_rejects_exceeding_cb_securities(
    setup: tuple[Ledger, Bank, Bank, Government, CentralBankLedger],
) -> None:
    _, bank_a, _, gov, cb = setup
    gov.issue_bonds(bank_a, usd(500))
    cb.purchase_government_bonds(bank_a, usd(100))
    with pytest.raises(ValueError):
        cb.sell_government_bonds(bank_a, usd(200))


def test_sell_government_bonds_rejects_insufficient_bank_settlement_balance(
    setup: tuple[Ledger, Bank, Bank, Government, CentralBankLedger],
) -> None:
    _, bank_a, bank_b, gov, cb = setup
    gov.issue_bonds(bank_a, usd(500))
    cb.purchase_government_bonds(bank_a, usd(300))
    cb.settle_interbank_transfer(bank_a, bank_b, usd(250))  # drains bank_a to 50

    with pytest.raises(InsufficientFundsError):
        cb.sell_government_bonds(bank_a, usd(100))


def test_lend_to_bank_and_repay_round_trip_exactly(
    setup: tuple[Ledger, Bank, Bank, Government, CentralBankLedger],
) -> None:
    ledger, bank_a, _, _, cb = setup

    cb.lend_to_bank(bank_a, usd(100))
    assert cb.settlement_balance_of(bank_a) == usd(100)
    assert cb.loan_payable_of(bank_a) == usd(100)
    assert cb.loans_to_banks_outstanding == usd(100)
    assert cb.reserve_liability_to(bank_a) == usd(100)
    ledger.check_identities("USD")

    cb.repay_central_bank_loan(bank_a, usd(100))
    assert cb.settlement_balance_of(bank_a) == Money.zero("USD")
    assert cb.loan_payable_of(bank_a) == Money.zero("USD")
    assert cb.loans_to_banks_outstanding == Money.zero("USD")
    assert cb.reserve_liability_to(bank_a) == Money.zero("USD")
    ledger.check_identities("USD")


def test_lend_to_bank_rejects_non_positive_amount(
    setup: tuple[Ledger, Bank, Bank, Government, CentralBankLedger],
) -> None:
    _, bank_a, _, _, cb = setup
    with pytest.raises(ValueError):
        cb.lend_to_bank(bank_a, usd(-5))


def test_repay_central_bank_loan_rejects_non_positive_amount(
    setup: tuple[Ledger, Bank, Bank, Government, CentralBankLedger],
) -> None:
    _, bank_a, _, _, cb = setup
    with pytest.raises(ValueError):
        cb.repay_central_bank_loan(bank_a, usd(0))


def test_repay_central_bank_loan_rejects_amount_exceeding_outstanding(
    setup: tuple[Ledger, Bank, Bank, Government, CentralBankLedger],
) -> None:
    _, bank_a, _, _, cb = setup
    cb.lend_to_bank(bank_a, usd(50))
    with pytest.raises(ValueError):
        cb.repay_central_bank_loan(bank_a, usd(100))


def test_repay_central_bank_loan_rejects_insufficient_settlement_balance(
    setup: tuple[Ledger, Bank, Bank, Government, CentralBankLedger],
) -> None:
    _, bank_a, bank_b, _, cb = setup
    cb.lend_to_bank(bank_a, usd(50))
    cb.settle_interbank_transfer(bank_a, bank_b, usd(45))  # leaves bank_a with 5

    with pytest.raises(InsufficientFundsError):
        cb.repay_central_bank_loan(bank_a, usd(50))


def test_settle_interbank_transfer_reallocates_without_changing_total_liability(
    setup: tuple[Ledger, Bank, Bank, Government, CentralBankLedger],
) -> None:
    ledger, bank_a, bank_b, _, cb = setup
    cb.lend_to_bank(bank_a, usd(200))
    total_before = cb.reserve_liability_to(bank_a) + cb.reserve_liability_to(bank_b)

    cb.settle_interbank_transfer(bank_a, bank_b, usd(75))

    assert cb.settlement_balance_of(bank_a) == usd(125)
    assert cb.settlement_balance_of(bank_b) == usd(75)
    assert cb.reserve_liability_to(bank_a) == usd(125)
    assert cb.reserve_liability_to(bank_b) == usd(75)
    total_after = cb.reserve_liability_to(bank_a) + cb.reserve_liability_to(bank_b)
    assert total_after == total_before
    ledger.check_identities("USD")


def test_cross_bank_transfer_preserves_total_settlement_balances_system_wide(
    setup: tuple[Ledger, Bank, Bank, Government, CentralBankLedger],
) -> None:
    """LED-08's own literal acceptance wording: "cross-bank transfer
    preserves total settlement balances." Checked across a THIRD bank
    not party to the transfer at all, not just the two-bank case above
    (where "total preserved" is less discriminating, since a sum over
    exactly the two parties that swapped it trivially nets to zero
    either way) -- the system-wide total across every registered bank
    must still be unchanged."""
    ledger, bank_a, bank_b, _, cb = setup
    bank_c = Bank(ledger, "bank_c", max_leverage=50.0)
    bank_c.capitalize(usd(1000))
    cb.register_bank(bank_c)
    cb.lend_to_bank(bank_a, usd(500))
    cb.lend_to_bank(bank_c, usd(300))

    def total_settlement_balance() -> Money:
        return (
            cb.settlement_balance_of(bank_a)
            + cb.settlement_balance_of(bank_b)
            + cb.settlement_balance_of(bank_c)
        )

    total_before = total_settlement_balance()
    cb.settle_interbank_transfer(bank_a, bank_b, usd(150))
    assert total_settlement_balance() == total_before  # bank_c untouched, total unchanged

    cb.settle_interbank_transfer(bank_c, bank_b, usd(100))
    assert total_settlement_balance() == total_before
    ledger.check_identities("USD")


def test_settle_interbank_transfer_rejects_self_transfer(
    setup: tuple[Ledger, Bank, Bank, Government, CentralBankLedger],
) -> None:
    _, bank_a, _, _, cb = setup
    with pytest.raises(ValueError):
        cb.settle_interbank_transfer(bank_a, bank_a, usd(10))


def test_settle_interbank_transfer_rejects_non_positive_amount(
    setup: tuple[Ledger, Bank, Bank, Government, CentralBankLedger],
) -> None:
    _, bank_a, bank_b, _, cb = setup
    with pytest.raises(ValueError):
        cb.settle_interbank_transfer(bank_a, bank_b, usd(0))


def test_settle_interbank_transfer_rejects_insufficient_payer_balance(
    setup: tuple[Ledger, Bank, Bank, Government, CentralBankLedger],
) -> None:
    _, bank_a, bank_b, _, cb = setup
    with pytest.raises(InsufficientFundsError):
        cb.settle_interbank_transfer(bank_a, bank_b, usd(1))


def test_multi_channel_sequence_keeps_ledger_and_per_bank_identities_balanced(
    setup: tuple[Ledger, Bank, Bank, Government, CentralBankLedger],
) -> None:
    """Exercises all three channels (OMO, discount window, interbank
    settlement) in one sequence against two *different* Bank instances
    sharing Sector.BANK, re-checking after every single step that the
    ledger's own sector-wide identity check passes. OMO and discount-window
    operations also keep each bank individually balanced -- summed by hand
    across only that bank's own accounts, a strictly finer-grained check
    than the ledger provides natively -- because both legs of those
    transactions land on the SAME bank's book. `settle_interbank_transfer`
    is the one exception, by design (see its own docstring): it moves only
    the reserve leg, so it shifts each bank's individual residual by
    exactly the transferred amount without changing the sector-wide total.
    """
    ledger, bank_a, bank_b, gov, cb = setup

    def assert_sector_balanced() -> None:
        ledger.check_identities("USD")

    def assert_each_bank_individually_balanced() -> None:
        for bank in (bank_a, bank_b):
            sheet = _bank_own_balance_sheet(ledger, bank, cb)
            assert sheet["residual"] == Money.zero("USD")

    assert_sector_balanced()
    assert_each_bank_individually_balanced()

    gov.issue_bonds(bank_a, usd(500))
    assert_sector_balanced()
    assert_each_bank_individually_balanced()

    cb.purchase_government_bonds(bank_a, usd(300))
    assert_sector_balanced()
    assert_each_bank_individually_balanced()

    cb.lend_to_bank(bank_b, usd(100))
    assert_sector_balanced()
    assert_each_bank_individually_balanced()

    residual_a_before = _bank_own_balance_sheet(ledger, bank_a, cb)["residual"]
    residual_b_before = _bank_own_balance_sheet(ledger, bank_b, cb)["residual"]
    cb.settle_interbank_transfer(bank_a, bank_b, usd(150))
    assert_sector_balanced()  # sector-wide identity still holds
    residual_a_after = _bank_own_balance_sheet(ledger, bank_a, cb)["residual"]
    residual_b_after = _bank_own_balance_sheet(ledger, bank_b, cb)["residual"]
    # each bank's own residual moves by exactly the transferred amount, in
    # opposite directions, netting to zero across the sector as a whole --
    # not a bug, the documented limitation of this one operation.
    assert residual_a_after == residual_a_before - usd(150)
    assert residual_b_after == residual_b_before + usd(150)
    assert (residual_a_after - residual_a_before) + (residual_b_after - residual_b_before) == (
        Money.zero("USD")
    )

    cb.sell_government_bonds(bank_a, usd(100))
    assert_sector_balanced()

    cb.repay_central_bank_loan(bank_b, usd(40))
    assert_sector_balanced()

    # Sanity on final state: nothing drifted to a nonsensical sign.
    assert cb.securities_holdings >= Money.zero("USD")
    assert cb.loans_to_banks_outstanding >= Money.zero("USD")
    assert cb.settlement_balance_of(bank_a) >= Money.zero("USD")
    assert cb.settlement_balance_of(bank_b) >= Money.zero("USD")


def test_central_bank_equity_stays_zero_throughout(
    setup: tuple[Ledger, Bank, Bank, Government, CentralBankLedger],
) -> None:
    """Every issuance channel is exactly asset-for-liability; the central
    bank's own equity account should never move away from zero."""
    ledger, bank_a, bank_b, gov, cb = setup
    gov.issue_bonds(bank_a, usd(500))
    cb.purchase_government_bonds(bank_a, usd(300))
    cb.lend_to_bank(bank_b, usd(100))
    cb.settle_interbank_transfer(bank_a, bank_b, usd(50))
    cb.sell_government_bonds(bank_a, usd(50))
    cb.repay_central_bank_loan(bank_b, usd(30))

    assert ledger.account(cb.equity_account).balance == Money.zero("USD")
    sheet = ledger.balance_sheet(Sector.CENTRAL_BANK)
    assert sheet["assets"] == sheet["liabilities"]


def test_without_a_rate_rule_tracks_policy_rate_is_false() -> None:
    cb = CentralBankLedger(Ledger(), "cb")
    assert cb.tracks_policy_rate is False
    assert cb.current_rate is None


def test_without_a_rate_rule_step_rate_raises_a_clear_error() -> None:
    cb = CentralBankLedger(Ledger(), "cb")
    with pytest.raises(NoPolicyRateRuleError):
        cb.step_rate([])


def test_rejects_rate_rule_without_initial_rate() -> None:
    rule = PolicyRateRule(neutral_rate=0.03, mean_reversion_speed=0.5, dt=1 / 12)
    with pytest.raises(ValueError):
        CentralBankLedger(Ledger(), "cb", rate_rule=rule)


def test_rejects_initial_rate_without_rate_rule() -> None:
    with pytest.raises(ValueError):
        CentralBankLedger(Ledger(), "cb", initial_rate=0.03)


def test_with_a_rate_rule_tracks_policy_rate_is_true() -> None:
    rule = PolicyRateRule(neutral_rate=0.03, mean_reversion_speed=0.5, dt=1 / 12)
    cb = CentralBankLedger(Ledger(), "cb", rate_rule=rule, initial_rate=0.05)
    assert cb.tracks_policy_rate is True
    assert cb.current_rate == 0.05


def test_step_rate_matches_the_standalone_central_bank_wrapper_exactly() -> None:
    """step_rate must be bit-for-bit identical to policy_rate.CentralBank.step
    across many steps, including a shocked one -- it calls the exact same
    PolicyRateRule.step, not a reimplementation of the same formula."""
    rule = PolicyRateRule(neutral_rate=0.03, mean_reversion_speed=0.5, dt=1 / 12)
    unified = CentralBankLedger(Ledger(), "cb", rate_rule=rule, initial_rate=0.08)
    standalone = CentralBank(agent_id="cb_standalone", rule=rule, current_rate=0.08)

    for t in range(1, 13):
        shocks = [Shock("s", t, "policy_rate", 0.001)] if t == 5 else []
        unified_rate = unified.step_rate(shocks)
        standalone_rate = standalone.step(shocks)
        assert unified_rate == pytest.approx(standalone_rate, abs=1e-15)
    assert unified.current_rate == pytest.approx(standalone.current_rate, abs=1e-15)


def test_a_bank_cannot_be_registered_with_two_different_central_banks() -> None:
    """A limitation surfaced while building PR-041, documented in the
    module docstring rather than discovered by accident: register_bank's
    linked account names are keyed only by bank_id, so a second
    registration with a DIFFERENT CentralBankLedger collides on the
    exact same account name."""
    from prometheus.core.ledger import DuplicateAccountError

    ledger = Ledger()
    bank_a = Bank(ledger, "bank_a", max_leverage=50.0)
    cb1 = CentralBankLedger(ledger, "cb1")
    cb2 = CentralBankLedger(ledger, "cb2")
    cb1.register_bank(bank_a)
    with pytest.raises(DuplicateAccountError):
        cb2.register_bank(bank_a)


def test_unified_central_bank_can_still_operate_its_balance_sheet() -> None:
    """A rate-tracking CentralBankLedger is still a fully functional
    balance-sheet agent -- the two capabilities compose, they don't
    interfere with each other."""
    ledger = Ledger()
    bank_a = Bank(ledger, "bank_a", max_leverage=50.0)
    gov = Government(ledger, "gov")
    bank_a.capitalize(usd(1000))
    rule = PolicyRateRule(neutral_rate=0.03, mean_reversion_speed=0.5, dt=1 / 12)
    unified = CentralBankLedger(ledger, "cb_unified", rate_rule=rule, initial_rate=0.03)
    unified.register_bank(bank_a)

    unified.step_rate([])
    gov.issue_bonds(bank_a, usd(500))
    unified.purchase_government_bonds(bank_a, usd(300))

    assert unified.settlement_balance_of(bank_a) == usd(300)
    ledger.check_identities("USD")
