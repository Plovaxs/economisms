"""Turn a runner's typed config into an editable form, and a filled-in form back into a recipe.

The form is *derived*, never hand-written: it walks the same dataclass annotations that
`service.schema` turns into the OpenAPI document, so a field added to a runner appears here
without anyone editing this file, and a type this module cannot represent fails loudly (see
`UnsupportedFieldError` and `test_every_runner_has_a_form_that_reproduces_its_default_recipe`)
instead of silently vanishing from the window.

A form is advice, not authority. What `assemble` returns is still passed through
`orchestration.recipes.prepare_recipe` -- typed decoding plus the resource limits -- before
anything is queued, so a value this module accepts and the runner rejects is reported to the user,
never run. The checks here exist to give a precise, per-field message for the mistakes people
actually make (a letter in a number, `nan`, a date that is not a date), not to replace that gate.

Everything user-typed is parsed by an explicit, narrow grammar: `float("1_000")`, `float("nan")`,
`date.fromisoformat("20260131")` and `Fraction("1_0")` all succeed in Python, and none of them is
something a person meant to type into a research parameter.
"""

from __future__ import annotations

import functools
import json
import math
import re
import types
from collections.abc import Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass, fields, is_dataclass
from datetime import date, datetime
from fractions import Fraction
from typing import Any, Literal, Union, get_args, get_origin, get_type_hints

from prometheus.orchestration.recipes import RUNNERS, _config_class, default_recipe

FieldKind = Literal[
    "int", "float", "bool", "text", "date", "choice", "fraction", "list", "json", "group"
]
Path = tuple[str, ...]

_FALLBACKS: dict[str, Any] = {
    "int": 0,
    "float": 0.0,
    "bool": False,
    "text": "",
    "date": "2000-01-01",
    "fraction": "0",
    "list": "",
    "json": "[]",
}
_ACRONYMS = {
    "ar": "AR",
    "bps": "bps",
    "bsde": "BSDE",
    "cvar": "CVaR",
    "es": "ES",
    "gru": "GRU",
    "id": "ID",
    "ids": "IDs",
    "marl": "MARL",
    "mlp": "MLP",
    "omo": "OMO",
    "pde": "PDE",
    "pinn": "PINN",
    "rl": "RL",
    "sde": "SDE",
    "usd": "USD",
    "var": "VaR",
    "yoy": "YoY",
}

_INTEGER = re.compile(r"[+-]?[0-9]{1,18}")
_DECIMAL = re.compile(
    r"[+-]?(?:[0-9]{1,18}(?:\.[0-9]{0,18})?|\.[0-9]{1,18})(?:[eE][+-]?[0-9]{1,3})?"
)
_FRACTION = re.compile(
    r"[+-]?(?:[0-9]{1,18}/[0-9]{1,18}|[0-9]{1,18}(?:\.[0-9]{0,18})?|\.[0-9]{1,18})(?:[eE][+-]?[0-9]{1,3})?"
)
_DATE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")


class UnsupportedFieldError(TypeError):
    """A runner field has a type the form builder cannot represent."""


@dataclass(frozen=True, slots=True)
class FieldSpec:
    """One editable value (or, for `kind == "group"`, a nested object of them)."""

    key: str
    path: Path
    label: str
    kind: FieldKind
    default: Any
    """What the editor shows first. Text for `fraction`, `list` and `json`; `None` when an optional
    value starts unset."""
    fallback: Any = None
    """What an optional value shows when the user switches it on."""
    optional: bool = False
    choices: tuple[str, ...] = ()
    element: FieldKind | None = None
    children: tuple[FieldSpec, ...] = ()
    minimum: float | None = None
    maximum: float | None = None
    exclusive_minimum: bool = False
    help: str = ""


def humanize(name: str) -> str:
    """`n_train_paths` -> `Number of train paths`; `cvar_alpha` -> `CVaR alpha`."""
    words = [word for word in name.split("_") if word]
    if words[:1] == ["n"] and len(words) > 1:  # `n_paths`, but a lone `n` is just N
        words = ["number", "of", *words[1:]]
    shown = [_ACRONYMS.get(word, word) for word in words]
    if shown and shown[0] == words[0]:
        shown[0] = shown[0].capitalize()
    return " ".join(shown)


def _fraction_text(value: Any) -> str:
    if isinstance(value, Mapping):
        numerator, denominator = value["numerator"], value["denominator"]
        return str(numerator) if denominator == 1 else f"{numerator}/{denominator}"
    return str(value)


def _list_text(values: Sequence[Any]) -> str:
    return ", ".join(str(value) for value in values)


def _scalar_kind(annotation: Any) -> FieldKind | None:
    if annotation is bool:
        return "bool"
    if annotation is int:
        return "int"
    if annotation is float:
        return "float"
    if annotation is str:
        return "text"
    if annotation is date:
        return "date"
    if annotation is Fraction:
        return "fraction"
    return None


def _spec(key: str, annotation: Any, default: Any, path: Path) -> FieldSpec:
    label = humanize(key)
    origin, arguments = get_origin(annotation), get_args(annotation)
    optional = False
    if origin in (Union, types.UnionType):
        members = [member for member in arguments if member is not type(None)]
        if len(members) != 1 or len(members) == len(arguments):
            raise UnsupportedFieldError(f"{'.'.join(path)}: only `X | None` unions are supported")
        annotation, optional = members[0], True
        origin, arguments = get_origin(annotation), get_args(annotation)
    if origin is Literal:
        choices = tuple(str(choice) for choice in arguments)
        fallback = choices[0] if optional else None
        return FieldSpec(
            key,
            path,
            label,
            "choice",
            default,
            fallback=fallback,
            optional=optional,
            choices=choices,
        )
    kind = _scalar_kind(annotation)
    if kind is not None:
        shown = _fraction_text(default) if kind == "fraction" and default is not None else default
        return FieldSpec(
            key,
            path,
            label,
            kind,
            shown,
            fallback=_FALLBACKS[kind] if optional else None,
            optional=optional,
        )
    if origin is tuple and len(arguments) == 2 and arguments[1] is Ellipsis:
        element = arguments[0]
        element_kind = _scalar_kind(element)
        scalar_elements = element_kind in ("int", "float", "text")
        items = [] if default is None else list(default)
        if scalar_elements and not any("," in str(item) for item in items):
            return FieldSpec(
                key,
                path,
                label,
                "list",
                _list_text(items),
                fallback="" if optional else None,
                optional=optional,
                element=element_kind,
            )
        if scalar_elements or is_dataclass(element):
            return FieldSpec(
                key,
                path,
                label,
                "json",
                json.dumps(items, indent=2),
                fallback="[]" if optional else None,
                optional=optional,
            )
    if isinstance(annotation, type) and is_dataclass(annotation):
        children = _fields_of(annotation, default if isinstance(default, Mapping) else {}, path)
        return FieldSpec(key, path, label, "group", None, optional=optional, children=children)
    raise UnsupportedFieldError(f"{'.'.join(path)}: no form editor for {annotation!r}")


def _fields_of(cls: type, defaults: Mapping[str, Any], path: Path) -> tuple[FieldSpec, ...]:
    hints = get_type_hints(cls)
    return tuple(
        _spec(field.name, hints[field.name], defaults.get(field.name), (*path, field.name))
        for field in fields(cls)
    )


@functools.cache
def build_form(kind: str) -> tuple[FieldSpec, ...]:
    """The form for runner `kind`, with the runner's own defaults.

    The first call imports the runner module to read its config type, and that import loads torch
    (about a second and a third of a gigabyte). It is cached, and `warm_up` pays it on a
    background thread at start-up so the first click on a lab is instant.
    """
    return _fields_of(_config_class(kind), default_recipe(kind), ())


def warm_up(kinds: Iterable[str] | None = None) -> None:
    """Build every runner's form now (the whole cost is the one-time import described above)."""
    for kind in RUNNERS if kinds is None else kinds:
        build_form(kind)


def leaves(specs: Sequence[FieldSpec]) -> Iterator[FieldSpec]:
    """Every editable value, in display order, flattening groups."""
    for spec in specs:
        if spec.kind == "group":
            yield from leaves(spec.children)
        else:
            yield spec


def initial_values(specs: Sequence[FieldSpec]) -> dict[Path, Any]:
    return {spec.path: spec.default for spec in leaves(specs)}


def _editor_value(spec: FieldSpec, value: Any) -> Any:
    """A recipe value as the editor shows it (the inverse of `parse_value`)."""
    if value is None:
        return None
    if spec.kind == "fraction":
        return _fraction_text(value)
    if spec.kind == "list":
        return _list_text(value)
    if spec.kind == "json":
        return json.dumps(value, indent=2)
    return value


def values_from_config(specs: Sequence[FieldSpec], config: Mapping[str, Any]) -> dict[Path, Any]:
    """Editor values for an existing recipe (to re-run a past job with its settings). A field the
    recipe lacks keeps the form's default; a value that is not what the field expects is passed
    through as it is, and shows up as an error on the field rather than being silently dropped."""
    values: dict[Path, Any] = {}

    def walk(group: Sequence[FieldSpec], source: Mapping[str, Any]) -> None:
        for spec in group:
            present = spec.key in source
            if spec.kind == "group":
                nested = source.get(spec.key)
                walk(spec.children, nested if isinstance(nested, Mapping) else {})
            elif present:
                values[spec.path] = _editor_value(spec, source[spec.key])
            else:
                values[spec.path] = spec.default

    walk(specs, config)
    return values


def find(specs: Sequence[FieldSpec], path: Path) -> FieldSpec:
    for spec in specs:
        if spec.path == path:
            return spec
        if spec.kind == "group" and path[: len(spec.path)] == spec.path:
            return find(spec.children, path)
    raise KeyError(path)


# ---------------------------------------------------------------------------------- parsing


def _parse_int(raw: Any) -> int:
    if isinstance(raw, bool):
        raise ValueError("must be a whole number")
    if isinstance(raw, int):
        return raw
    if isinstance(raw, float) and math.isfinite(raw) and raw == int(raw):
        return int(raw)
    if isinstance(raw, str) and _INTEGER.fullmatch(raw.strip()):
        return int(raw.strip())
    raise ValueError("must be a whole number")


def _parse_float(raw: Any) -> float:
    if isinstance(raw, bool):
        raise ValueError("must be a number")
    if isinstance(raw, (int, float)):
        try:
            value = float(raw)
        except OverflowError:  # an integer too large for a double
            raise ValueError("must be a finite number") from None
    elif isinstance(raw, str) and _DECIMAL.fullmatch(raw.strip()):
        value = float(raw.strip())
    else:
        raise ValueError("must be a number")
    if not math.isfinite(value):
        raise ValueError("must be a finite number")
    return value


def _parse_date(raw: Any) -> str:
    if isinstance(raw, datetime):
        return raw.date().isoformat()
    if isinstance(raw, date):
        return raw.isoformat()
    message = "must be a calendar date like 2026-01-31"
    if not (isinstance(raw, str) and _DATE.fullmatch(raw.strip())):
        raise ValueError(message)
    try:
        return date.fromisoformat(raw.strip()).isoformat()
    except ValueError:
        raise ValueError(message) from None


def _parse_fraction(raw: Any) -> dict[str, int]:
    if isinstance(raw, Fraction):
        value = raw
    elif isinstance(raw, bool) or not isinstance(raw, (str, int, float)):
        raise ValueError("must be a number or a ratio like 3/10")
    else:
        text = str(raw).strip()
        if not _FRACTION.fullmatch(text):
            raise ValueError("must be a number or a ratio like 3/10")
        try:
            value = Fraction(text)
        except ZeroDivisionError:
            raise ValueError("the denominator of a ratio cannot be zero") from None
    return {"numerator": value.numerator, "denominator": value.denominator}


def _parse_element(kind: FieldKind | None, text: str) -> Any:
    if kind == "int":
        return _parse_int(text)
    if kind == "float":
        return _parse_float(text)
    return text


def _parse_list(spec: FieldSpec, raw: Any) -> list[Any]:
    if not isinstance(raw, str):
        raise ValueError("must be a comma-separated list")
    if not raw.strip():
        return []
    result: list[Any] = []
    for position, piece in enumerate(raw.split(","), start=1):
        try:
            result.append(_parse_element(spec.element, piece.strip()))
        except ValueError as exc:
            raise ValueError(f"item {position} {exc}") from None
    return result


def _parse_json(raw: Any) -> list[Any]:
    if not isinstance(raw, str):
        raise ValueError("must be JSON text")
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"is not valid JSON (line {exc.lineno}, column {exc.colno})") from None
    if not isinstance(value, list):
        raise ValueError("must be a JSON list")
    return value


def _check_bounds(spec: FieldSpec, value: int | float) -> None:
    if spec.minimum is not None:
        too_small = value <= spec.minimum if spec.exclusive_minimum else value < spec.minimum
        if too_small:
            word = "greater than" if spec.exclusive_minimum else "at least"
            raise ValueError(f"must be {word} {spec.minimum:g}")
    if spec.maximum is not None and value > spec.maximum:
        raise ValueError(f"must be at most {spec.maximum:g}")


def parse_value(spec: FieldSpec, raw: Any) -> Any:
    """Parse one editor value into its JSON form, or raise `ValueError` with a short message."""
    kind = spec.kind
    if kind == "int":
        value = _parse_int(raw)
        _check_bounds(spec, value)
        return value
    if kind == "float":
        number = _parse_float(raw)
        _check_bounds(spec, number)
        return number
    if kind == "bool":
        if not isinstance(raw, bool):
            raise ValueError("must be on or off")
        return raw
    if kind == "text":
        if not isinstance(raw, str):
            raise ValueError("must be text")
        return raw
    if kind == "date":
        return _parse_date(raw)
    if kind == "choice":
        if raw not in spec.choices:
            raise ValueError("must be one of: " + ", ".join(spec.choices))
        return raw
    if kind == "fraction":
        return _parse_fraction(raw)
    if kind == "list":
        return _parse_list(spec, raw)
    if kind == "json":
        return _parse_json(raw)
    raise ValueError("this field cannot be edited directly")


def assemble(
    specs: Sequence[FieldSpec], values: Mapping[Path, Any]
) -> tuple[dict[str, Any], dict[Path, str]]:
    """Build the recipe from editor values. Never raises for anything a user can type: every
    problem comes back keyed by field path so the window can mark exactly that field."""
    errors: dict[Path, str] = {}
    return _assemble(specs, values, errors), errors


def _assemble(
    specs: Sequence[FieldSpec], values: Mapping[Path, Any], errors: dict[Path, str]
) -> dict[str, Any]:
    config: dict[str, Any] = {}
    for spec in specs:
        if spec.kind == "group":
            config[spec.key] = _assemble(spec.children, values, errors)
            continue
        raw = values.get(spec.path)
        if raw is None:
            if spec.optional:
                config[spec.key] = None
            else:
                errors[spec.path] = "is required"
            continue
        try:
            config[spec.key] = parse_value(spec, raw)
        except ValueError as exc:
            errors[spec.path] = str(exc)
    return config
