"""Position book and snapshot-linked valuation (RISK-01), with stale-
snapshot rejection (RISK-13): a `Position` records what was originally
entered (a `EuropeanOption`, `ForwardContract` or `AmericanOption`, a
signed quantity, the `MarketSnapshot` it was entered against, and the
per-unit entry price); valuing it later requires the caller to supply a
CURRENT instrument (today's remaining maturity) and a current snapshot --
this module never invents its own day-count convention to decay maturity
from calendar dates, matching how every other scenario in this
repository (multi_step_run.py's own `remaining_years` recomputation)
already handles time-to-maturity decay explicitly, not implicitly.

Pricing an `AmericanOption` position needs a binomial-tree step count
that the two closed-form instruments don't: `value_position`/`value_book`
take an optional `n_steps`, required (and rejected with a clear error,
not a confusing one from deep inside the pricer) exactly when the
instrument being priced is an `AmericanOption`, ignored otherwise.

Two independent flavors of "stale" are rejected, not just one:

  - Structural/temporal: a current snapshot dated before the position's
    own entry snapshot is nonsensical (you cannot mark a position to
    market using data from before it existed) and is always rejected.
  - Freshness tolerance (optional): when a caller supplies `as_of` and
    `max_staleness_days`, a current snapshot older than that tolerance,
    relative to `as_of`, is rejected too -- the caller decides what
    "fresh enough" means for their own risk purpose; this module enforces
    whatever tolerance is given, rather than picking one itself.

A current instrument must be the SAME kind as the position's original
one (an `EuropeanOption` position cannot be repriced as a forward, or
vice versa) and must match its identifying terms exactly -- strike and
option type for an option, delivery price for a forward -- only
remaining maturity may differ. Repricing a position as if it were a
different contract is rejected, not silently allowed.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date

from prometheus.volterra.american_options import american_binomial_price
from prometheus.volterra.black_scholes import black_scholes_price
from prometheus.volterra.forwards import forward_contract_value
from prometheus.volterra.instruments import AmericanOption, EuropeanOption, ForwardContract
from prometheus.volterra.market import MarketSnapshot

Instrument = EuropeanOption | ForwardContract | AmericanOption


class PositionError(Exception):
    """Base class for position/valuation errors."""


class StaleSnapshotError(PositionError):
    pass


class InstrumentMismatchError(PositionError):
    pass


def _price(snapshot: MarketSnapshot, instrument: Instrument, n_steps: int | None) -> float:
    if isinstance(instrument, EuropeanOption):
        return black_scholes_price(snapshot, instrument)
    if isinstance(instrument, AmericanOption):
        if n_steps is None:
            raise ValueError("n_steps is required to price an AmericanOption position")
        return american_binomial_price(snapshot, instrument, n_steps)
    return forward_contract_value(snapshot, instrument)


def _identifying_terms_match(current: Instrument, original: Instrument) -> bool:
    if type(current) is not type(original):
        return False
    if isinstance(current, (EuropeanOption, AmericanOption)):
        assert isinstance(original, (EuropeanOption, AmericanOption))
        return (current.strike, current.option_type) == (original.strike, original.option_type)
    assert isinstance(current, ForwardContract) and isinstance(original, ForwardContract)
    return current.delivery_price == original.delivery_price


@dataclass(frozen=True, slots=True)
class Position:
    position_id: str
    instrument: Instrument
    quantity: float
    entry_snapshot: MarketSnapshot
    entry_price: float

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
        if (
            isinstance(self.entry_price, bool)
            or not isinstance(self.entry_price, (int, float))
            or not math.isfinite(self.entry_price)
            or self.entry_price < 0
        ):
            raise ValueError("entry_price must be finite and non-negative")


@dataclass(frozen=True, slots=True)
class PositionValuation:
    position_id: str
    mark_price: float
    market_value: float
    unrealized_pnl: float
    as_of: date


def value_position(
    position: Position,
    current_instrument: Instrument,
    current_snapshot: MarketSnapshot,
    *,
    as_of: date | None = None,
    max_staleness_days: int | None = None,
    n_steps: int | None = None,
) -> PositionValuation:
    if not _identifying_terms_match(current_instrument, position.instrument):
        raise InstrumentMismatchError(
            f"current_instrument ({current_instrument!r}) does not match position "
            f"{position.position_id!r}'s original contract ({position.instrument!r})"
        )
    if current_instrument.maturity > position.instrument.maturity:
        raise ValueError(
            "current_instrument's remaining maturity cannot exceed the position's "
            "original maturity -- time cannot run backward"
        )
    if current_snapshot.as_of < position.entry_snapshot.as_of:
        raise StaleSnapshotError(
            f"current snapshot ({current_snapshot.as_of}) precedes position "
            f"{position.position_id!r}'s own entry snapshot ({position.entry_snapshot.as_of})"
        )
    if as_of is not None and max_staleness_days is not None:
        staleness_days = (as_of - current_snapshot.as_of).days
        if staleness_days < 0:
            raise ValueError("current_snapshot cannot be dated after as_of")
        if staleness_days > max_staleness_days:
            raise StaleSnapshotError(
                f"current snapshot is {staleness_days} days old as of {as_of}, "
                f"exceeding the {max_staleness_days}-day staleness tolerance"
            )

    mark_price = _price(current_snapshot, current_instrument, n_steps)
    market_value = position.quantity * mark_price
    unrealized_pnl = position.quantity * (mark_price - position.entry_price)
    return PositionValuation(
        position_id=position.position_id,
        mark_price=mark_price,
        market_value=market_value,
        unrealized_pnl=unrealized_pnl,
        as_of=current_snapshot.as_of,
    )


@dataclass(frozen=True, slots=True)
class PositionBook:
    positions: tuple[Position, ...]

    def __post_init__(self) -> None:
        if not self.positions:
            raise ValueError("a position book must hold at least one position")
        ids = [p.position_id for p in self.positions]
        if len(set(ids)) != len(ids):
            raise ValueError("positions must have distinct position_ids")


def value_book(
    book: PositionBook,
    current_instruments: Mapping[str, Instrument],
    current_snapshot: MarketSnapshot,
    *,
    as_of: date | None = None,
    max_staleness_days: int | None = None,
    n_steps: int | None = None,
) -> tuple[PositionValuation, ...]:
    valuations = []
    for position in book.positions:
        if position.position_id not in current_instruments:
            raise ValueError(f"missing current instrument for position {position.position_id!r}")
        valuations.append(
            value_position(
                position,
                current_instruments[position.position_id],
                current_snapshot,
                as_of=as_of,
                max_staleness_days=max_staleness_days,
                n_steps=n_steps,
            )
        )
    return tuple(valuations)


def total_market_value(valuations: Sequence[PositionValuation]) -> float:
    return sum(v.market_value for v in valuations)


def total_unrealized_pnl(valuations: Sequence[PositionValuation]) -> float:
    return sum(v.unrealized_pnl for v in valuations)
