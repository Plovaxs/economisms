"""HDG-07: "leverage, concentration and position constraints... all
proposed actions obey projected feasible region." A Hypothesis property
sweep confirming the literal "all" and "always obey," matching VAL-08's
own precedent (test_action_feasibility_invariants.py) for this kind of
claim: not just a few hand-picked examples, but a check over randomly
generated proposed holdings, spot prices, position/leverage limits and
capital.
"""

from __future__ import annotations

import numpy as np
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from prometheus.hedging.position_constraints import (
    PositionLimits,
    project_onto_feasible_region,
)


@given(
    proposed=st.floats(min_value=-1e4, max_value=1e4, allow_nan=False),
    spot=st.floats(min_value=0.01, max_value=1e4, allow_nan=False),
    max_position=st.floats(min_value=1e-3, max_value=1e3, allow_nan=False),
    max_leverage=st.floats(min_value=1e-3, max_value=50.0, allow_nan=False),
    capital=st.floats(min_value=1.0, max_value=1e6, allow_nan=False),
)
@settings(max_examples=300)
def test_projected_holding_always_obeys_both_bounds(
    proposed: float, spot: float, max_position: float, max_leverage: float, capital: float
) -> None:
    limits = PositionLimits(max_position=max_position, max_leverage=max_leverage, capital=capital)
    out = project_onto_feasible_region(np.array([proposed]), np.array([spot]), limits)
    assert abs(out[0]) <= max_position + 1e-6
    assert abs(out[0]) * spot <= capital * max_leverage + 1e-3


@given(
    proposed=st.floats(min_value=-1e4, max_value=1e4, allow_nan=False),
    spot=st.floats(min_value=0.01, max_value=1e4, allow_nan=False),
    max_position=st.floats(min_value=1e-3, max_value=1e3, allow_nan=False),
    max_leverage=st.floats(min_value=1e-3, max_value=50.0, allow_nan=False),
    capital=st.floats(min_value=1.0, max_value=1e6, allow_nan=False),
)
@settings(max_examples=300)
def test_an_already_feasible_holding_is_never_altered(
    proposed: float, spot: float, max_position: float, max_leverage: float, capital: float
) -> None:
    """The converse of the invariant above (mirroring VAL-08's own
    "rejection AND its converse" pattern): a holding that is already
    inside both bounds must come back unchanged, not needlessly
    tightened.

    A small relative margin keeps this test clear of the exact
    boundary: right AT either bound, the test's own float arithmetic
    (multiplication) and the production function's (division then
    clip) can legitimately round to values differing by a single ULP
    -- a real floating-point fact, not a logic bug, confirmed by a
    Hypothesis-found case where proposed == spot == max_leverage ==
    capital and the two formulas rounded 1 ULP apart. The margin
    excludes that ambiguous sliver; `pytest.approx` on the comparison
    itself is a second, independent safeguard."""
    limits = PositionLimits(max_position=max_position, max_leverage=max_leverage, capital=capital)
    margin = 1.0 - 1e-9
    within_position = abs(proposed) <= max_position * margin
    within_leverage = abs(proposed) * spot <= capital * max_leverage * margin
    already_feasible = within_position and within_leverage
    out = project_onto_feasible_region(np.array([proposed]), np.array([spot]), limits)
    if already_feasible:
        assert out[0] == pytest.approx(proposed)
