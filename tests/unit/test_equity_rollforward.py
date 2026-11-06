import pytest

from prometheus.core.money import Money
from prometheus.econosim.economy import Economy
from prometheus.econosim.equity_rollforward import reconcile_equity_rollforward


def test_equity_rollforward_reconciles_across_all_four_agent_sectors() -> None:
    """LED-04's literal "across all agent sectors": one shared economy
    with a sequence of transactions touching Household, Firm, Bank and
    Government equity accounts, each independently reconciled against
    the SAME journal."""
    econ = Economy()
    hh = econ.add_household("hh-1")
    firm = econ.add_firm("firm-1")
    bank = econ.add_bank("bank-1", max_leverage=10.0)
    gov = econ.add_government("gov-1")

    bank.capitalize(Money(1_000_000_00, "USD"))
    hh.receive_income(Money(500_00, "USD"))
    hh.consume(firm, Money(200_00, "USD"))
    firm.pay_wages(hh, Money(50_00, "USD"))
    bank.originate_loan(hh, Money(300_00, "USD"))
    hh.repay_loan(bank, Money(100_00, "USD"))
    gov.collect_tax(hh, Money(30_00, "USD"))
    gov.pay_transfer(hh, Money(10_00, "USD"))
    bank.accrue_interest(hh, annual_rate=0.1, dt=1.0)

    journal = econ.ledger.journal
    for agent, account_id in (
        (hh, hh.equity_account),
        (firm, firm.equity_account),
        (bank, bank.equity_account),
        (gov, gov.equity_account),
    ):
        result = reconcile_equity_rollforward(
            account_id=account_id,
            opening_equity=Money.zero("USD"),
            transactions=journal,
            closing_equity=agent.net_worth if agent is not bank else bank.capital,
        )
        assert result.reconciles, f"{account_id} rollforward did not reconcile: {result}"

    econ.check_integrity()


def test_equity_rollforward_detects_a_tampered_closing_balance() -> None:
    """The reconciliation must actually discriminate a wrong closing
    balance from a correct one, not just return True on the happy
    path."""
    econ = Economy()
    hh = econ.add_household("hh-1")
    firm = econ.add_firm("firm-1")
    hh.receive_income(Money(1000_00, "USD"))
    hh.consume(firm, Money(300_00, "USD"))

    journal = econ.ledger.journal
    wrong_closing = Money(hh.net_worth.minor_units + 1, "USD")
    result = reconcile_equity_rollforward(
        account_id=hh.equity_account,
        opening_equity=Money.zero("USD"),
        transactions=journal,
        closing_equity=wrong_closing,
    )
    assert not result.reconciles
    assert result.recomputed_closing_equity == hh.net_worth


def test_equity_rollforward_reports_total_increases_and_decreases_separately() -> None:
    econ = Economy()
    hh = econ.add_household("hh-1")
    firm = econ.add_firm("firm-1")
    hh.receive_income(Money(1000_00, "USD"))
    hh.consume(firm, Money(300_00, "USD"))

    journal = econ.ledger.journal
    result = reconcile_equity_rollforward(
        account_id=hh.equity_account,
        opening_equity=Money.zero("USD"),
        transactions=journal,
        closing_equity=hh.net_worth,
    )
    assert result.total_increases == Money(1000_00, "USD")
    assert result.total_decreases == Money(300_00, "USD")
    assert result.closing_equity == Money(700_00, "USD")


def test_equity_rollforward_supports_a_mid_simulation_opening_balance() -> None:
    """A rollforward need not start from zero -- the caller may capture
    an opening balance partway through a simulation and reconcile only
    the transactions since then."""
    econ = Economy()
    hh = econ.add_household("hh-1")
    firm = econ.add_firm("firm-1")
    hh.receive_income(Money(1000_00, "USD"))

    opening = hh.net_worth
    opening_journal_length = len(econ.ledger.journal)
    hh.consume(firm, Money(150_00, "USD"))
    period_transactions = econ.ledger.journal[opening_journal_length:]

    result = reconcile_equity_rollforward(
        account_id=hh.equity_account,
        opening_equity=opening,
        transactions=period_transactions,
        closing_equity=hh.net_worth,
    )
    assert result.reconciles
    assert result.total_decreases == Money(150_00, "USD")


def test_equity_rollforward_rejects_a_currency_mismatch() -> None:
    econ = Economy()
    hh = econ.add_household("hh-1")
    firm = econ.add_firm("firm-1")
    hh.receive_income(Money(1000_00, "USD"))
    hh.consume(firm, Money(300_00, "USD"))

    journal = econ.ledger.journal
    with pytest.raises(ValueError, match="currency"):
        reconcile_equity_rollforward(
            account_id=hh.equity_account,
            opening_equity=Money.zero("EUR"),
            transactions=journal,
            closing_equity=hh.net_worth,
        )
