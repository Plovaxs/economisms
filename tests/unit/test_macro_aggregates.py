import pytest

from prometheus.core.money import Money
from prometheus.econosim.economy import Economy
from prometheus.econosim.macro_aggregates import compute_macro_aggregates


def usd(major_units: float) -> Money:
    return Money(int(round(major_units * 100)), "USD")


def test_gdp_income_and_expenditure_reconcile_on_a_clean_period() -> None:
    """ECO-15's own "validated" requirement, exercised against a real
    Economy, not a hand-waved example: a household consumes from a firm,
    the firm pays wages, and a government taxes/transfers on the side.
    Both GDP approaches must agree, AND the ledger-derived firm profit
    must match the caller's own flow-tracked profit -- two genuinely
    separate code paths."""
    econ = Economy()
    hh = econ.add_household("hh-1")
    firm = econ.add_firm("firm-1")
    gov = econ.add_government("gov-1")
    firm.capitalize(usd(10_000))
    hh.receive_income(usd(5_000))

    opening_firm_equity = firm.net_worth
    hh.consume(firm, usd(1_000))
    firm.pay_wages(hh, usd(600))
    gov.collect_tax(hh, usd(50))
    gov.pay_transfer(hh, usd(20))
    closing_firm_equity = firm.net_worth

    result = compute_macro_aggregates(
        consumption_spending=usd(1_000),
        wages_paid=usd(600),
        opening_firm_equity=opening_firm_equity,
        closing_firm_equity=closing_firm_equity,
        credit_outstanding=Money.zero("USD"),
        price_level=1.02,
        prior_price_level=1.00,
    )
    assert result.gdp_reconciles
    assert result.gdp_expenditure == usd(1_000)
    assert result.gdp_income == usd(1_000)
    assert result.firm_profit_from_ledger == usd(400)
    assert result.firm_profit_from_flows == usd(400)


def test_taxes_and_transfers_do_not_affect_gdp() -> None:
    """The discriminating half of the check above, isolated: scaling the
    tax/transfer amounts up or down must leave GDP completely unchanged
    -- transfers are correctly excluded from GDP under this definition,
    not merely assumed to be."""
    econ = Economy()
    hh = econ.add_household("hh-1")
    firm = econ.add_firm("firm-1")
    gov = econ.add_government("gov-1")
    firm.capitalize(usd(10_000))
    hh.receive_income(usd(5_000))

    opening_firm_equity = firm.net_worth
    hh.consume(firm, usd(1_000))
    firm.pay_wages(hh, usd(600))
    gov.collect_tax(hh, usd(999))  # a much larger tax than the clean-period test
    gov.pay_transfer(hh, usd(500))
    closing_firm_equity = firm.net_worth

    result = compute_macro_aggregates(
        consumption_spending=usd(1_000),
        wages_paid=usd(600),
        opening_firm_equity=opening_firm_equity,
        closing_firm_equity=closing_firm_equity,
        credit_outstanding=Money.zero("USD"),
        price_level=1.0,
    )
    assert result.gdp_reconciles
    assert result.gdp_expenditure == usd(1_000)


def test_an_unaccounted_mid_period_capitalization_breaks_reconciliation() -> None:
    """A mid-period `Firm.capitalize` touches firm equity through a
    channel the caller's flow totals don't know about -- this MUST be
    flagged (gdp_reconciles=False), not silently averaged into profit.
    Confirms the check is a genuine discriminator, not a tautology that
    always reports True by construction."""
    econ = Economy()
    hh = econ.add_household("hh-1")
    firm = econ.add_firm("firm-1")
    firm.capitalize(usd(10_000))
    hh.receive_income(usd(5_000))

    opening_firm_equity = firm.net_worth
    hh.consume(firm, usd(1_000))
    firm.capitalize(usd(500))  # the confound: an un-tracked equity injection
    firm.pay_wages(hh, usd(600))
    closing_firm_equity = firm.net_worth

    result = compute_macro_aggregates(
        consumption_spending=usd(1_000),
        wages_paid=usd(600),
        opening_firm_equity=opening_firm_equity,
        closing_firm_equity=closing_firm_equity,
        credit_outstanding=Money.zero("USD"),
        price_level=1.0,
    )
    assert not result.gdp_reconciles
    assert result.firm_profit_from_ledger != result.firm_profit_from_flows


def test_credit_outstanding_passes_through_the_callers_aggregate() -> None:
    econ = Economy()
    firm = econ.add_firm("firm-1")
    firm.capitalize(usd(1_000))
    result = compute_macro_aggregates(
        consumption_spending=Money.zero("USD"),
        wages_paid=Money.zero("USD"),
        opening_firm_equity=firm.net_worth,
        closing_firm_equity=firm.net_worth,
        credit_outstanding=usd(50_000),
        price_level=1.0,
    )
    assert result.credit_outstanding == usd(50_000)


def test_inflation_rate_is_the_percentage_change_in_price_level() -> None:
    econ = Economy()
    firm = econ.add_firm("firm-1")
    result = compute_macro_aggregates(
        consumption_spending=Money.zero("USD"),
        wages_paid=Money.zero("USD"),
        opening_firm_equity=firm.net_worth,
        closing_firm_equity=firm.net_worth,
        credit_outstanding=Money.zero("USD"),
        price_level=1.03,
        prior_price_level=1.00,
    )
    assert result.inflation_rate_pct == pytest.approx(3.0)


def test_inflation_rate_is_none_without_a_prior_price_level() -> None:
    econ = Economy()
    firm = econ.add_firm("firm-1")
    result = compute_macro_aggregates(
        consumption_spending=Money.zero("USD"),
        wages_paid=Money.zero("USD"),
        opening_firm_equity=firm.net_worth,
        closing_firm_equity=firm.net_worth,
        credit_outstanding=Money.zero("USD"),
        price_level=1.0,
    )
    assert result.inflation_rate_pct is None


def test_rejects_negative_consumption_or_wages() -> None:
    econ = Economy()
    firm = econ.add_firm("firm-1")
    with pytest.raises(ValueError, match="consumption_spending"):
        compute_macro_aggregates(
            consumption_spending=Money(-100, "USD"),
            wages_paid=Money.zero("USD"),
            opening_firm_equity=firm.net_worth,
            closing_firm_equity=firm.net_worth,
            credit_outstanding=Money.zero("USD"),
            price_level=1.0,
        )
    with pytest.raises(ValueError, match="wages_paid"):
        compute_macro_aggregates(
            consumption_spending=Money.zero("USD"),
            wages_paid=Money(-100, "USD"),
            opening_firm_equity=firm.net_worth,
            closing_firm_equity=firm.net_worth,
            credit_outstanding=Money.zero("USD"),
            price_level=1.0,
        )


def test_rejects_non_positive_price_levels() -> None:
    econ = Economy()
    firm = econ.add_firm("firm-1")
    with pytest.raises(ValueError, match="price_level"):
        compute_macro_aggregates(
            consumption_spending=Money.zero("USD"),
            wages_paid=Money.zero("USD"),
            opening_firm_equity=firm.net_worth,
            closing_firm_equity=firm.net_worth,
            credit_outstanding=Money.zero("USD"),
            price_level=0.0,
        )
    with pytest.raises(ValueError, match="prior_price_level"):
        compute_macro_aggregates(
            consumption_spending=Money.zero("USD"),
            wages_paid=Money.zero("USD"),
            opening_firm_equity=firm.net_worth,
            closing_firm_equity=firm.net_worth,
            credit_outstanding=Money.zero("USD"),
            price_level=1.0,
            prior_price_level=-1.0,
        )
