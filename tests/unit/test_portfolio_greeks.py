from datetime import date

import pytest

from prometheus.titan.portfolio_greeks import (
    LineGreeks,
    PortfolioGreeksReport,
    aggregate_portfolio_greeks,
    greeks_from_position_book,
    verify_reconciliation,
)
from prometheus.titan.positions import Position, PositionBook
from prometheus.volterra.black_scholes import Greeks, black_scholes_greeks
from prometheus.volterra.heston_greeks import heston_finite_difference_greeks
from prometheus.volterra.instruments import EuropeanOption
from prometheus.volterra.market import MarketSnapshot
from prometheus.volterra.merton_greeks import merton_finite_difference_greeks


def _greeks(**overrides: float) -> Greeks:
    defaults: dict = dict(delta=0.5, gamma=0.02, vega=30.0, theta=-5.0, rho=40.0)
    defaults.update(overrides)
    return Greeks(**defaults)


def test_line_greeks_rejects_invalid_fields() -> None:
    with pytest.raises(ValueError):
        LineGreeks(position_id="", quantity=1.0, per_unit=_greeks())
    with pytest.raises(ValueError):
        LineGreeks(position_id="A", quantity=0.0, per_unit=_greeks())
    with pytest.raises(ValueError):
        LineGreeks(position_id="A", quantity=float("nan"), per_unit=_greeks())


def test_line_greeks_scaled_multiplies_every_field_by_quantity() -> None:
    line = LineGreeks(position_id="A", quantity=3.0, per_unit=_greeks())
    scaled = line.scaled
    assert scaled.delta == pytest.approx(1.5)
    assert scaled.gamma == pytest.approx(0.06)
    assert scaled.vega == pytest.approx(90.0)
    assert scaled.theta == pytest.approx(-15.0)
    assert scaled.rho == pytest.approx(120.0)


def test_aggregate_rejects_empty_or_duplicate_lines() -> None:
    with pytest.raises(ValueError):
        aggregate_portfolio_greeks([], date(2026, 1, 1))
    lines = [
        LineGreeks(position_id="A", quantity=1.0, per_unit=_greeks()),
        LineGreeks(position_id="A", quantity=-1.0, per_unit=_greeks()),
    ]
    with pytest.raises(ValueError):
        aggregate_portfolio_greeks(lines, date(2026, 1, 1))


def test_aggregate_totals_equal_the_sum_of_scaled_lines_with_distinct_greeks() -> None:
    lines = [
        LineGreeks(position_id="A", quantity=2.0, per_unit=_greeks(delta=0.5, gamma=0.02)),
        LineGreeks(position_id="B", quantity=-1.0, per_unit=_greeks(delta=0.3, gamma=0.01)),
        LineGreeks(position_id="C", quantity=5.0, per_unit=_greeks(delta=-0.4, gamma=0.03)),
    ]
    report = aggregate_portfolio_greeks(lines, date(2026, 1, 1))

    expected_delta = 2.0 * 0.5 + (-1.0) * 0.3 + 5.0 * (-0.4)
    expected_gamma = 2.0 * 0.02 + (-1.0) * 0.01 + 5.0 * 0.03
    assert report.total.delta == pytest.approx(expected_delta)
    assert report.total.gamma == pytest.approx(expected_gamma)
    assert report.as_of == date(2026, 1, 1)
    assert verify_reconciliation(report) is True


def test_offsetting_long_and_short_positions_net_to_zero_delta() -> None:
    lines = [
        LineGreeks(position_id="long", quantity=10.0, per_unit=_greeks(delta=0.6)),
        LineGreeks(position_id="short", quantity=-10.0, per_unit=_greeks(delta=0.6)),
    ]
    report = aggregate_portfolio_greeks(lines, date(2026, 1, 1))
    assert report.total.delta == pytest.approx(0.0, abs=1e-12)


def test_verify_reconciliation_detects_a_tampered_total() -> None:
    lines = [LineGreeks(position_id="A", quantity=2.0, per_unit=_greeks(delta=0.5))]
    report = aggregate_portfolio_greeks(lines, date(2026, 1, 1))
    tampered = PortfolioGreeksReport(
        lines=report.lines,
        total=Greeks(
            delta=report.total.delta + 1.0,  # deliberately wrong
            gamma=report.total.gamma,
            vega=report.total.vega,
            theta=report.total.theta,
            rho=report.total.rho,
        ),
        as_of=report.as_of,
    )
    assert verify_reconciliation(tampered) is False


def _position(position_id: str, quantity: float) -> Position:
    market = MarketSnapshot(as_of=date(2026, 1, 1), spot=100.0, risk_free_rate=0.03, volatility=0.2)
    option = EuropeanOption(strike=100.0, maturity=1.0, option_type="call")
    return Position(
        position_id=position_id,
        instrument=option,
        quantity=quantity,
        entry_snapshot=market,
        entry_price=10.0,
    )


def test_greeks_from_position_book_reads_quantities_from_the_book() -> None:
    book = PositionBook(positions=(_position("A", 2.0), _position("B", -3.0)))
    per_unit = {"A": _greeks(delta=0.5), "B": _greeks(delta=0.5)}

    report = greeks_from_position_book(book, per_unit, date(2026, 1, 1))
    assert report.total.delta == pytest.approx(2.0 * 0.5 + (-3.0) * 0.5)
    assert {line.position_id for line in report.lines} == {"A", "B"}


def test_greeks_from_position_book_rejects_missing_per_unit_greeks() -> None:
    book = PositionBook(positions=(_position("A", 2.0), _position("B", -3.0)))
    with pytest.raises(ValueError, match="B"):
        greeks_from_position_book(book, {"A": _greeks()}, date(2026, 1, 1))


def test_aggregation_genuinely_works_across_different_pricing_models() -> None:
    """The design goal stated in the module's own docstring, exercised
    directly: one line's per-unit Greeks come from Black-Scholes,
    another from Heston, another from Merton -- this module never looks
    at which model produced a Greeks object, it only scales and sums."""
    market = MarketSnapshot(as_of=date(2026, 1, 1), spot=100.0, risk_free_rate=0.03, volatility=0.2)
    option = EuropeanOption(strike=100.0, maturity=1.0, option_type="call")

    from prometheus.stochastica.heston import HestonParams
    from prometheus.stochastica.jump_diffusion import MertonJumpParams

    bs_g = black_scholes_greeks(market, option)
    heston_g = heston_finite_difference_greeks(
        market, option, HestonParams(mu=0.03, kappa=1.5, theta=0.04, xi=0.3, rho=-0.6, v0=0.045)
    )
    merton_params = MertonJumpParams(
        mu=0.03, sigma=0.2, jump_intensity=0.75, jump_mean=-0.1, jump_std=0.25
    )
    merton_g = merton_finite_difference_greeks(market, option, merton_params)

    lines = [
        LineGreeks(position_id="bs_line", quantity=1.0, per_unit=bs_g),
        LineGreeks(position_id="heston_line", quantity=2.0, per_unit=heston_g),
        LineGreeks(position_id="merton_line", quantity=-1.0, per_unit=merton_g),
    ]
    report = aggregate_portfolio_greeks(lines, date(2026, 1, 1))
    expected_delta = 1.0 * bs_g.delta + 2.0 * heston_g.delta + (-1.0) * merton_g.delta
    assert report.total.delta == pytest.approx(expected_delta)
    assert verify_reconciliation(report) is True
