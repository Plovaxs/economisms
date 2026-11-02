from dataclasses import FrozenInstanceError

import pytest

from prometheus.core.money import CurrencyMismatchError, Money


def test_addition_and_subtraction() -> None:
    a = Money(500, "USD")
    b = Money(300, "USD")
    assert a + b == Money(800, "USD")
    assert a - b == Money(200, "USD")


def test_negative_amounts_allowed_as_values() -> None:
    assert Money(-100, "USD").is_negative()
    assert not Money(100, "USD").is_negative()
    assert Money(0, "USD").is_zero()


def test_currency_mismatch_on_add_raises() -> None:
    with pytest.raises(CurrencyMismatchError):
        Money(100, "USD") + Money(100, "EUR")


def test_currency_mismatch_on_comparison_raises() -> None:
    with pytest.raises(CurrencyMismatchError):
        _ = Money(100, "USD") < Money(100, "EUR")


def test_ordering_within_same_currency() -> None:
    assert Money(100, "USD") < Money(200, "USD")
    assert Money(200, "USD") > Money(100, "USD")
    assert Money(100, "USD") <= Money(100, "USD")


def test_float_rejected_no_cent_drift() -> None:
    with pytest.raises(TypeError):
        Money(1.5, "USD")  # type: ignore[arg-type]


def test_bool_rejected_as_minor_units() -> None:
    with pytest.raises(TypeError):
        Money(True, "USD")  # type: ignore[arg-type]


def test_multiplication_by_int_scalar() -> None:
    assert Money(100, "USD") * 3 == Money(300, "USD")


def test_multiplication_by_float_rejected() -> None:
    with pytest.raises(TypeError):
        Money(100, "USD") * 1.5  # type: ignore[arg-type]


def test_is_immutable() -> None:
    m = Money(100, "USD")
    with pytest.raises(FrozenInstanceError):
        m.minor_units = 200  # type: ignore[misc]


def test_zero_classmethod() -> None:
    assert Money.zero("EUR") == Money(0, "EUR")


def test_empty_currency_rejected() -> None:
    with pytest.raises(ValueError):
        Money(100, "")
