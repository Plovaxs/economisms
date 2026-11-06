import random

import pytest

from prometheus.core.money import Money
from prometheus.econosim.economy import Economy
from prometheus.econosim.insolvency import (
    ClaimPriority,
    CreditorClaim,
    allocate_recovery,
    resolve_insolvency,
)


def _economy_with_two_capitalized_banks(capital: int = 100_000_00) -> Economy:
    econ = Economy()
    econ.add_bank("bank-a", max_leverage=10.0).capitalize(Money(capital, "USD"))
    econ.add_bank("bank-b", max_leverage=10.0).capitalize(Money(capital, "USD"))
    return econ


# -- allocate_recovery: pure allocation math -------------------------------


def test_allocate_recovery_pays_single_tier_in_full_when_recovery_covers_it() -> None:
    econ = _economy_with_two_capitalized_banks()
    claims = [
        CreditorClaim(econ.banks["bank-a"], Money(600_00, "USD"), ClaimPriority.SENIOR_UNSECURED),
        CreditorClaim(econ.banks["bank-b"], Money(400_00, "USD"), ClaimPriority.SENIOR_UNSECURED),
    ]
    allocation = allocate_recovery(claims, Money(1_000_00, "USD"))
    assert allocation == [Money(600_00, "USD"), Money(400_00, "USD")]


def test_allocate_recovery_splits_single_tier_pro_rata_when_recovery_is_short() -> None:
    econ = _economy_with_two_capitalized_banks()
    claims = [
        CreditorClaim(econ.banks["bank-a"], Money(600_00, "USD"), ClaimPriority.SENIOR_UNSECURED),
        CreditorClaim(econ.banks["bank-b"], Money(400_00, "USD"), ClaimPriority.SENIOR_UNSECURED),
    ]
    allocation = allocate_recovery(claims, Money(250_00, "USD"))
    # exact pro rata: 250.00 * 600/1000 = 150.00, 250.00 * 400/1000 = 100.00
    assert allocation == [Money(150_00, "USD"), Money(100_00, "USD")]
    assert sum(allocation, Money.zero("USD")) == Money(250_00, "USD")


def test_allocate_recovery_respects_absolute_priority_across_tiers() -> None:
    """A secured claim must be paid in full before the unsecured claim
    receives anything -- recovery here is too small to reach the
    unsecured tier at all."""
    econ = _economy_with_two_capitalized_banks()
    claims = [
        CreditorClaim(econ.banks["bank-a"], Money(300_00, "USD"), ClaimPriority.SECURED),
        CreditorClaim(
            econ.banks["bank-b"], Money(700_00, "USD"), ClaimPriority.SENIOR_UNSECURED
        ),
    ]
    allocation = allocate_recovery(claims, Money(200_00, "USD"))
    assert allocation == [Money(200_00, "USD"), Money.zero("USD")]


def test_allocate_recovery_pays_senior_tier_in_full_then_splits_remainder_to_junior_tier() -> None:
    econ = _economy_with_two_capitalized_banks()
    claims = [
        CreditorClaim(econ.banks["bank-a"], Money(300_00, "USD"), ClaimPriority.SECURED),
        CreditorClaim(
            econ.banks["bank-b"], Money(700_00, "USD"), ClaimPriority.SENIOR_UNSECURED
        ),
    ]
    allocation = allocate_recovery(claims, Money(400_00, "USD"))
    # secured gets its full 300.00; the remaining 100.00 goes entirely to
    # the single junior claim (nothing to split pro rata against)
    assert allocation == [Money(300_00, "USD"), Money(100_00, "USD")]


def test_allocate_recovery_apportionment_is_exact_and_within_one_unit_of_ideal_share() -> None:
    """Largest-remainder apportionment must never lose/invent minor units,
    and must never deviate from each claim's exact real-valued share by
    a full minor unit or more -- checked against 500 random claim sets."""
    rng = random.Random(1234)
    for _ in range(500):
        n = rng.randint(1, 6)
        amounts = [rng.randint(1, 10_000) for _ in range(n)]
        total = sum(amounts)
        target = rng.randint(0, total)
        econ = _economy_with_two_capitalized_banks()
        bank = econ.banks["bank-a"]
        claims = [
            CreditorClaim(bank, Money(a, "USD"), ClaimPriority.SENIOR_UNSECURED) for a in amounts
        ]
        allocation = allocate_recovery(claims, Money(target, "USD"))
        shares = [m.minor_units for m in allocation]
        assert sum(shares) == target
        for amount, share in zip(amounts, shares, strict=True):
            ideal = amount * target / total
            assert abs(share - ideal) < 1.0 + 1e-9
            assert 0 <= share <= amount


def test_allocate_recovery_rejects_recovery_exceeding_total_claims() -> None:
    econ = _economy_with_two_capitalized_banks()
    claims = [
        CreditorClaim(econ.banks["bank-a"], Money(100_00, "USD"), ClaimPriority.SENIOR_UNSECURED)
    ]
    with pytest.raises(ValueError):
        allocate_recovery(claims, Money(200_00, "USD"))


def test_allocate_recovery_rejects_empty_claims() -> None:
    with pytest.raises(ValueError):
        allocate_recovery([], Money(100_00, "USD"))


def test_allocate_recovery_rejects_non_positive_claim_amount() -> None:
    econ = _economy_with_two_capitalized_banks()
    claims = [
        CreditorClaim(econ.banks["bank-a"], Money(0, "USD"), ClaimPriority.SENIOR_UNSECURED)
    ]
    with pytest.raises(ValueError):
        allocate_recovery(claims, Money(0, "USD"))


def test_allocate_recovery_rejects_mismatched_claim_currencies() -> None:
    econ = _economy_with_two_capitalized_banks()
    claims = [
        CreditorClaim(econ.banks["bank-a"], Money(100_00, "USD"), ClaimPriority.SENIOR_UNSECURED),
        CreditorClaim(econ.banks["bank-b"], Money(100_00, "EUR"), ClaimPriority.SENIOR_UNSECURED),
    ]
    with pytest.raises(ValueError):
        allocate_recovery(claims, Money(100_00, "USD"))


def test_allocate_recovery_rejects_recovery_in_a_different_currency_than_the_claims() -> None:
    econ = _economy_with_two_capitalized_banks()
    claims = [
        CreditorClaim(econ.banks["bank-a"], Money(100_00, "USD"), ClaimPriority.SENIOR_UNSECURED)
    ]
    with pytest.raises(ValueError):
        allocate_recovery(claims, Money(50_00, "EUR"))


def test_allocate_recovery_rejects_negative_recovery() -> None:
    econ = _economy_with_two_capitalized_banks()
    claims = [
        CreditorClaim(econ.banks["bank-a"], Money(100_00, "USD"), ClaimPriority.SENIOR_UNSECURED)
    ]
    with pytest.raises(ValueError):
        allocate_recovery(claims, Money(-1, "USD"))


# -- resolve_insolvency: ledger-level end-to-end ---------------------------


def test_resolve_insolvency_end_to_end_two_creditors_same_tier_pro_rata() -> None:
    econ = _economy_with_two_capitalized_banks()
    bank_a, bank_b = econ.banks["bank-a"], econ.banks["bank-b"]
    hh = econ.add_household("hh-1")
    bank_a.originate_loan(hh, Money(600_00, "USD"))
    bank_b.originate_loan(hh, Money(400_00, "USD"))
    firm = econ.add_firm("firm-1")
    hh.consume(firm, Money(750_00, "USD"))  # leaves exactly 250.00 cash
    assert hh.cash_balance == Money(250_00, "USD")

    claims = [
        CreditorClaim(bank_a, Money(600_00, "USD"), ClaimPriority.SENIOR_UNSECURED),
        CreditorClaim(bank_b, Money(400_00, "USD"), ClaimPriority.SENIOR_UNSECURED),
    ]
    result = resolve_insolvency(hh, claims, Money(250_00, "USD"))

    assert result.borrower_id == "hh-1"
    paid_a, paid_b = (s.paid for s in result.settlements)
    assert paid_a == Money(150_00, "USD")
    assert paid_b == Money(100_00, "USD")
    assert result.settlements[0].written_off == Money(450_00, "USD")
    assert result.settlements[1].written_off == Money(300_00, "USD")

    assert hh.debt_balance == Money.zero("USD")
    assert hh.cash_balance == Money.zero("USD")
    assert bank_a.loans_outstanding == Money.zero("USD")
    assert bank_b.loans_outstanding == Money.zero("USD")
    # realized losses: bank_a lost 450.00, bank_b lost 300.00
    assert bank_a.capital == Money(100_000_00 - 450_00, "USD")
    assert bank_b.capital == Money(100_000_00 - 300_00, "USD")
    econ.check_integrity()


def test_resolve_insolvency_end_to_end_respects_priority_across_tiers() -> None:
    econ = _economy_with_two_capitalized_banks()
    secured_bank, unsecured_bank = econ.banks["bank-a"], econ.banks["bank-b"]
    hh = econ.add_household("hh-1")
    secured_bank.originate_loan(hh, Money(300_00, "USD"))
    unsecured_bank.originate_loan(hh, Money(700_00, "USD"))
    firm = econ.add_firm("firm-1")
    hh.consume(firm, Money(600_00, "USD"))  # leaves exactly 400.00 cash
    assert hh.cash_balance == Money(400_00, "USD")

    claims = [
        CreditorClaim(secured_bank, Money(300_00, "USD"), ClaimPriority.SECURED),
        CreditorClaim(unsecured_bank, Money(700_00, "USD"), ClaimPriority.SENIOR_UNSECURED),
    ]
    result = resolve_insolvency(hh, claims, Money(400_00, "USD"))

    secured_settlement, unsecured_settlement = result.settlements
    assert secured_settlement.paid == Money(300_00, "USD")
    assert secured_settlement.written_off == Money.zero("USD")
    assert unsecured_settlement.paid == Money(100_00, "USD")
    assert unsecured_settlement.written_off == Money(600_00, "USD")

    assert secured_bank.capital == Money(100_000_00, "USD")  # made whole, no loss
    assert unsecured_bank.capital == Money(100_000_00 - 600_00, "USD")
    econ.check_integrity()


def test_resolve_insolvency_full_recovery_writes_off_nothing() -> None:
    econ = _economy_with_two_capitalized_banks()
    bank_a, bank_b = econ.banks["bank-a"], econ.banks["bank-b"]
    hh = econ.add_household("hh-1")
    bank_a.originate_loan(hh, Money(600_00, "USD"))
    bank_b.originate_loan(hh, Money(400_00, "USD"))
    assert hh.cash_balance == Money(1_000_00, "USD")

    claims = [
        CreditorClaim(bank_a, Money(600_00, "USD"), ClaimPriority.SENIOR_UNSECURED),
        CreditorClaim(bank_b, Money(400_00, "USD"), ClaimPriority.SENIOR_UNSECURED),
    ]
    result = resolve_insolvency(hh, claims, Money(1_000_00, "USD"))

    assert all(s.written_off.is_zero() for s in result.settlements)
    assert bank_a.capital == Money(100_000_00, "USD")
    assert bank_b.capital == Money(100_000_00, "USD")
    econ.check_integrity()


def test_resolve_insolvency_zero_recovery_writes_off_everything_and_skips_repayment() -> None:
    econ = _economy_with_two_capitalized_banks()
    bank_a, bank_b = econ.banks["bank-a"], econ.banks["bank-b"]
    hh = econ.add_household("hh-1")
    bank_a.originate_loan(hh, Money(600_00, "USD"))
    bank_b.originate_loan(hh, Money(400_00, "USD"))
    firm = econ.add_firm("firm-1")
    hh.consume(firm, Money(1_000_00, "USD"))  # household is flat broke
    assert hh.cash_balance == Money.zero("USD")

    claims = [
        CreditorClaim(bank_a, Money(600_00, "USD"), ClaimPriority.SENIOR_UNSECURED),
        CreditorClaim(bank_b, Money(400_00, "USD"), ClaimPriority.SENIOR_UNSECURED),
    ]
    result = resolve_insolvency(hh, claims, Money.zero("USD"))

    assert all(s.paid.is_zero() for s in result.settlements)
    assert result.settlements[0].written_off == Money(600_00, "USD")
    assert result.settlements[1].written_off == Money(400_00, "USD")
    assert len(result.transactions) == 2  # one write-off each, no repayment postings
    econ.check_integrity()


def test_resolve_insolvency_rejects_empty_claims() -> None:
    econ = _economy_with_two_capitalized_banks()
    hh = econ.add_household("hh-1")
    with pytest.raises(ValueError):
        resolve_insolvency(hh, [], Money.zero("USD"))


def test_resolve_insolvency_rejects_claims_not_matching_borrowers_recorded_debt() -> None:
    econ = _economy_with_two_capitalized_banks()
    bank_a, bank_b = econ.banks["bank-a"], econ.banks["bank-b"]
    hh = econ.add_household("hh-1")
    bank_a.originate_loan(hh, Money(600_00, "USD"))
    bank_b.originate_loan(hh, Money(400_00, "USD"))

    claims = [
        # understates bank_a's actual claim
        CreditorClaim(bank_a, Money(500_00, "USD"), ClaimPriority.SENIOR_UNSECURED),
        CreditorClaim(bank_b, Money(400_00, "USD"), ClaimPriority.SENIOR_UNSECURED),
    ]
    with pytest.raises(ValueError):
        resolve_insolvency(hh, claims, Money(250_00, "USD"))
    # nothing posted: debt and cash both unchanged
    assert hh.debt_balance == Money(1_000_00, "USD")
    assert hh.cash_balance == Money(1_000_00, "USD")


def test_resolve_insolvency_rejects_recovery_exceeding_borrowers_cash() -> None:
    econ = _economy_with_two_capitalized_banks()
    bank_a, bank_b = econ.banks["bank-a"], econ.banks["bank-b"]
    hh = econ.add_household("hh-1")
    bank_a.originate_loan(hh, Money(600_00, "USD"))
    bank_b.originate_loan(hh, Money(400_00, "USD"))
    firm = econ.add_firm("firm-1")
    hh.consume(firm, Money(900_00, "USD"))  # only 100.00 cash left
    assert hh.cash_balance == Money(100_00, "USD")

    claims = [
        CreditorClaim(bank_a, Money(600_00, "USD"), ClaimPriority.SENIOR_UNSECURED),
        CreditorClaim(bank_b, Money(400_00, "USD"), ClaimPriority.SENIOR_UNSECURED),
    ]
    with pytest.raises(ValueError):
        resolve_insolvency(hh, claims, Money(200_00, "USD"))  # more cash than hh has
    assert hh.debt_balance == Money(1_000_00, "USD")
    assert hh.cash_balance == Money(100_00, "USD")


def test_government_borrower_can_be_resolved_through_insolvency_too() -> None:
    """resolve_insolvency is written against the Borrower protocol, like
    every other agents.py method -- Government goes through the identical
    code path as Household, not a separate mechanism."""
    econ = _economy_with_two_capitalized_banks()
    bank_a, bank_b = econ.banks["bank-a"], econ.banks["bank-b"]
    gov = econ.add_government("gov-1")
    bank_a.originate_loan(gov, Money(300_00, "USD"))
    bank_b.originate_loan(gov, Money(700_00, "USD"))
    gov.pay_transfer(econ.add_household("hh-1"), Money(900_00, "USD"))  # leaves 100.00
    assert gov.cash_balance == Money(100_00, "USD")

    claims = [
        CreditorClaim(bank_a, Money(300_00, "USD"), ClaimPriority.SENIOR_UNSECURED),
        CreditorClaim(bank_b, Money(700_00, "USD"), ClaimPriority.SENIOR_UNSECURED),
    ]
    result = resolve_insolvency(gov, claims, Money(100_00, "USD"))

    assert result.borrower_id == "gov-1"
    assert gov.debt_balance == Money.zero("USD")
    econ.check_integrity()


def test_claims_written_off_reconcile_exactly_with_aggregate_equity_loss() -> None:
    """ECO-10 ("implement defaults and orderly loss allocation; claims
    and equity loss reconciliation passes toy cases"), checked as its
    own explicit, deliberate identity rather than inferred from the
    scattered per-bank capital assertions in the tests above: summed
    across every creditor (3 banks, SECURED/SENIOR_UNSECURED/
    SUBORDINATED tiers, a partial recovery), the TOTAL amount written
    off must equal EXACTLY the TOTAL equity (capital) lost by those
    creditors -- no claim is extinguished without a matching,
    equal-sized loss recognized somewhere, and vice versa."""
    econ = Economy()
    secured = econ.add_bank("secured-bank", max_leverage=10.0)
    senior = econ.add_bank("senior-bank", max_leverage=10.0)
    subordinated = econ.add_bank("subordinated-bank", max_leverage=10.0)
    for bank in (secured, senior, subordinated):
        bank.capitalize(Money(100_000_00, "USD"))

    hh = econ.add_household("hh-1")
    secured.originate_loan(hh, Money(200_00, "USD"))
    senior.originate_loan(hh, Money(500_00, "USD"))
    subordinated.originate_loan(hh, Money(300_00, "USD"))
    firm = econ.add_firm("firm-1")
    hh.consume(firm, Money(650_00, "USD"))  # leaves exactly 350.00 cash
    assert hh.cash_balance == Money(350_00, "USD")

    capital_before = {
        bank.agent_id: bank.capital for bank in (secured, senior, subordinated)
    }
    claims = [
        CreditorClaim(secured, Money(200_00, "USD"), ClaimPriority.SECURED),
        CreditorClaim(senior, Money(500_00, "USD"), ClaimPriority.SENIOR_UNSECURED),
        CreditorClaim(subordinated, Money(300_00, "USD"), ClaimPriority.SUBORDINATED),
    ]
    result = resolve_insolvency(hh, claims, Money(350_00, "USD"))

    total_written_off = sum(
        (s.written_off for s in result.settlements), start=Money.zero("USD")
    )
    total_equity_lost = sum(
        (
            capital_before[bank.agent_id] - bank.capital
            for bank in (secured, senior, subordinated)
        ),
        start=Money.zero("USD"),
    )
    assert total_written_off == total_equity_lost
    assert total_written_off == Money(1000_00 - 350_00, "USD")  # total claims - recovery
    econ.check_integrity()
