"""MAR-03: "Implement action feasibility projection/constraint solver --
Property tests never produce prohibited spending or lending." Also
covers the matching real-construction guarantees for MAR-06 (bank
lending headroom) and MAR-07 (central-bank rate band), both of which
reuse the identical fraction-projection mechanism.

This is NEW evidence, not a restatement of `tests/property/
test_action_feasibility_invariants.py` (VAL-08): that file sweeps raw
`Money` amounts fed directly to `econosim.agents`' own methods. This
file sweeps the layer above it -- a policy's raw (adversarial, possibly
out-of-[0,1]) fraction output -- through `marl.feasibility`'s
projection, confirming the resulting `Money` amount can never even
reach the ledger's feasibility gate with an infeasible request.
"""

from __future__ import annotations

from hypothesis import given, settings
from hypothesis import strategies as st

from prometheus.core.money import Money
from prometheus.marl.feasibility import project_fraction_to_amount, project_fraction_to_headroom
from prometheus.marl.spaces import CentralBankAction

_SUPPRESS = settings(max_examples=200, deadline=None)

_adversarial_fraction = st.floats(min_value=-1_000.0, max_value=1_000.0, allow_nan=False)
_available_minor = st.integers(min_value=0, max_value=10_000_000_000)


@given(fraction=_adversarial_fraction, available_minor=_available_minor)
@_SUPPRESS
def test_projected_amount_never_exceeds_available_for_any_adversarial_fraction(
    fraction, available_minor
):
    available = Money(available_minor, "USD")
    projected = project_fraction_to_amount(fraction, available)
    assert projected.minor_units >= 0
    assert projected.minor_units <= available.minor_units


@given(fraction=_adversarial_fraction, headroom_minor=_available_minor)
@_SUPPRESS
def test_projected_loan_never_exceeds_bank_headroom_for_any_adversarial_fraction(
    fraction, headroom_minor
):
    headroom = Money(headroom_minor, "USD")
    projected = project_fraction_to_headroom(fraction, headroom)
    assert projected.minor_units >= 0
    assert projected.minor_units <= headroom.minor_units


@given(fraction=st.floats(min_value=1.0, max_value=1.0))
@_SUPPRESS
def test_a_fraction_of_exactly_one_projects_to_the_entire_available_balance(fraction):
    available = Money(12_345, "USD")
    assert project_fraction_to_amount(fraction, available) == available


@given(
    raw_rate=st.floats(min_value=-1_000.0, max_value=1_000.0, allow_nan=False),
    rate_min=st.floats(min_value=0.0, max_value=0.05, allow_nan=False),
    rate_max_offset=st.floats(min_value=0.001, max_value=0.50, allow_nan=False),
)
@_SUPPRESS
def test_central_bank_action_never_issues_a_rate_outside_its_own_configured_band(
    raw_rate, rate_min, rate_max_offset
):
    rate_max = rate_min + rate_max_offset
    action = CentralBankAction(policy_rate=raw_rate, rate_min=rate_min, rate_max=rate_max)
    assert rate_min <= action.policy_rate <= rate_max
