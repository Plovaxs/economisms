"""Third-party license inventory (GOV-09: "identify third-party
intellectual property and attribution needs"; acceptance criterion:
"license inventory and notices approved by maintainer").

`direct_dependency_names` parses the real `[project.dependencies]` and
`[project.optional-dependencies]` tables out of this repository's own
`pyproject.toml` with `tomllib` (standard library, Python 3.11+) --
the actual declared dependency list, not a hand-maintained duplicate that
could silently drift out of sync with what the project actually depends
on. A PEP 508 requirement string (e.g. `"numpy>=1.26"`) is reduced to its
bare distribution name by taking everything before the first version/
marker/extras delimiter.

`collect_license_inventory` then queries `importlib.metadata` for each
name's REAL, installed package metadata -- `License-Expression` (the
modern PEP 639 SPDX identifier, e.g. `"MIT"`, `"BSD-3-Clause"`) when
present, falling back to any `Classifier: License :: ...` entries,
falling back to the raw legacy `License:` metadata field truncated to a
reportable length -- never invented. A dependency installed in this exact
environment with NO resolvable license signal at all is reported as
`license_expression=None` rather than silently omitted, so a reviewer
sees every dependency was actually checked, not just the ones that had an
easy answer.

This introspects THIS environment's actually-installed packages (matching
`uv.lock`'s pinned resolution) -- it makes no network call and depends on
nothing beyond the standard library plus whatever is already installed,
so it is as hermetic and deterministic as the rest of this repository's
test suite.
"""

from __future__ import annotations

import re
import tomllib
from dataclasses import dataclass
from importlib import metadata
from pathlib import Path

_NAME_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*")


def _bare_name(requirement: str) -> str:
    match = _NAME_PATTERN.match(requirement.strip())
    if not match:
        raise ValueError(f"cannot parse a distribution name from requirement {requirement!r}")
    return match.group(0)


def direct_dependency_names(pyproject_path: Path) -> tuple[str, ...]:
    data = tomllib.loads(pyproject_path.read_text(encoding="utf-8"))
    project = data["project"]
    names = [_bare_name(req) for req in project.get("dependencies", [])]
    for extra_requirements in project.get("optional-dependencies", {}).values():
        names.extend(_bare_name(req) for req in extra_requirements)
    # stable, de-duplicated order
    seen: dict[str, None] = {}
    for name in names:
        seen.setdefault(name, None)
    return tuple(seen)


class LicenseExpressionError(ValueError):
    """An SPDX license expression that cannot be parsed."""


_SPDX_TOKEN = re.compile(r"\s*(\(|\)|[A-Za-z0-9][A-Za-z0-9.+-]*)")
_STRONG_COPYLEFT = ("GPL", "AGPL")


def _tokens(expression: str) -> list[str]:
    tokens, position = [], 0
    while position < len(expression.rstrip()):
        match = _SPDX_TOKEN.match(expression, position)
        if match is None:
            raise LicenseExpressionError(f"cannot read {expression[position:]!r}")
        tokens.append(match.group(1))
        position = match.end()
    if not tokens:
        raise LicenseExpressionError("empty license expression")
    return tokens


def allows_mit_project(expression: str) -> bool:
    """Whether an SPDX `License-Expression` can be satisfied without strong copyleft.

    `A OR B` is satisfiable if either side is (the licensee chooses), `A AND B` only if both are,
    and an identifier is acceptable unless it is GPL or AGPL (any version, with or without an
    exception: a linking exception does not make a program GPL-free). **LGPL is acceptable** --
    that is the file-level, dynamic-linking weak copyleft this project has always said it
    permits -- and the reason a substring test for "GPL" cannot be used: "LGPL-3.0-only" contains
    it. The grammar is SPDX's: `AND` binds tighter than `OR`, `WITH` attaches an exception, and
    parentheses group. As SPDX 2.3 requires, the operators are matched in upper case only
    (identifiers are case-insensitive): that is what stops an informal "GPLv2 or later" being read
    as the expression "GPLv2 OR later" -- an alternative called `later` -- and waved through.
    Raises `LicenseExpressionError` rather than guessing at a malformed expression.
    """
    tokens = _tokens(expression)
    position = 0

    def peek() -> str | None:
        return tokens[position] if position < len(tokens) else None

    def take() -> str:
        nonlocal position
        lexeme = tokens[position]
        position += 1
        return lexeme

    def disjunction() -> bool:
        result = conjunction()
        while peek() == "OR":
            take()
            result = conjunction() or result  # evaluate both sides: a malformed tail must raise
        return result

    def conjunction() -> bool:
        result = atom()
        while peek() == "AND":
            take()
            result = atom() and result
        return result

    def atom() -> bool:
        if position >= len(tokens):
            raise LicenseExpressionError("the expression ends where a license was expected")
        lexeme = take()
        if lexeme == "(":
            inner = disjunction()
            if peek() != ")":
                raise LicenseExpressionError("missing closing parenthesis")
            take()
            return inner
        if lexeme == ")" or lexeme in ("AND", "OR", "WITH"):
            raise LicenseExpressionError(f"unexpected {lexeme!r}")
        if peek() == "WITH":
            take()
            if position >= len(tokens) or tokens[position] in ("(", ")"):
                raise LicenseExpressionError("WITH needs an exception identifier")
            take()
        return not lexeme.upper().startswith(_STRONG_COPYLEFT)

    verdict = disjunction()
    if position != len(tokens):
        raise LicenseExpressionError(f"unexpected {tokens[position]!r}")
    return verdict


@dataclass(frozen=True, slots=True)
class DependencyLicense:
    name: str
    installed_version: str | None
    license_expression: str | None
    license_classifiers: tuple[str, ...]
    license_field: str | None = None
    """The legacy `License:` header, when it is a short single line (a few packages, PySide6
    among them, publish their SPDX expression only there). A multi-line license *text*, an empty
    value or `UNKNOWN` is not reported, so nothing here is a truncated paragraph of legal prose."""


MAX_LEGACY_LICENSE_CHARS = 200


def _legacy_license_field(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text or "\n" in text or len(text) > MAX_LEGACY_LICENSE_CHARS:
        return None
    return None if text.upper() in ("UNKNOWN", "NONE") else text


def collect_license_inventory(names: tuple[str, ...]) -> tuple[DependencyLicense, ...]:
    results = []
    for name in names:
        try:
            meta = metadata.metadata(name)
        except metadata.PackageNotFoundError:
            results.append(
                DependencyLicense(
                    name=name,
                    installed_version=None,
                    license_expression=None,
                    license_classifiers=(),
                )
            )
            continue
        classifiers = tuple(
            value.rsplit("::", 1)[-1].strip()
            for value in meta.get_all("Classifier") or ()
            if "License" in value
        )
        license_expressions = meta.get_all("License-Expression") or ()
        results.append(
            DependencyLicense(
                name=name,
                installed_version=meta["Version"],
                license_expression=license_expressions[0] if license_expressions else None,
                license_classifiers=classifiers,
                license_field=_legacy_license_field((meta.get_all("License") or [None])[0]),
            )
        )
    return tuple(results)
