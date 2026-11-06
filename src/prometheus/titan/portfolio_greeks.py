"""Portfolio-level Greeks aggregation (PRI-10: "Implement portfolio-level
repricing and Greeks aggregation" -- "Sum of line-level Greeks reconciles
to portfolio totals").

`titan.positions` already handles portfolio-level REPRICING (RISK-01):
`value_book`/`total_market_value` sum signed market values across a
`PositionBook`. What it does not do is Greeks aggregation, and its
`Instrument` union covers only 3 of this repository's now 6 pricers with
Greeks (`EuropeanOption`/Black-Scholes, `AmericanOption`, and
`ForwardContract` has none to aggregate) -- Heston, Merton, barrier and
geometric-Asian options (PR-058) are not part of that union.

Rather than redesign `Position`/`Instrument` to carry each model's own
extra parameters (Heston needs `HestonParams`, Merton needs
`MertonJumpParams`, neither of which `Position` has anywhere to put) and
risk the existing, already-tested repricing path, this module is
deliberately decoupled: it aggregates whatever PER-UNIT `Greeks` the
caller supplies for each position, computed via whichever pricer-
specific Greeks function actually applies (`black_scholes_greeks`,
`heston_finite_difference_greeks`, `merton_finite_difference_greeks`,
`barrier_finite_difference_greeks`, `geometric_asian_finite_difference_
greeks`, or `american_binomial_greeks`) -- the choice of pricer is the
caller's, not this module's. This works for any CURRENT or FUTURE
pricer with a `Greeks` output, not just the 3 `titan.positions` already
knows how to reprice.

`greeks_from_position_book` is the connective-tissue convenience: it
reads quantities directly from an existing `PositionBook` (no
duplicated position bookkeeping), paired with a caller-supplied mapping
of per-unit Greeks.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date

from prometheus.titan.positions import PositionBook
from prometheus.volterra.black_scholes import Greeks


@dataclass(frozen=True, slots=True)
class LineGreeks:
    position_id: str
    quantity: float
    per_unit: Greeks
    """The Greeks of ONE unit/contract of the instrument, in whatever
    convention that pricer's Greeks function uses (see each module's own
    docstring -- e.g. Heston's vega is `d(price)/d(v0)`, not a per-sigma
    quantity; aggregating vega across positions priced under DIFFERENT
    models only makes sense if the caller is aware of this)."""

    def __post_init__(self) -> None:
        if not isinstance(self.position_id, str) or not self.position_id:
            raise ValueError("position_id must be non-empty text")
        if (
            isinstance(self.quantity, bool)
            or not isinstance(self.quantity, (int, float))
            or not math.isfinite(self.quantity)
            or self.quantity == 0
        ):
            raise ValueError("quantity must be a finite, non-zero number")

    @property
    def scaled(self) -> Greeks:
        """This line's quantity-scaled contribution to the portfolio."""
        return Greeks(
            delta=self.quantity * self.per_unit.delta,
            gamma=self.quantity * self.per_unit.gamma,
            vega=self.quantity * self.per_unit.vega,
            theta=self.quantity * self.per_unit.theta,
            rho=self.quantity * self.per_unit.rho,
        )


@dataclass(frozen=True, slots=True)
class PortfolioGreeksReport:
    lines: tuple[LineGreeks, ...]
    total: Greeks
    as_of: date


def aggregate_portfolio_greeks(lines: Sequence[LineGreeks], as_of: date) -> PortfolioGreeksReport:
    if not lines:
        raise ValueError("at least one line is required to aggregate a portfolio")
    ids = [line.position_id for line in lines]
    if len(set(ids)) != len(ids):
        raise ValueError("lines must have distinct position_ids")

    scaled = [line.scaled for line in lines]
    total = Greeks(
        delta=sum(g.delta for g in scaled),
        gamma=sum(g.gamma for g in scaled),
        vega=sum(g.vega for g in scaled),
        theta=sum(g.theta for g in scaled),
        rho=sum(g.rho for g in scaled),
    )
    return PortfolioGreeksReport(lines=tuple(lines), total=total, as_of=as_of)


def verify_reconciliation(report: PortfolioGreeksReport, abs_tol: float = 1e-9) -> bool:
    """Independently re-derives each total field from the report's own
    `lines` (a SEPARATE summation from whatever produced `report.total`,
    even though today that happens to be the same code path in
    `aggregate_portfolio_greeks`) and confirms they match -- the literal
    PRI-10 acceptance criterion, checked explicitly rather than assumed
    true by construction, so a future refactor that mutates `total`
    without updating `lines` (or vice versa) is caught."""
    recombined = Greeks(
        delta=sum(line.scaled.delta for line in report.lines),
        gamma=sum(line.scaled.gamma for line in report.lines),
        vega=sum(line.scaled.vega for line in report.lines),
        theta=sum(line.scaled.theta for line in report.lines),
        rho=sum(line.scaled.rho for line in report.lines),
    )
    return all(
        math.isclose(getattr(recombined, field), getattr(report.total, field), abs_tol=abs_tol)
        for field in ("delta", "gamma", "vega", "theta", "rho")
    )


def greeks_from_position_book(
    book: PositionBook, per_unit_greeks: Mapping[str, Greeks], as_of: date
) -> PortfolioGreeksReport:
    """Reads quantities from an existing `PositionBook` rather than
    duplicating position bookkeeping; `per_unit_greeks` must cover every
    position in `book` (checked explicitly -- a silently-skipped position
    would under-report portfolio risk)."""
    missing = {p.position_id for p in book.positions} - set(per_unit_greeks)
    if missing:
        raise ValueError(f"missing per-unit Greeks for position(s): {sorted(missing)}")
    lines = [
        LineGreeks(
            position_id=position.position_id,
            quantity=position.quantity,
            per_unit=per_unit_greeks[position.position_id],
        )
        for position in book.positions
    ]
    return aggregate_portfolio_greeks(lines, as_of)
