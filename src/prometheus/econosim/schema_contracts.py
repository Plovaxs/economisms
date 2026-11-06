"""Schema contracts, unit normalization and currency mapping (DAT-10:
"implement schema contracts, unit normalization and currency mapping";
acceptance criterion: "contract failures quarantined and logged").

A `SchemaContract` declares, per series, the exact unit and currency a
record must carry. `validate_against_contract` never raises on a
mismatch and never silently drops the record either -- it returns a
`QuarantinedRecord` (the reason, and the actual vs. expected values)
for the caller to log and set aside, or `None` if the record conforms.
"Quarantined," not discarded: a caller still has everything needed to
investigate and fix the source of the mismatch.

`normalize_unit` performs EXACT unit-scale conversions (e.g. USD
millions <-> USD billions, percent <-> fraction) via a fixed,
deterministic conversion table -- not currency exchange-rate
conversion, which would need live, time-varying market data this
repository does not have and will not fabricate. `map_currency_code`
similarly only maps a currency's various real-world spellings to its
ISO 4217 code (e.g. "US Dollar" -> "USD") and validates the result
against a small fixed set of codes this project recognizes; it never
converts an amount between currencies.
"""

from __future__ import annotations

from dataclasses import dataclass

_UNIT_SCALE: dict[str, float] = {
    "usd": 1.0,
    "usd thousands": 1_000.0,
    "usd millions": 1_000_000.0,
    "usd billions": 1_000_000_000.0,
    "fraction": 1.0,
    "percent": 0.01,
}

_CURRENCY_ALIASES: dict[str, str] = {
    "usd": "USD",
    "us dollar": "USD",
    "us dollars": "USD",
    "eur": "EUR",
    "euro": "EUR",
    "euros": "EUR",
    "idr": "IDR",
    "indonesian rupiah": "IDR",
}
_RECOGNIZED_CURRENCY_CODES: frozenset[str] = frozenset(_CURRENCY_ALIASES.values())


class UnrecognizedUnitError(ValueError):
    """Raised when `normalize_unit` is given a unit outside the fixed
    conversion table -- it never guesses a scale factor."""


class UnrecognizedCurrencyError(ValueError):
    """Raised when `map_currency_code` is given a spelling outside the
    fixed alias table."""


def normalize_unit(value: float, from_unit: str, to_unit: str) -> float:
    from_key, to_key = from_unit.strip().lower(), to_unit.strip().lower()
    if from_key not in _UNIT_SCALE:
        raise UnrecognizedUnitError(f"unrecognized unit {from_unit!r}")
    if to_key not in _UNIT_SCALE:
        raise UnrecognizedUnitError(f"unrecognized unit {to_unit!r}")
    return value * _UNIT_SCALE[from_key] / _UNIT_SCALE[to_key]


def map_currency_code(spelling: str) -> str:
    key = spelling.strip().lower()
    if key not in _CURRENCY_ALIASES:
        raise UnrecognizedCurrencyError(f"unrecognized currency spelling {spelling!r}")
    return _CURRENCY_ALIASES[key]


@dataclass(frozen=True, slots=True)
class SchemaContract:
    series_id: str
    expected_unit: str
    expected_currency: str | None

    def __post_init__(self) -> None:
        if not self.series_id:
            raise ValueError("series_id must not be empty")
        if not self.expected_unit:
            raise ValueError("expected_unit must not be empty")
        if self.expected_currency is not None and self.expected_currency not in (
            _RECOGNIZED_CURRENCY_CODES
        ):
            raise ValueError(
                f"expected_currency must be one of {sorted(_RECOGNIZED_CURRENCY_CODES)} or None"
            )


@dataclass(frozen=True, slots=True)
class QuarantinedRecord:
    series_id: str
    reason: str
    observed_unit: str
    observed_currency: str | None


def validate_against_contract(
    series_id: str,
    unit: str,
    currency: str | None,
    contract: SchemaContract,
) -> QuarantinedRecord | None:
    if series_id != contract.series_id:
        raise ValueError(
            f"series_id mismatch: record is {series_id!r}, contract is for "
            f"{contract.series_id!r} -- validate a record only against its own contract"
        )
    if unit != contract.expected_unit:
        return QuarantinedRecord(
            series_id=series_id,
            reason=f"unit mismatch: expected {contract.expected_unit!r}, got {unit!r}",
            observed_unit=unit,
            observed_currency=currency,
        )
    if currency != contract.expected_currency:
        return QuarantinedRecord(
            series_id=series_id,
            reason=(
                f"currency mismatch: expected {contract.expected_currency!r}, got {currency!r}"
            ),
            observed_unit=unit,
            observed_currency=currency,
        )
    return None
