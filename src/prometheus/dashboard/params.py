"""Strict, bounded query-parameter parsing for the dashboard.

Every numeric parameter used to go straight through a bare `int()` /
`float()` with no range at all, and the result was handed to a model or a
numpy allocation: `?n=100000000000` on `/dashboard/portfolio-risk` asked
numpy for an 800 GB array, `?max_epochs=1000000` on
`/dashboard/inflationcast` asked for a training run that would not finish,
a non-numeric value raised an unhandled `ValueError`, and a non-ASCII query
raised an unhandled `UnicodeDecodeError`. Nothing about the caller needed to
be unusual: a read-only token was enough.

Here every parameter has an explicit range, only plain decimal numbers
match (no `nan`, `inf`, `1_000`, `0x10`, or exponents large enough to
overflow), a repeated parameter is ambiguous and refused, and every failure
is a `ParamError` carrying the HTTP status to answer with.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from urllib.parse import parse_qs

MAX_QUERY_BYTES = 2048
MAX_QUERY_FIELDS = 32
SEED_RANGE = (0, 2**32 - 1)

_INT = re.compile(r"[0-9]{1,15}")
_FLOAT = re.compile(r"[+-]?(?:[0-9]{1,15}(?:\.[0-9]{0,15})?|\.[0-9]{1,15})(?:[eE][+-]?[0-9]{1,3})?")
_TOKEN = re.compile(r"[A-Za-z0-9._:-]{0,128}")


@dataclass(frozen=True, slots=True)
class FloatRange:
    lo: float
    hi: float
    lo_open: bool = False


class ParamError(ValueError):
    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status, self.message = status, message


def parse_query(raw: bytes) -> dict[str, list[str]]:
    if len(raw) > MAX_QUERY_BYTES:
        raise ParamError(414, "query string exceeds the byte budget")
    try:
        text = raw.decode("ascii")
    except UnicodeDecodeError as exc:
        raise ParamError(400, "query string must be ASCII") from exc
    try:
        return parse_qs(
            text,
            keep_blank_values=True,
            strict_parsing=bool(text),
            max_num_fields=MAX_QUERY_FIELDS,
        )
    except ValueError as exc:
        raise ParamError(400, "malformed query string") from exc


def wants_json(raw: bytes) -> bool:
    """Whether the caller asked for `format=json`. Tolerant on purpose: it is
    only used to pick the SHAPE of an error response, so a query too broken
    to parse is answered in JSON rather than raising a second error."""
    try:
        return parse_qs(raw.decode("ascii")).get("format", [""])[0] == "json"
    except (UnicodeDecodeError, ValueError):
        return True


def _single(query: dict[str, list[str]], name: str) -> str | None:
    values = query.get(name)
    if values is None:
        return None
    if len(values) != 1:
        raise ParamError(400, f"{name} must be given at most once")
    return values[0]


def int_param(query: dict[str, list[str]], name: str, default: int, *, lo: int, hi: int) -> int:
    text = _single(query, name)
    if text is None:
        return default
    if _INT.fullmatch(text) is None or not lo <= int(text) <= hi:
        raise ParamError(400, f"{name} must be an integer between {lo} and {hi}")
    return int(text)


def float_param(
    query: dict[str, list[str]], name: str, default: float, bounds: FloatRange
) -> float:
    text = _single(query, name)
    if text is None:
        return default
    ok = _FLOAT.fullmatch(text) is not None
    value = float(text) if ok else math.nan
    ok = (
        ok
        and math.isfinite(value)
        and value <= bounds.hi
        and (value > bounds.lo if bounds.lo_open else value >= bounds.lo)
    )
    if not ok:
        low = f"greater than {bounds.lo}" if bounds.lo_open else f"at least {bounds.lo}"
        raise ParamError(400, f"{name} must be a number {low} and at most {bounds.hi}")
    return value


def token_param(query: dict[str, list[str]], name: str, default: str = "") -> str:
    text = _single(query, name)
    if text is None:
        return default
    if _TOKEN.fullmatch(text) is None:
        raise ParamError(
            400, f"{name} must be at most 128 letters, digits or the characters . _ : -"
        )
    return text
