import pytest

from prometheus.core.ledger import Ledger
from prometheus.core.money import Money
from prometheus.econosim.agents import Bank, CreditLimitExceededError, InsufficientFundsError
from prometheus.econosim.interbank_market import InterbankMarket


def usd(major_units: float) -> Money:
    return Money(int(round(major_units * 100)), "USD")


@pytest.fixture
def setup() -> tuple[Ledger, Bank, Bank, InterbankMarket]:
    ledger = Ledger()
    bank_a = Bank(ledger, "bank_a", max_leverage=10.0)
    bank_b = Bank(ledger, "bank_b", max_leverage=10.0)
    bank_a.capitalize(usd(1000))
    bank_b.capitalize(usd(1000))
    market = InterbankMarket(ledger)
    return ledger, bank_a, bank_b, market


def test_exposure_is_zero_before_any_loan(
    setup: tuple[Ledger, Bank, Bank, InterbankMarket],
) -> None:
    _, bank_a, bank_b, market = setup
    assert market.exposure(bank_a, bank_b) == Money.zero("USD")
    assert market.total_interbank_exposure(bank_a) == Money.zero("USD")


def test_lend_moves_reserves_and_creates_a_matching_exposure(
    setup: tuple[Ledger, Bank, Bank, InterbankMarket],
) -> None:
    ledger, bank_a, bank_b, market = setup
    market.lend(bank_a, bank_b, usd(300))

    assert market.exposure(bank_a, bank_b) == usd(300)
    assert ledger.account(bank_a.reserves_account).balance == usd(700)
    assert ledger.account(bank_b.reserves_account).balance == usd(1300)
    ledger.check_identities("USD")


def test_a_second_loan_between_the_same_pair_accumulates_on_the_same_link(
    setup: tuple[Ledger, Bank, Bank, InterbankMarket],
) -> None:
    """The second `lend` call between an already-linked pair must reuse
    the existing accounts (accumulating exposure), not open a second,
    separate pair of accounts."""
    _, bank_a, bank_b, market = setup
    market.lend(bank_a, bank_b, usd(100))
    market.lend(bank_a, bank_b, usd(50))
    assert market.exposure(bank_a, bank_b) == usd(150)


def test_repay_is_the_exact_reverse_of_lend(
    setup: tuple[Ledger, Bank, Bank, InterbankMarket],
) -> None:
    ledger, bank_a, bank_b, market = setup
    market.lend(bank_a, bank_b, usd(300))
    market.repay(bank_a, bank_b, usd(300))

    assert market.exposure(bank_a, bank_b) == Money.zero("USD")
    assert ledger.account(bank_a.reserves_account).balance == usd(1000)
    assert ledger.account(bank_b.reserves_account).balance == usd(1000)
    ledger.check_identities("USD")


def test_partial_repayment_reduces_exposure_by_exactly_the_amount_paid(
    setup: tuple[Ledger, Bank, Bank, InterbankMarket],
) -> None:
    _, bank_a, bank_b, market = setup
    market.lend(bank_a, bank_b, usd(300))
    market.repay(bank_a, bank_b, usd(100))
    assert market.exposure(bank_a, bank_b) == usd(200)


def test_total_interbank_exposure_sums_across_every_counterparty(
    setup: tuple[Ledger, Bank, Bank, InterbankMarket],
) -> None:
    ledger, bank_a, bank_b, market = setup
    bank_c = Bank(ledger, "bank_c", max_leverage=10.0)
    bank_c.capitalize(usd(1000))
    market.lend(bank_a, bank_b, usd(300))
    market.lend(bank_a, bank_c, usd(200))
    assert market.total_interbank_exposure(bank_a) == usd(500)
    assert market.total_interbank_exposure(bank_b) == Money.zero("USD")


def test_lend_rejects_self_loan(setup: tuple[Ledger, Bank, Bank, InterbankMarket]) -> None:
    _, bank_a, _, market = setup
    with pytest.raises(ValueError):
        market.lend(bank_a, bank_a, usd(10))


def test_lend_rejects_non_positive_principal(
    setup: tuple[Ledger, Bank, Bank, InterbankMarket],
) -> None:
    _, bank_a, bank_b, market = setup
    with pytest.raises(ValueError):
        market.lend(bank_a, bank_b, usd(0))


def test_lend_rejects_amount_exceeding_lender_reserves(
    setup: tuple[Ledger, Bank, Bank, InterbankMarket],
) -> None:
    _, bank_a, bank_b, market = setup
    with pytest.raises(InsufficientFundsError):
        market.lend(bank_a, bank_b, usd(2000))


def test_lend_rejects_amount_exceeding_lender_leverage_cap(
    setup: tuple[Ledger, Bank, Bank, InterbankMarket],
) -> None:
    """bank_a's capital stays at 1000 (max_leverage 10 -> capacity 10000)
    even after it borrows $50,000 of liquidity from a third bank -- a loan
    received boosts reserves, not capital. Lending $11,000 of that onward
    exceeds bank_a's OWN capital-based cap well before its (now ample)
    reserves would ever bind."""
    ledger, bank_a, bank_b, market = setup
    bank_c = Bank(ledger, "bank_c", max_leverage=10.0)
    bank_c.capitalize(usd(100_000))
    market.lend(bank_c, bank_a, usd(50_000))

    with pytest.raises(CreditLimitExceededError):
        market.lend(bank_a, bank_b, usd(11_000))


def test_repay_rejects_non_positive_amount(
    setup: tuple[Ledger, Bank, Bank, InterbankMarket],
) -> None:
    _, bank_a, bank_b, market = setup
    market.lend(bank_a, bank_b, usd(100))
    with pytest.raises(ValueError):
        market.repay(bank_a, bank_b, usd(0))


def test_repay_rejects_amount_exceeding_outstanding_exposure(
    setup: tuple[Ledger, Bank, Bank, InterbankMarket],
) -> None:
    _, bank_a, bank_b, market = setup
    market.lend(bank_a, bank_b, usd(100))
    with pytest.raises(ValueError):
        market.repay(bank_a, bank_b, usd(200))


def test_repay_rejects_amount_exceeding_borrower_reserves(
    setup: tuple[Ledger, Bank, Bank, InterbankMarket],
) -> None:
    ledger, bank_a, bank_b, market = setup
    market.lend(bank_a, bank_b, usd(900))
    # bank_b spends its reserves elsewhere (simulated by a second loan out)
    bank_c = Bank(ledger, "bank_c", max_leverage=10.0)
    bank_c.capitalize(usd(10))
    market.lend(bank_b, bank_c, usd(1800))  # drains bank_b's reserves below 900
    with pytest.raises(InsufficientFundsError):
        market.repay(bank_a, bank_b, usd(900))


def test_distinct_pairs_get_distinct_linked_accounts_not_an_aggregate(
    setup: tuple[Ledger, Bank, Bank, InterbankMarket],
) -> None:
    """The defining design choice of this module: borrowing from two
    different lenders must be independently trackable, not netted into
    one aggregate payable balance."""
    ledger, bank_a, bank_b, market = setup
    bank_c = Bank(ledger, "bank_c", max_leverage=10.0)
    bank_c.capitalize(usd(1000))
    market.lend(bank_b, bank_a, usd(300))
    market.lend(bank_c, bank_a, usd(700))

    assert market.exposure(bank_b, bank_a) == usd(300)
    assert market.exposure(bank_c, bank_a) == usd(700)
    # repaying bank_b in full must not affect the separate debt to bank_c
    market.repay(bank_b, bank_a, usd(300))
    assert market.exposure(bank_b, bank_a) == Money.zero("USD")
    assert market.exposure(bank_c, bank_a) == usd(700)
