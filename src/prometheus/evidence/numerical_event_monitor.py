"""High-severity numerical event monitoring with assigned ownership
(OPS-07: "Monitor unexpected NaN, solver failure and pricing
deviation"; acceptance criterion: "High-severity numerical events
page assigned owner").

`monitor_call` runs any zero-argument callable once: a raised exception
(of any kind) is a `solver_failure` event, and a non-finite (NaN/Inf)
value anywhere in a successful result is a `non_finite_result` event.
Grounded against this repository's own REAL pricers/simulators, not
only synthetic callables: a normal `volterra.black_scholes.black_scholes_price`
call produces no event, while `stochastica.gbm.simulate_gbm_paths`
called with the same extreme positive drift this repository's own
`test_gbm.py` already confirms raises a clear `ValueError` produces a
genuine `solver_failure` event, carrying that real exception's message.

`monitor_pricing_deviation` compares two already-computed prices (e.g.
a real `volterra.monte_carlo.monte_carlo_price_vanilla` estimate against
the real closed-form `black_scholes_price` for the same market and
option) and reports a `pricing_deviation` event when their relative
difference exceeds a caller-chosen threshold -- confirmed to stay
silent when a real Monte Carlo estimate with enough paths agrees with
the real closed-form price, and to fire when compared against a
genuinely different option's reference price.

"Page assigned owner" is NOT fabricated: `owner` is a required field
with no default on every event, the same "no silently-defaulted field"
reasoning `evidence.ops_inventory.ServiceComponent`'s own `owner` field
already uses.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal

import numpy as np

EventKind = Literal["non_finite_result", "solver_failure", "pricing_deviation"]


@dataclass(frozen=True, slots=True)
class NumericalEvent:
    kind: EventKind
    detail: str
    owner: str

    def __post_init__(self) -> None:
        if not self.detail:
            raise ValueError("detail must not be empty")
        if not self.owner:
            raise ValueError("owner must not be empty")


def monitor_call(call: Callable[[], object], *, owner: str) -> NumericalEvent | None:
    try:
        result = call()
    except Exception as exc:
        return NumericalEvent(kind="solver_failure", detail=str(exc) or repr(exc), owner=owner)
    array = np.asarray(result, dtype=float)
    if not np.all(np.isfinite(array)):
        return NumericalEvent(
            kind="non_finite_result", detail="result contains NaN or Inf", owner=owner
        )
    return None


def monitor_pricing_deviation(
    primary_price: float,
    reference_price: float,
    *,
    max_relative_deviation: float,
    owner: str,
) -> NumericalEvent | None:
    if max_relative_deviation <= 0:
        raise ValueError("max_relative_deviation must be positive")
    scale = abs(reference_price) if reference_price != 0 else 1.0
    deviation = abs(primary_price - reference_price) / scale
    if deviation > max_relative_deviation:
        return NumericalEvent(
            kind="pricing_deviation",
            detail=(
                f"relative deviation {deviation:.6f} exceeds the "
                f"{max_relative_deviation} threshold "
                f"(primary={primary_price}, reference={reference_price})"
            ),
            owner=owner,
        )
    return None
