"""Shared numeric-input validation (VAL-13: "perform NaN/Inf injection
and solver fail-closed tests... no invalid output promoted or silently
cached").

An ordinary bounds check like `if x <= 0: raise ValueError(...)` silently
admits NaN: every comparison involving NaN (`<=`, `<`, `>`, `>=`, `==`)
evaluates to False under IEEE754, so `nan <= 0` is False and the check
passes a NaN straight through. The same input then propagates silently
through downstream arithmetic (`math.log`, `math.exp`, ... all return
NaN for a NaN argument without raising) to a silently NaN output, with
no error anywhere -- confirmed directly: constructing a `MarketSnapshot`
with `spot=float("nan")` raised nothing before this module existed.
`require_finite` closes that gap explicitly, as the first check in a
dataclass's `__post_init__`, before any sign/range check that would
otherwise let a NaN or Inf field through unnoticed.
"""

from __future__ import annotations

import math


def require_finite(**fields: float) -> None:
    """Raises ValueError naming the first NaN or Inf field found, in the
    order given."""
    for name, value in fields.items():
        if not math.isfinite(value):
            raise ValueError(f"{name} must be finite, got {value}")
