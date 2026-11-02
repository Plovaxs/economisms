from dataclasses import FrozenInstanceError

import pytest

from prometheus.core.ledger import (
    AccountType,
    DuplicateAccountError,
    EmptyTransactionError,
    Ledger,
    LedgerIdentityViolation,
    LedgerImbalanceError,
    Posting,
    Sector,
    SectorImbalanceError,
    Side,
    UnknownAccountError,
)
from prometheus.core.money import Money


def _simple_ledger() -> tuple[Ledger, str, str]:
    """Two asset accounts in the same sector -- enough to post a trivially
    balanced, single-sector transfer transaction."""
    ledger = Ledger()
    ledger.open_account("firm-a:deposit", Sector.FIRM, AccountType.ASSET)
    ledger.open_account("firm-b:deposit", Sector.FIRM, AccountType.ASSET)
    return ledger, "firm-a:deposit", "firm-b:deposit"


def test_open_account_rejects_duplicates() -> None:
    ledger, *_ = _simple_ledger()
    with pytest.raises(DuplicateAccountError):
        ledger.open_account("firm-a:deposit", Sector.FIRM, AccountType.ASSET)


def test_unknown_account_lookup_raises() -> None:
    ledger, *_ = _simple_ledger()
    with pytest.raises(UnknownAccountError):
        ledger.account("does-not-exist")


def test_balanced_transfer_updates_both_balances() -> None:
    ledger, a, b = _simple_ledger()
    ledger.post(
        [
            Posting(a, Side.CREDIT, Money(500, "USD")),
            Posting(b, Side.DEBIT, Money(500, "USD")),
        ],
        description="transfer",
    )
    assert ledger.account(a).balance == Money(-500, "USD")
    assert ledger.account(b).balance == Money(500, "USD")
    assert len(ledger.journal) == 1


def test_empty_transaction_rejected() -> None:
    ledger, *_ = _simple_ledger()
    with pytest.raises(EmptyTransactionError):
        ledger.post([], description="nothing")


def test_unknown_account_in_posting_rejected_before_mutation() -> None:
    ledger, a, _ = _simple_ledger()
    with pytest.raises(UnknownAccountError):
        ledger.post(
            [
                Posting(a, Side.CREDIT, Money(100, "USD")),
                Posting("ghost:account", Side.DEBIT, Money(100, "USD")),
            ],
            description="bad",
        )
    # fail closed: no partial mutation from the rejected transaction
    assert ledger.account(a).balance == Money(0, "USD")
    assert len(ledger.journal) == 0


def test_globally_imbalanced_transaction_rejected() -> None:
    ledger, a, b = _simple_ledger()
    with pytest.raises(LedgerImbalanceError):
        ledger.post(
            [
                Posting(a, Side.CREDIT, Money(500, "USD")),
                Posting(b, Side.DEBIT, Money(400, "USD")),
            ],
            description="imbalanced",
        )
    assert ledger.account(a).balance == Money(0, "USD")
    assert ledger.account(b).balance == Money(0, "USD")
    assert len(ledger.journal) == 0


def test_negative_or_zero_posting_amount_rejected() -> None:
    with pytest.raises(ValueError):
        Posting("x", Side.DEBIT, Money(0, "USD"))
    with pytest.raises(ValueError):
        Posting("x", Side.DEBIT, Money(-10, "USD"))


def test_cross_sector_transaction_with_missing_counterpart_rejected() -> None:
    """A transaction that is globally balanced (total debits == total
    credits across the whole transaction) but where one sector's own subset
    of postings does not net to zero must still be rejected -- this is
    exactly the bug a naive "global balance only" check would miss: here the
    loan's household-side counterpart was sent to the wrong sector entirely
    (a firm's equity account) instead of a household liability account, yet
    the transaction still balances overall (2000 debits == 2000 credits)."""
    ledger = Ledger()
    ledger.open_account("bank-a:loans", Sector.BANK, AccountType.ASSET)
    ledger.open_account("bank-a:deposits", Sector.BANK, AccountType.LIABILITY)
    ledger.open_account("hh-a:deposit", Sector.HOUSEHOLD, AccountType.ASSET)
    ledger.open_account("firm-a:equity", Sector.FIRM, AccountType.EQUITY)

    with pytest.raises(SectorImbalanceError) as excinfo:
        ledger.post(
            [
                Posting("bank-a:loans", Side.DEBIT, Money(1000, "USD")),
                Posting("bank-a:deposits", Side.CREDIT, Money(1000, "USD")),
                Posting("hh-a:deposit", Side.DEBIT, Money(1000, "USD")),
                Posting("firm-a:equity", Side.CREDIT, Money(1000, "USD")),  # bug: wrong sector
            ],
            description="broken loan origination",
        )
    assert excinfo.value.sector is Sector.HOUSEHOLD
    # fail closed: nothing was mutated, not even the (individually fine) bank side
    assert ledger.account("bank-a:loans").balance == Money(0, "USD")
    assert ledger.account("hh-a:deposit").balance == Money(0, "USD")
    assert len(ledger.journal) == 0


def test_check_identities_passes_for_well_formed_history() -> None:
    ledger = Ledger()
    ledger.open_account("bank-a:deposits", Sector.BANK, AccountType.LIABILITY)
    ledger.open_account("bank-a:loans", Sector.BANK, AccountType.ASSET)
    ledger.open_account("hh-a:deposit", Sector.HOUSEHOLD, AccountType.ASSET)
    ledger.open_account("hh-a:loan_payable", Sector.HOUSEHOLD, AccountType.LIABILITY)
    ledger.post(
        [
            Posting("bank-a:loans", Side.DEBIT, Money(1000, "USD")),
            Posting("bank-a:deposits", Side.CREDIT, Money(1000, "USD")),
            Posting("hh-a:deposit", Side.DEBIT, Money(1000, "USD")),
            Posting("hh-a:loan_payable", Side.CREDIT, Money(1000, "USD")),
        ],
        description="loan origination",
    )
    ledger.check_identities()  # must not raise


def test_check_identities_detects_bypassed_mutation() -> None:
    """ECO-16: fail-closed detection. Ledger.post() can never produce a
    broken identity, so to exercise the detector we reach past the public
    API and corrupt a balance directly, the way a bug or a corrupted replay
    might."""
    ledger = Ledger()
    ledger.open_account("hh-a:deposit", Sector.HOUSEHOLD, AccountType.ASSET)
    ledger.open_account("hh-a:equity", Sector.HOUSEHOLD, AccountType.EQUITY)
    ledger.post(
        [
            Posting("hh-a:deposit", Side.DEBIT, Money(100, "USD")),
            Posting("hh-a:equity", Side.CREDIT, Money(100, "USD")),
        ],
        description="seed",
    )
    ledger.check_identities()  # sane before corruption

    ledger.account("hh-a:deposit")._apply(Side.DEBIT, Money(1, "USD"))  # simulate corruption
    with pytest.raises(LedgerIdentityViolation):
        ledger.check_identities()


def test_balance_sheet_residual_zero_after_transactions() -> None:
    ledger, a, b = _simple_ledger()
    ledger.post(
        [
            Posting(a, Side.CREDIT, Money(500, "USD")),
            Posting(b, Side.DEBIT, Money(500, "USD")),
        ],
        description="transfer",
    )
    sheet = ledger.balance_sheet(Sector.FIRM)
    assert sheet["residual"] == Money(0, "USD")


def test_state_hash_is_deterministic_for_identical_histories() -> None:
    def build() -> Ledger:
        ledger, a, b = _simple_ledger()
        ledger.post(
            [
                Posting(a, Side.CREDIT, Money(500, "USD")),
                Posting(b, Side.DEBIT, Money(500, "USD")),
            ],
            description="transfer",
            step=1,
        )
        return ledger

    hash_1 = build().snapshot(step=1).state_hash()
    hash_2 = build().snapshot(step=1).state_hash()
    assert hash_1 == hash_2


def test_state_hash_differs_for_different_histories() -> None:
    ledger_a, a, b = _simple_ledger()
    ledger_a.post(
        [Posting(a, Side.CREDIT, Money(500, "USD")), Posting(b, Side.DEBIT, Money(500, "USD"))],
        description="transfer",
        step=1,
    )
    ledger_b, a2, b2 = _simple_ledger()
    ledger_b.post(
        [Posting(a2, Side.CREDIT, Money(600, "USD")), Posting(b2, Side.DEBIT, Money(600, "USD"))],
        description="transfer",
        step=1,
    )
    assert ledger_a.snapshot(1).state_hash() != ledger_b.snapshot(1).state_hash()


def test_journal_is_append_only_and_postings_immutable() -> None:
    ledger, a, b = _simple_ledger()
    txn = ledger.post(
        [Posting(a, Side.CREDIT, Money(500, "USD")), Posting(b, Side.DEBIT, Money(500, "USD"))],
        description="transfer",
    )
    with pytest.raises(FrozenInstanceError):
        txn.description = "tampered"  # type: ignore[misc]
    with pytest.raises(AttributeError):
        ledger.journal.append(txn)  # type: ignore[attr-defined]
