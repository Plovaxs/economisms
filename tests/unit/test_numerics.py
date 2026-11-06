import math

import pytest

from prometheus.numerics import require_finite


def test_accepts_all_finite_fields() -> None:
    require_finite(a=1.0, b=-2.5, c=0.0)


def test_rejects_nan() -> None:
    with pytest.raises(ValueError, match="b must be finite"):
        require_finite(a=1.0, b=float("nan"))


def test_rejects_positive_and_negative_infinity() -> None:
    with pytest.raises(ValueError, match="a must be finite"):
        require_finite(a=math.inf)
    with pytest.raises(ValueError, match="a must be finite"):
        require_finite(a=-math.inf)


def test_reports_the_first_offending_field_in_argument_order() -> None:
    with pytest.raises(ValueError, match="b must be finite"):
        require_finite(a=1.0, b=float("nan"), c=float("inf"))
