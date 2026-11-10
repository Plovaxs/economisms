"""MAR-03: "Implement action feasibility projection/constraint solver --
Property tests never produce prohibited spending or lending."

`econosim.agents`/`core.ledger` already enforce budget and leverage
feasibility structurally (confirmed and property-tested under VAL-08,
see `tests/property/test_action_feasibility_invariants.py`) -- this
module does NOT reimplement that check. What it adds, specific to MAR's
own RL action space: a PROJECTION from a raw (possibly out-of-[0,1],
e.g. straight out of an untrained network before any squashing) scalar
into a real `core.money.Money` amount that is mathematically guaranteed,
by construction, never to exceed the agent's own observed capacity --
so a policy's raw output can never even REACH the ledger's feasibility
gate with an infeasible request in the first place. `tests/property/
test_mar_action_feasibility.py` is the new evidence here: it sweeps
adversarial (including negative and far-greater-than-1) raw fractions
through these projections and confirms the resulting `Money` amount is
always `<=` the real available balance/headroom, for every input
Hypothesis generates.
"""

from __future__ import annotations

import math

from prometheus.core.money import Money


def _clip01(value: float) -> float:
    if math.isnan(value):
        return 0.0
    return min(max(value, 0.0), 1.0)


def project_fraction_to_amount(fraction: float, available: Money) -> Money:
    """`available * clip01(fraction)`, floored to a whole number of
    minor units so the result is never (even by floating-point
    rounding) a single minor unit more than `available` itself."""
    if available.minor_units < 0:
        raise ValueError("available balance must not itself be negative")
    clipped = _clip01(fraction)
    minor = math.floor(available.minor_units * clipped)
    minor = min(minor, available.minor_units)  # defensive: never exceed available even by 1
    return Money(minor, available.currency)


def project_fraction_to_headroom(fraction: float, headroom: Money) -> Money:
    """Identical mechanics to `project_fraction_to_amount`, named
    separately for `BankAction.lending_fraction` call sites so a reader
    does not have to infer "amount" means "loan size here" from context."""
    return project_fraction_to_amount(fraction, headroom)
