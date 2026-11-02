import pytest

from prometheus.core.money import Money
from prometheus.econosim.economy import Economy
from prometheus.econosim.market_clearing import (
    apply_goods_clearing_to_ledger,
    apply_labor_clearing_to_ledger,
    clear_quantity_market,
)


def test_rejects_negative_quantities() -> None:
    with pytest.raises(ValueError):
        clear_quantity_market({"a": -1.0}, {"b": 1.0})
    with pytest.raises(ValueError):
        clear_quantity_market({"a": 1.0}, {"b": -1.0})


def test_exact_match_realizes_everything() -> None:
    result = clear_quantity_market({"buyer": 10.0}, {"seller": 10.0})
    assert result.realized_buy_quantities == {"buyer": 10.0}
    assert result.realized_sell_quantities == {"seller": 10.0}
    assert result.clearing_residual == 0.0


def test_excess_supply_rations_sellers_pro_rata() -> None:
    result = clear_quantity_market({"buyer": 15.0}, {"s1": 10.0, "s2": 10.0})
    assert result.total_realized_quantity == 15.0
    assert result.realized_buy_quantities == {"buyer": 15.0}  # buyer fully served
    assert result.realized_sell_quantities == {"s1": 7.5, "s2": 7.5}  # sellers rationed equally
    assert result.clearing_residual == 15.0 - 20.0


def test_excess_demand_rations_buyers_pro_rata() -> None:
    result = clear_quantity_market({"b1": 10.0, "b2": 20.0}, {"seller": 15.0})
    assert result.total_realized_quantity == 15.0
    assert result.realized_sell_quantities == {"seller": 15.0}  # seller fully served
    # buyers rationed proportional to their original desired quantity (1:2 split of 15 -> 5:10)
    assert result.realized_buy_quantities == pytest.approx({"b1": 5.0, "b2": 10.0})
    assert result.clearing_residual == 30.0 - 15.0


def test_zero_demand_or_supply_handled_without_division_errors() -> None:
    result = clear_quantity_market({}, {"seller": 10.0})
    assert result.total_realized_quantity == 0.0
    assert result.realized_sell_quantities == {"seller": 0.0}

    result2 = clear_quantity_market({"buyer": 10.0}, {})
    assert result2.total_realized_quantity == 0.0
    assert result2.realized_buy_quantities == {"buyer": 0.0}


@pytest.mark.parametrize(
    "buy_orders,sell_orders",
    [
        ({"a": 7.0, "b": 13.0}, {"c": 20.0}),
        ({"a": 100.0}, {"c": 30.0, "d": 70.0}),
        ({"a": 1.0, "b": 2.0, "c": 3.0}, {"d": 4.0, "e": 1.0}),
    ],
)
def test_no_double_counting_sums_match_realized_total(
    buy_orders: dict[str, float], sell_orders: dict[str, float]
) -> None:
    """ECO-08's structural property: summing either side's realized
    quantities always equals total_realized_quantity exactly, for any mix
    of participants and any supply/demand imbalance."""
    result = clear_quantity_market(buy_orders, sell_orders)
    assert sum(result.realized_buy_quantities.values()) == pytest.approx(
        result.total_realized_quantity
    )
    assert sum(result.realized_sell_quantities.values()) == pytest.approx(
        result.total_realized_quantity
    )


def _funded_economy() -> tuple[Economy, "object", dict]:
    from prometheus.econosim.agents import Firm, Household

    econ = Economy()
    firm: Firm = econ.add_firm("firm-1")
    households: dict[str, Household] = {
        "hh-1": econ.add_household("hh-1"),
        "hh-2": econ.add_household("hh-2"),
    }
    for hh in households.values():
        hh.receive_income(Money(1_000_00, "USD"))
    households["hh-1"].consume(firm, Money(500_00, "USD"))  # seed firm with cash
    return econ, firm, households


def test_labor_clearing_pays_realized_not_desired_hours() -> None:
    econ, firm, households = _funded_economy()
    hh1, hh2 = households["hh-1"], households["hh-2"]
    cash_before_hh1, cash_before_hh2 = hh1.cash_balance, hh2.cash_balance
    firm_cash_before = firm.cash_balance

    # firm wants 15 hours; households offer 20 total (oversupply) -> 15 realized, split 7.5/7.5
    clearing = clear_quantity_market(
        buy_orders={firm.agent_id: 15.0},
        sell_orders={hh1.agent_id: 10.0, hh2.agent_id: 10.0},
    )
    apply_labor_clearing_to_ledger(clearing, households, firm, Money(1000, "USD"))

    expected_wage_each = Money(int(7.5 * 1000), "USD")
    assert hh1.cash_balance - cash_before_hh1 == expected_wage_each
    assert hh2.cash_balance - cash_before_hh2 == expected_wage_each
    assert firm_cash_before - firm.cash_balance == expected_wage_each * 2
    econ.check_integrity()


def test_goods_clearing_charges_realized_not_desired_quantity() -> None:
    econ, firm, households = _funded_economy()
    hh1, hh2 = households["hh-1"], households["hh-2"]
    cash_before_hh1, cash_before_hh2 = hh1.cash_balance, hh2.cash_balance
    firm_cash_before = firm.cash_balance

    # households want 10 total; firm supplies only 8 (shortage) -> 8 realized, split 4/4
    clearing = clear_quantity_market(
        buy_orders={hh1.agent_id: 5.0, hh2.agent_id: 5.0},
        sell_orders={firm.agent_id: 8.0},
    )
    apply_goods_clearing_to_ledger(clearing, firm, households, Money(500, "USD"))

    expected_charge_each = Money(int(4.0 * 500), "USD")
    assert cash_before_hh1 - hh1.cash_balance == expected_charge_each
    assert cash_before_hh2 - hh2.cash_balance == expected_charge_each
    assert firm.cash_balance - firm_cash_before == expected_charge_each * 2
    econ.check_integrity()


def test_apply_labor_clearing_rejects_unknown_household_id() -> None:
    econ, firm, households = _funded_economy()
    clearing = clear_quantity_market(
        buy_orders={firm.agent_id: 5.0}, sell_orders={"ghost-household": 5.0}
    )
    with pytest.raises(KeyError):
        apply_labor_clearing_to_ledger(clearing, households, firm, Money(1000, "USD"))


def test_zero_realized_quantity_posts_no_transaction() -> None:
    econ, firm, households = _funded_economy()
    hh1 = households["hh-1"]
    cash_before = hh1.cash_balance
    clearing = clear_quantity_market(
        buy_orders={firm.agent_id: 0.0}, sell_orders={hh1.agent_id: 0.0}
    )
    transactions = apply_labor_clearing_to_ledger(clearing, households, firm, Money(1000, "USD"))
    assert transactions == []
    assert hh1.cash_balance == cash_before
