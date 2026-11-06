from datetime import date, timedelta

import numpy as np
import pytest

from prometheus.titan.positions import (
    InstrumentMismatchError,
    Position,
    PositionBook,
    StaleSnapshotError,
    total_market_value,
    total_unrealized_pnl,
    value_book,
    value_position,
)
from prometheus.titan.risk_metrics import historical_var, pnl_to_losses
from prometheus.volterra.american_options import american_binomial_price
from prometheus.volterra.black_scholes import black_scholes_price
from prometheus.volterra.forwards import forward_contract_value, forward_price
from prometheus.volterra.instruments import AmericanOption, EuropeanOption, ForwardContract
from prometheus.volterra.market import MarketSnapshot


def _snapshot(day_offset: int = 0, spot: float = 100.0) -> MarketSnapshot:
    return MarketSnapshot(date(2026, 1, 1) + timedelta(days=day_offset), spot, 0.03, 0.2)


def _entry_position(position_id: str = "p1", quantity: float = 10.0) -> Position:
    snapshot = _snapshot()
    instrument = EuropeanOption(100.0, 1.0, "call")
    price = black_scholes_price(snapshot, instrument)
    return Position(position_id, instrument, quantity, snapshot, price)


def test_position_rejects_empty_id() -> None:
    snapshot = _snapshot()
    instrument = EuropeanOption(100.0, 1.0, "call")
    with pytest.raises(ValueError):
        Position("", instrument, 10.0, snapshot, 1.0)


def test_position_rejects_zero_quantity() -> None:
    snapshot = _snapshot()
    instrument = EuropeanOption(100.0, 1.0, "call")
    with pytest.raises(ValueError):
        Position("p1", instrument, 0.0, snapshot, 1.0)


def test_position_rejects_non_finite_quantity() -> None:
    snapshot = _snapshot()
    instrument = EuropeanOption(100.0, 1.0, "call")
    with pytest.raises(ValueError):
        Position("p1", instrument, float("nan"), snapshot, 1.0)


def test_position_rejects_negative_entry_price() -> None:
    snapshot = _snapshot()
    instrument = EuropeanOption(100.0, 1.0, "call")
    with pytest.raises(ValueError):
        Position("p1", instrument, 10.0, snapshot, -1.0)


def test_valuing_at_the_exact_entry_snapshot_gives_zero_unrealized_pnl() -> None:
    position = _entry_position()
    valuation = value_position(position, position.instrument, position.entry_snapshot)
    assert valuation.unrealized_pnl == pytest.approx(0.0, abs=1e-9)
    assert valuation.market_value == pytest.approx(position.quantity * position.entry_price)


def test_valuation_matches_direct_black_scholes_computation() -> None:
    position = _entry_position(quantity=10.0)
    current_snapshot = _snapshot(day_offset=30, spot=105.0)
    current_instrument = EuropeanOption(100.0, 1.0 - 30 / 365.25, "call")

    valuation = value_position(position, current_instrument, current_snapshot)

    expected_mark = black_scholes_price(current_snapshot, current_instrument)
    assert valuation.mark_price == pytest.approx(expected_mark)
    assert valuation.market_value == pytest.approx(10.0 * expected_mark)
    assert valuation.unrealized_pnl == pytest.approx(10.0 * (expected_mark - position.entry_price))
    assert valuation.as_of == current_snapshot.as_of


def test_short_position_has_inverted_pnl_sign_relative_to_mark_move() -> None:
    long_position = _entry_position("long", quantity=10.0)
    short_position = _entry_position("short", quantity=-10.0)
    current_snapshot = _snapshot(day_offset=10, spot=110.0)
    current_instrument = EuropeanOption(100.0, 1.0 - 10 / 365.25, "call")

    long_valuation = value_position(long_position, current_instrument, current_snapshot)
    short_valuation = value_position(short_position, current_instrument, current_snapshot)

    assert short_valuation.market_value == pytest.approx(-long_valuation.market_value)
    assert short_valuation.unrealized_pnl == pytest.approx(-long_valuation.unrealized_pnl)


def test_rejects_snapshot_preceding_the_entry_snapshot() -> None:
    position = _entry_position()
    stale_snapshot = _snapshot(day_offset=-10)
    with pytest.raises(StaleSnapshotError):
        value_position(position, position.instrument, stale_snapshot)


def test_rejects_snapshot_exceeding_the_freshness_tolerance() -> None:
    position = _entry_position()
    current_snapshot = _snapshot(day_offset=30, spot=100.0)
    current_instrument = EuropeanOption(100.0, 1.0 - 30 / 365.25, "call")
    with pytest.raises(StaleSnapshotError):
        value_position(
            position,
            current_instrument,
            current_snapshot,
            as_of=date(2026, 3, 1),
            max_staleness_days=5,
        )


def test_accepts_snapshot_within_the_freshness_tolerance() -> None:
    position = _entry_position()
    current_snapshot = _snapshot(day_offset=30, spot=100.0)
    current_instrument = EuropeanOption(100.0, 1.0 - 30 / 365.25, "call")
    valuation = value_position(
        position,
        current_instrument,
        current_snapshot,
        as_of=date(2026, 2, 2),
        max_staleness_days=5,
    )
    assert valuation.as_of == current_snapshot.as_of


def test_rejects_as_of_preceding_the_snapshot() -> None:
    position = _entry_position()
    current_snapshot = _snapshot(day_offset=30, spot=100.0)
    current_instrument = EuropeanOption(100.0, 1.0 - 30 / 365.25, "call")
    with pytest.raises(ValueError):
        value_position(
            position,
            current_instrument,
            current_snapshot,
            as_of=date(2026, 1, 1),
            max_staleness_days=5,
        )


def test_rejects_mismatched_strike() -> None:
    position = _entry_position()
    wrong_instrument = EuropeanOption(110.0, 0.9, "call")
    with pytest.raises(InstrumentMismatchError):
        value_position(position, wrong_instrument, _snapshot(day_offset=10))


def test_rejects_mismatched_option_type() -> None:
    position = _entry_position()
    wrong_instrument = EuropeanOption(100.0, 0.9, "put")
    with pytest.raises(InstrumentMismatchError):
        value_position(position, wrong_instrument, _snapshot(day_offset=10))


def test_rejects_maturity_running_backward() -> None:
    position = _entry_position()
    longer_instrument = EuropeanOption(100.0, 1.5, "call")
    with pytest.raises(ValueError):
        value_position(position, longer_instrument, _snapshot(day_offset=10))


def test_position_book_rejects_empty_positions() -> None:
    with pytest.raises(ValueError):
        PositionBook(())


def test_position_book_rejects_duplicate_ids() -> None:
    position_a = _entry_position("dup")
    position_b = _entry_position("dup")
    with pytest.raises(ValueError):
        PositionBook((position_a, position_b))


def test_value_book_rejects_a_missing_current_instrument() -> None:
    book = PositionBook((_entry_position("p1"),))
    with pytest.raises(ValueError):
        value_book(book, {}, _snapshot(day_offset=10))


def test_value_book_aggregates_a_long_and_a_short_position_correctly() -> None:
    entry_snapshot = _snapshot()
    call = EuropeanOption(100.0, 1.0, "call")
    put = EuropeanOption(100.0, 1.0, "put")
    call_price = black_scholes_price(entry_snapshot, call)
    put_price = black_scholes_price(entry_snapshot, put)
    book = PositionBook(
        (
            Position("long_call", call, 10.0, entry_snapshot, call_price),
            Position("short_put", put, -5.0, entry_snapshot, put_price),
        )
    )

    current_snapshot = _snapshot(day_offset=31, spot=95.0)
    elapsed = (current_snapshot.as_of - entry_snapshot.as_of).days / 365.25
    current_instruments = {
        "long_call": EuropeanOption(100.0, 1.0 - elapsed, "call"),
        "short_put": EuropeanOption(100.0, 1.0 - elapsed, "put"),
    }
    valuations = value_book(book, current_instruments, current_snapshot)

    assert len(valuations) == 2
    expected_total_value = sum(v.market_value for v in valuations)
    expected_total_pnl = sum(v.unrealized_pnl for v in valuations)
    assert total_market_value(valuations) == pytest.approx(expected_total_value)
    assert total_unrealized_pnl(valuations) == pytest.approx(expected_total_pnl)


def test_connects_to_titan_risk_metrics_for_a_real_var_pipeline() -> None:
    """A full pipeline, not isolated unit checks: mark a single-position
    book to a simulated daily spot path, build a realized daily P&L
    series from the resulting market values, and compute its historical
    VaR with titan.risk_metrics -- an independent, already-evidenced
    module, not reimplemented here."""
    entry_snapshot = _snapshot()
    instrument = EuropeanOption(100.0, 1.0, "call")
    entry_price = black_scholes_price(entry_snapshot, instrument)
    book = PositionBook((Position("p1", instrument, 10.0, entry_snapshot, entry_price),))

    rng = np.random.default_rng(0)
    n_days = 200
    spots = 100.0 * np.exp(np.cumsum(rng.normal(0.0, 0.012, n_days)))
    market_values = [10.0 * entry_price]
    for day in range(n_days):
        elapsed = (day + 1) / 365.25
        remaining = 1.0 - elapsed
        snapshot = _snapshot(day_offset=day + 1, spot=float(spots[day]))
        current_instruments = {"p1": EuropeanOption(100.0, remaining, "call")}
        valuations = value_book(book, current_instruments, snapshot)
        market_values.append(total_market_value(valuations))

    pnl = np.diff(np.array(market_values))
    losses = pnl_to_losses(pnl)
    var95 = historical_var(losses, 0.95)

    assert np.isfinite(var95)
    assert len(pnl) == n_days


def _forward_position(position_id: str = "f1", quantity: float = 5.0) -> Position:
    entry_snapshot = _snapshot()
    delivery_price = forward_price(entry_snapshot, 1.0)
    instrument = ForwardContract(delivery_price, 1.0)
    return Position(position_id, instrument, quantity, entry_snapshot, entry_price=0.0)


def test_forward_position_valuation_matches_direct_computation() -> None:
    position = _forward_position(quantity=5.0)
    current_snapshot = _snapshot(day_offset=30, spot=105.0)
    current_instrument = ForwardContract(position.instrument.delivery_price, 1.0 - 30 / 365.25)

    valuation = value_position(position, current_instrument, current_snapshot)

    expected_mark = forward_contract_value(current_snapshot, current_instrument)
    assert valuation.mark_price == pytest.approx(expected_mark)
    assert valuation.market_value == pytest.approx(5.0 * expected_mark)
    assert valuation.unrealized_pnl == pytest.approx(valuation.market_value)  # entry_price is 0


def test_forward_position_at_entry_has_zero_unrealized_pnl() -> None:
    """A fairly-priced forward (delivery price = forward_price at entry)
    is worth exactly zero at the moment it is entered -- the defining
    no-arbitrage property, checked through the position layer too."""
    position = _forward_position()
    valuation = value_position(position, position.instrument, position.entry_snapshot)
    assert valuation.market_value == pytest.approx(0.0, abs=1e-9)
    assert valuation.unrealized_pnl == pytest.approx(0.0, abs=1e-9)


def test_forward_position_rejects_mismatched_delivery_price() -> None:
    position = _forward_position()
    wrong_instrument = ForwardContract(position.instrument.delivery_price + 10.0, 0.9)
    with pytest.raises(InstrumentMismatchError):
        value_position(position, wrong_instrument, _snapshot(day_offset=10))


def test_cross_type_reprice_is_rejected_both_ways() -> None:
    """An option position cannot be repriced as a forward, and a forward
    position cannot be repriced as an option -- the type itself, not just
    the identifying terms, must match."""
    option_position = _entry_position()
    forward_position = _forward_position()
    mismatched_forward = ForwardContract(100.0, 0.9)
    mismatched_option = EuropeanOption(100.0, 0.9, "call")

    with pytest.raises(InstrumentMismatchError):
        value_position(option_position, mismatched_forward, _snapshot(day_offset=10))
    with pytest.raises(InstrumentMismatchError):
        value_position(forward_position, mismatched_option, _snapshot(day_offset=10))


def test_position_book_can_mix_option_and_forward_instruments() -> None:
    entry_snapshot = _snapshot()
    call = EuropeanOption(100.0, 1.0, "call")
    call_price = black_scholes_price(entry_snapshot, call)
    delivery_price = forward_price(entry_snapshot, 1.0)
    forward = ForwardContract(delivery_price, 1.0)

    book = PositionBook(
        (
            Position("opt1", call, 10.0, entry_snapshot, call_price),
            Position("fwd1", forward, 5.0, entry_snapshot, 0.0),
        )
    )
    current_snapshot = _snapshot(day_offset=30, spot=105.0)
    elapsed = 30 / 365.25
    current_instruments = {
        "opt1": EuropeanOption(100.0, 1.0 - elapsed, "call"),
        "fwd1": ForwardContract(delivery_price, 1.0 - elapsed),
    }

    valuations = value_book(book, current_instruments, current_snapshot)

    assert len(valuations) == 2
    expected_total = sum(v.market_value for v in valuations)
    assert total_market_value(valuations) == pytest.approx(expected_total)


def _american_position(position_id: str = "am1", quantity: float = 10.0) -> Position:
    entry_snapshot = _snapshot(day_offset=0)
    instrument = AmericanOption(100.0, 1.0, "put")
    entry_price = american_binomial_price(entry_snapshot, instrument, 200)
    return Position(position_id, instrument, quantity, entry_snapshot, entry_price)


def test_american_position_valuation_requires_n_steps() -> None:
    position = _american_position()
    current_snapshot = _snapshot(day_offset=30, spot=95.0)
    current_instrument = AmericanOption(100.0, 1.0 - 30 / 365.25, "put")
    with pytest.raises(ValueError):
        value_position(position, current_instrument, current_snapshot)


def test_american_position_valuation_matches_direct_computation() -> None:
    position = _american_position(quantity=10.0)
    current_snapshot = _snapshot(day_offset=30, spot=95.0)
    current_instrument = AmericanOption(100.0, 1.0 - 30 / 365.25, "put")

    valuation = value_position(position, current_instrument, current_snapshot, n_steps=200)

    expected_mark = american_binomial_price(current_snapshot, current_instrument, 200)
    assert valuation.mark_price == pytest.approx(expected_mark)
    assert valuation.market_value == pytest.approx(10.0 * expected_mark)


def test_n_steps_is_not_required_for_european_or_forward_positions() -> None:
    """n_steps is ignored (not required) for instruments that don't need
    it -- requiring it unconditionally would break every existing caller
    of value_position for non-American positions."""
    option_position = _entry_position()
    valuation = value_position(
        option_position, option_position.instrument, option_position.entry_snapshot, n_steps=None
    )
    assert valuation.unrealized_pnl == pytest.approx(0.0, abs=1e-9)


def test_american_vs_european_with_identical_strike_and_type_is_a_mismatch() -> None:
    """Even with identical strike and option_type, an AmericanOption and a
    EuropeanOption are different instrument TYPES -- repricing one as the
    other must be rejected, exactly like the forward/option mismatch."""
    position = _american_position()
    european_equivalent = EuropeanOption(100.0, 0.9, "put")
    with pytest.raises(InstrumentMismatchError):
        value_position(position, european_equivalent, _snapshot(day_offset=10), n_steps=200)


def test_position_book_can_mix_all_three_instrument_types() -> None:
    entry_snapshot = _snapshot()
    call = EuropeanOption(100.0, 1.0, "call")
    call_price = black_scholes_price(entry_snapshot, call)
    delivery_price = forward_price(entry_snapshot, 1.0)
    forward = ForwardContract(delivery_price, 1.0)
    american_put = AmericanOption(100.0, 1.0, "put")
    american_price = american_binomial_price(entry_snapshot, american_put, 200)

    book = PositionBook(
        (
            Position("opt_eu", call, 10.0, entry_snapshot, call_price),
            Position("opt_am", american_put, 10.0, entry_snapshot, american_price),
            Position("fwd", forward, 5.0, entry_snapshot, 0.0),
        )
    )
    current_snapshot = _snapshot(day_offset=30, spot=95.0)
    elapsed = 30 / 365.25
    current_instruments = {
        "opt_eu": EuropeanOption(100.0, 1.0 - elapsed, "call"),
        "opt_am": AmericanOption(100.0, 1.0 - elapsed, "put"),
        "fwd": ForwardContract(delivery_price, 1.0 - elapsed),
    }

    valuations = value_book(book, current_instruments, current_snapshot, n_steps=200)

    assert len(valuations) == 3
    expected_total = sum(v.market_value for v in valuations)
    assert total_market_value(valuations) == pytest.approx(expected_total)
