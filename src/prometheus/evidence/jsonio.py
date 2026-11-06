"""Strict JSON decoding shared by artifact readers and snapshot normalization."""

from __future__ import annotations

import json
import math
from typing import Any, NoReturn


def _reject_constant(value: str) -> NoReturn:
    raise ValueError(f"non-finite JSON constant is not supported: {value}")


def _finite_float(value: str) -> float:
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"non-finite JSON number is not supported: {value}")
    return result


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise ValueError(f"duplicate JSON key is not supported: {key}")
        value[key] = item
    return value


def strict_json_loads(content: str) -> Any:
    return json.loads(
        content,
        parse_constant=_reject_constant,
        parse_float=_finite_float,
        object_pairs_hook=_unique_object,
    )
