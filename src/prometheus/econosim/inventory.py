"""Inventory nonnegativity enforcement (LED-03: "enforce nonnegative
inventory unless specified financing exists; invalid sale or
withdrawal rejects with structured error").

`price_economy.py`'s own step logic already has a nonnegative-inventory
GUARD (`if new_inventory < 0: raise ValueError(...)`), but it is a bare
`ValueError` with no carried attributes, deeply nested inside a complex
multi-market settlement step, and -- because the goods market's supply
curve is itself capped at available inventory -- effectively
unreachable by any test that goes through normal price discovery (it
would require deliberately bypassing that capacity constraint to
trigger at all). `InventoryAccount` is a standalone, directly testable
primitive for the same invariant: nonnegative by default, with a named,
structured `InsufficientInventoryError` (carrying the available and
requested quantities, like `econosim.agents.InsufficientFundsError`
already does for cash) -- and "unless specified financing exists" is a
real, usable escape hatch, not just a clause satisfied by never
offering one: a withdrawal may dip into a NEGATIVE balance, down to
`-financing_limit`, but ONLY when the caller passes `financed=True` on
that SPECIFIC call -- an explicit, per-transaction opt-in, not an
account-wide setting a caller could forget was active.
"""

from __future__ import annotations


class InsufficientInventoryError(ValueError):
    def __init__(self, available: float, requested: float, floor: float) -> None:
        super().__init__(
            f"cannot withdraw {requested}: only {available} available "
            f"(floor {floor}, financed={floor != 0})"
        )
        self.available = available
        self.requested = requested
        self.floor = floor


class InventoryAccount:
    """A single inventory balance. `financing_limit` (>= 0, default 0 --
    no financing) is the maximum amount a FINANCED withdrawal may push
    the balance below zero; it does not, by itself, authorize anything
    -- `financed=True` must be passed explicitly on each withdrawal
    that needs to use it."""

    def __init__(self, quantity: float = 0.0, financing_limit: float = 0.0) -> None:
        if financing_limit < 0:
            raise ValueError("financing_limit must be non-negative")
        if quantity < -financing_limit:
            raise ValueError(
                f"initial quantity {quantity} is already below the financing floor "
                f"-{financing_limit}"
            )
        self.financing_limit = financing_limit
        self._quantity = quantity

    @property
    def quantity(self) -> float:
        return self._quantity

    def deposit(self, amount: float) -> None:
        if amount <= 0:
            raise ValueError("deposit amount must be positive")
        self._quantity += amount

    def withdraw(self, amount: float, *, financed: bool = False) -> None:
        """Rejects (structured `InsufficientInventoryError`) a withdrawal
        that would push the balance below zero, UNLESS `financed=True`
        is passed on this call AND the resulting balance stays at or
        above `-financing_limit`."""
        if amount <= 0:
            raise ValueError("withdrawal amount must be positive")
        floor = -self.financing_limit if financed else 0.0
        resulting = self._quantity - amount
        if resulting < floor:
            raise InsufficientInventoryError(self._quantity, amount, floor)
        self._quantity = resulting
