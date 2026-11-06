"""GDP, inflation and credit aggregate definitions, cross-validated
against the ledger rather than assumed (ECO-15: "GDP/inflation/credit
definitions documented and validated").

GDP, two independent approaches:

  expenditure  = consumption_spending (the only expenditure category this
                 model has -- no government purchases of goods/services
                 are modeled, only taxes and transfers, which are
                 correctly EXCLUDED from GDP under standard national
                 accounting; no investment or net exports either)
  income       = wages_paid + firm_profit_from_ledger

`firm_profit_from_ledger` is `closing_firm_equity - opening_firm_equity`
-- real ledger data, a genuinely SEPARATE code path from
`consumption_spending - wages_paid` (`firm_profit_from_flows`, the
caller's own running total of the two flow amounts). Comparing the two
is a real cross-check, not a tautology: if `consumption_spending == the
sum of every Household.consume amount in the period` and `wages_paid ==
the sum of every Firm.pay_wages amount`, AND no OTHER transaction touched
the firm's equity account during the period (e.g. a mid-period
`Firm.capitalize`), the two must agree exactly; if they disagree, either
the caller's flow totals are wrong or an un-modeled equity-touching event
occurred, and this function says so rather than reporting a GDP number
with unknown provenance.

Confirmed on a real two-household-one-firm-one-government `Economy`
scenario before being trusted: taxes and transfers (which pass through
Household/Government accounts only, never `Firm.equity_account`) leave
`firm_profit_from_ledger` completely unaffected, exactly as the
"transfers excluded from GDP" definition requires -- and a deliberately
dirtied period (an extra mid-period `Firm.capitalize`) was confirmed to
break the identity rather than silently average away, exactly the
"validated" failure mode this function exists to catch.

Credit aggregate: the sum of outstanding bank loans across however many
banks the caller supplies (`Bank.loans_outstanding` each) -- total
private credit extended in the economy.

Inflation: percentage change in a caller-supplied price level between
two periods. This repository's goods market has no endogenous price
discovery (`econosim.market_clearing`'s own docstring: "there is no
iterative price discovery... a buyer and a seller each submit a desired
quantity at an already-given price"), so "the price level" is whatever
price the simulation driver used to clear that period's goods market,
supplied here rather than inferred.
"""

from __future__ import annotations

from dataclasses import dataclass

from prometheus.core.money import Money


@dataclass(frozen=True, slots=True)
class MacroAggregates:
    gdp_expenditure: Money
    gdp_income: Money
    firm_profit_from_ledger: Money
    firm_profit_from_flows: Money
    gdp_reconciles: bool
    credit_outstanding: Money
    inflation_rate_pct: float | None


def compute_macro_aggregates(
    consumption_spending: Money,
    wages_paid: Money,
    opening_firm_equity: Money,
    closing_firm_equity: Money,
    credit_outstanding: Money,
    price_level: float,
    prior_price_level: float | None = None,
) -> MacroAggregates:
    """`credit_outstanding` is already the caller's own sum across every
    bank (e.g. `sum(bank.loans_outstanding for bank in banks)`) -- this
    function does not iterate banks itself, so it has no opinion on how
    many there are. `price_level`/`prior_price_level` are whatever units
    the caller's own goods-market price is denominated in; inflation is
    their percentage change, `None` when no `prior_price_level` is given
    (the first period in a run has nothing to compare against)."""
    if consumption_spending.is_negative():
        raise ValueError("consumption_spending must be non-negative")
    if wages_paid.is_negative():
        raise ValueError("wages_paid must be non-negative")
    if price_level <= 0.0:
        raise ValueError("price_level must be positive")
    if prior_price_level is not None and prior_price_level <= 0.0:
        raise ValueError("prior_price_level must be positive")

    firm_profit_from_ledger = closing_firm_equity - opening_firm_equity
    firm_profit_from_flows = consumption_spending - wages_paid
    gdp_expenditure = consumption_spending
    gdp_income = wages_paid + firm_profit_from_ledger

    inflation_rate_pct = None
    if prior_price_level is not None:
        inflation_rate_pct = (price_level / prior_price_level - 1.0) * 100.0

    return MacroAggregates(
        gdp_expenditure=gdp_expenditure,
        gdp_income=gdp_income,
        firm_profit_from_ledger=firm_profit_from_ledger,
        firm_profit_from_flows=firm_profit_from_flows,
        gdp_reconciles=(
            gdp_expenditure == gdp_income and firm_profit_from_ledger == firm_profit_from_flows
        ),
        credit_outstanding=credit_outstanding,
        inflation_rate_pct=inflation_rate_pct,
    )
