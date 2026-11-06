"""ECO-11 ("Implement interbank payments and reserve settlement") is
closed by two already-existing, already-separately-tested modules that
had never been tagged against this specific ID: `InterbankMarket`
(direct bilateral interbank PAYMENTS, moving each bank's own vault
`reserves_account`) and `CentralBankLedger.settle_interbank_transfer`
(central-bank-mediated reserve SETTLEMENT, reallocating each bank's
`cb_settlement_balance` sub-account at a shared central bank). Rather
than infer the ECO-11 claim from the two modules' own separate test
suites (`test_interbank_market.py`, `test_central_bank_ledger.py`), this
file states it explicitly, in one place, exercising both halves in a
single scenario -- and, since `central_bank_ledger.py`'s own docstring
explicitly documents the two reserve instruments as "never reconciled
in this model," confirms that claim empirically rather than trusting it
on faith.
"""

from prometheus.core.ledger import Ledger
from prometheus.core.money import Money
from prometheus.econosim.agents import Bank
from prometheus.econosim.central_bank_ledger import CentralBankLedger
from prometheus.econosim.interbank_market import InterbankMarket


def usd(major_units: float) -> Money:
    return Money(int(round(major_units * 100)), "USD")


def test_direct_lending_and_central_bank_settlement_both_cover_eco_11() -> None:
    ledger = Ledger()
    bank_a = Bank(ledger, "bank_a", max_leverage=50.0)
    bank_b = Bank(ledger, "bank_b", max_leverage=50.0)
    bank_a.capitalize(usd(1000))
    bank_b.capitalize(usd(1000))

    # Half 1 -- "interbank payments": a direct bilateral loan moves
    # reserves from bank_a's own vault to bank_b's.
    market = InterbankMarket(ledger)
    market.lend(bank_a, bank_b, usd(200))
    assert market.exposure(bank_a, bank_b) == usd(200)
    assert ledger.account(bank_a.reserves_account).balance == usd(800)
    assert ledger.account(bank_b.reserves_account).balance == usd(1200)

    # Half 2 -- "reserve settlement": a SEPARATE central-bank-mediated
    # reallocation of each bank's own settlement sub-account, issued
    # here via a discount-window loan to bank_a so it has a balance to
    # move.
    cb = CentralBankLedger(ledger, "cb")
    cb.register_bank(bank_a)
    cb.register_bank(bank_b)
    cb.lend_to_bank(bank_a, usd(500))
    cb.settle_interbank_transfer(bank_a, bank_b, usd(150))
    assert cb.settlement_balance_of(bank_a) == usd(350)
    assert cb.settlement_balance_of(bank_b) == usd(150)

    ledger.check_identities("USD")


def test_the_two_reserve_instruments_are_genuinely_unreconciled() -> None:
    """`central_bank_ledger.py`'s own docstring states that a bank's
    central-bank settlement balance and its own vault `reserves_account`
    "are never reconciled in this model" -- a discriminating check of
    that claim, not just a restatement of it: moving money through ONE
    channel must leave the OTHER channel's balance completely
    unaffected."""
    ledger = Ledger()
    bank_a = Bank(ledger, "bank_a", max_leverage=50.0)
    bank_b = Bank(ledger, "bank_b", max_leverage=50.0)
    bank_a.capitalize(usd(1000))
    bank_b.capitalize(usd(1000))
    market = InterbankMarket(ledger)
    cb = CentralBankLedger(ledger, "cb")
    cb.register_bank(bank_a)
    cb.register_bank(bank_b)
    cb.lend_to_bank(bank_a, usd(500))

    vault_reserves_before = (
        ledger.account(bank_a.reserves_account).balance,
        ledger.account(bank_b.reserves_account).balance,
    )
    cb.settle_interbank_transfer(bank_a, bank_b, usd(150))
    assert (
        ledger.account(bank_a.reserves_account).balance,
        ledger.account(bank_b.reserves_account).balance,
    ) == vault_reserves_before

    settlement_balances_before = (
        cb.settlement_balance_of(bank_a),
        cb.settlement_balance_of(bank_b),
    )
    market.lend(bank_a, bank_b, usd(200))
    assert (
        cb.settlement_balance_of(bank_a),
        cb.settlement_balance_of(bank_b),
    ) == settlement_balances_before
