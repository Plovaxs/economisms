"""Deterministic integer minor-unit currency values.

Blueprint requirement LED-02: "Use deterministic integer minor units for cash
ledger -- No floating-cent drift in production ledger fixtures." Every cash
amount in the ledger is therefore an integer count of minor units (e.g. cents
for USD), never a float.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import total_ordering


class CurrencyMismatchError(ValueError):
    """Raised when an operation mixes two different currencies."""

    def __init__(self, a: str, b: str) -> None:
        super().__init__(f"currency mismatch: {a!r} vs {b!r}")
        self.a = a
        self.b = b


@total_ordering
@dataclass(frozen=True, slots=True)
class Money:
    """An exact amount of currency in integer minor units.

    Comparisons and arithmetic between different currencies raise
    CurrencyMismatchError rather than silently producing a nonsensical result.
    """

    minor_units: int
    currency: str = "USD"

    def __post_init__(self) -> None:
        if not isinstance(self.minor_units, int) or isinstance(self.minor_units, bool):
            raise TypeError(f"minor_units must be int, got {type(self.minor_units)!r}")
        if not isinstance(self.currency, str) or not self.currency:
            raise ValueError("currency must be a non-empty code")

    def _check_currency(self, other: Money) -> None:
        if self.currency != other.currency:
            raise CurrencyMismatchError(self.currency, other.currency)

    def __add__(self, other: Money) -> Money:
        self._check_currency(other)
        return Money(self.minor_units + other.minor_units, self.currency)

    def __sub__(self, other: Money) -> Money:
        self._check_currency(other)
        return Money(self.minor_units - other.minor_units, self.currency)

    def __neg__(self) -> Money:
        return Money(-self.minor_units, self.currency)

    def __mul__(self, scalar: int) -> Money:
        if not isinstance(scalar, int) or isinstance(scalar, bool):
            raise TypeError("Money can only be multiplied by an int scalar")
        return Money(self.minor_units * scalar, self.currency)

    def __lt__(self, other: Money) -> bool:
        self._check_currency(other)
        return self.minor_units < other.minor_units

    def is_zero(self) -> bool:
        return self.minor_units == 0

    def is_negative(self) -> bool:
        return self.minor_units < 0

    def is_positive(self) -> bool:
        return self.minor_units > 0

    def abs(self) -> Money:
        return Money(abs(self.minor_units), self.currency)

    @classmethod
    def zero(cls, currency: str = "USD") -> Money:
        return cls(0, currency)

    def __repr__(self) -> str:
        return f"Money({self.minor_units}, {self.currency!r})"
