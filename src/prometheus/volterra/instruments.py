"""Versioned instrument specifications (PRI-01)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from prometheus.numerics import require_finite

OptionType = Literal["call", "put"]


@dataclass(frozen=True, slots=True)
class EuropeanOption:
    strike: float
    maturity: float
    option_type: OptionType

    def __post_init__(self) -> None:
        require_finite(strike=self.strike, maturity=self.maturity)
        if self.strike <= 0:
            raise ValueError("strike must be positive")
        if self.maturity <= 0:
            raise ValueError("maturity must be positive")
        if self.option_type not in ("call", "put"):
            raise ValueError(f"option_type must be 'call' or 'put', got {self.option_type!r}")


@dataclass(frozen=True, slots=True)
class ForwardContract:
    """A long forward with a fixed delivery price `delivery_price`,
    agreed at some point in the past, and `maturity` years remaining
    until delivery. See `volterra.forwards` for pricing."""

    delivery_price: float
    maturity: float

    def __post_init__(self) -> None:
        require_finite(delivery_price=self.delivery_price, maturity=self.maturity)
        if self.delivery_price <= 0:
            raise ValueError("delivery_price must be positive")
        if self.maturity <= 0:
            raise ValueError("maturity must be positive")


@dataclass(frozen=True, slots=True)
class AmericanOption:
    """Same contractual terms as `EuropeanOption`, but exercisable at any
    time up to and including maturity -- a genuinely different
    instrument (priced by a binomial tree, see `volterra.american_options`,
    not the Black-Scholes closed form), not just an alternate label on
    the same one."""

    strike: float
    maturity: float
    option_type: OptionType

    def __post_init__(self) -> None:
        require_finite(strike=self.strike, maturity=self.maturity)
        if self.strike <= 0:
            raise ValueError("strike must be positive")
        if self.maturity <= 0:
            raise ValueError("maturity must be positive")
        if self.option_type not in ("call", "put"):
            raise ValueError(f"option_type must be 'call' or 'put', got {self.option_type!r}")
