import pytest

from prometheus.core.money import Money
from prometheus.econosim.economy import Economy
from prometheus.econosim.liquidity import (
    LiquidityAssumptions,
    ask_price,
    bid_price,
    round_trip_cost,
)


def test_rejects_negative_spread() -> None:
    with pytest.raises(ValueError, match="non-negative"):
        LiquidityAssumptions(spread_bps=-1.0)


def test_rejects_zero_spread_without_explicit_frictionless_flag() -> None:
    """The literal LED-09 enforcement: a caller cannot get a zero-cost
    quote by accident."""
    with pytest.raises(ValueError, match="frictionless=True"):
        LiquidityAssumptions(spread_bps=0.0)
    with pytest.raises(ValueError, match="frictionless=True"):
        LiquidityAssumptions(spread_bps=0.0, frictionless=False)


def test_rejects_frictionless_flag_with_a_nonzero_spread() -> None:
    with pytest.raises(ValueError, match="spread_bps == 0"):
        LiquidityAssumptions(spread_bps=10.0, frictionless=True)


def test_zero_spread_frictionless_baseline_is_accepted() -> None:
    assumptions = LiquidityAssumptions(spread_bps=0.0, frictionless=True)
    assert ask_price(100.0, assumptions) == pytest.approx(100.0)
    assert bid_price(100.0, assumptions) == pytest.approx(100.0)
    assert round_trip_cost(1000.0, assumptions) == 0.0


def test_ask_is_above_mid_and_bid_is_below_mid() -> None:
    assumptions = LiquidityAssumptions(spread_bps=20.0)  # 20 bps = 0.20%
    ask = ask_price(100.0, assumptions)
    bid = bid_price(100.0, assumptions)
    assert ask > 100.0
    assert bid < 100.0
    assert ask == pytest.approx(100.10)
    assert bid == pytest.approx(99.90)


def test_ask_and_bid_are_symmetric_around_mid() -> None:
    assumptions = LiquidityAssumptions(spread_bps=50.0)
    mid = 200.0
    ask = ask_price(mid, assumptions)
    bid = bid_price(mid, assumptions)
    assert (ask + bid) / 2.0 == pytest.approx(mid)
    assert (ask - bid) == pytest.approx(mid * 50.0 / 10_000.0)


def test_round_trip_cost_matches_the_spread_fraction_of_notional() -> None:
    assumptions = LiquidityAssumptions(spread_bps=25.0)
    cost = round_trip_cost(10_000.0, assumptions)
    assert cost == pytest.approx(10_000.0 * 25.0 / 10_000.0)
    assert cost == pytest.approx(25.0)


def test_round_trip_cost_scales_linearly_with_notional() -> None:
    assumptions = LiquidityAssumptions(spread_bps=15.0)
    small = round_trip_cost(100.0, assumptions)
    large = round_trip_cost(1000.0, assumptions)
    assert large == pytest.approx(small * 10.0)


def test_ask_price_rejects_non_positive_mid() -> None:
    assumptions = LiquidityAssumptions(spread_bps=10.0)
    with pytest.raises(ValueError, match="mid_price"):
        ask_price(0.0, assumptions)
    with pytest.raises(ValueError, match="mid_price"):
        bid_price(-5.0, assumptions)


def test_round_trip_cost_rejects_negative_notional() -> None:
    assumptions = LiquidityAssumptions(spread_bps=10.0)
    with pytest.raises(ValueError, match="notional"):
        round_trip_cost(-1.0, assumptions)


def test_spread_quote_reduces_combined_wealth_versus_a_frictionless_trade() -> None:
    """Demonstrates the real economic effect by composing with the
    EXISTING, unmodified econosim ledger (Household.consume), not just
    checking the pure quoting math in isolation: a household buying a
    fixed quantity at the ASK price pays strictly more than it would at
    the frictionless mid price, for the same goods -- the spread is a
    genuine friction cost, not a bookkeeping abstraction with no
    ledger-level consequence."""
    mid_price = 100.0
    quantity = 10
    spreadful = LiquidityAssumptions(spread_bps=50.0)
    frictionless = LiquidityAssumptions(spread_bps=0.0, frictionless=True)

    econ_a = Economy()
    hh_a = econ_a.add_household("hh-1")
    firm_a = econ_a.add_firm("firm-1")
    hh_a.receive_income(Money(1_000_000, "USD"))  # $10,000.00, in cents
    cost_with_spread = ask_price(mid_price, spreadful) * quantity
    hh_a.consume(firm_a, Money(round(cost_with_spread * 100), "USD"))

    econ_b = Economy()
    hh_b = econ_b.add_household("hh-1")
    firm_b = econ_b.add_firm("firm-1")
    hh_b.receive_income(Money(1_000_000, "USD"))  # $10,000.00, in cents
    cost_frictionless = ask_price(mid_price, frictionless) * quantity
    hh_b.consume(firm_b, Money(round(cost_frictionless * 100), "USD"))

    assert cost_with_spread > cost_frictionless
    assert hh_a.cash_balance < hh_b.cash_balance
    econ_a.check_integrity()
    econ_b.check_integrity()
