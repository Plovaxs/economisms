"""The freeze guard: untouched data and reserved seeds stay unread until the protocol is frozen.

`docs/CONFIRMATORY_PROTOCOL.md` ends with a freeze record: a table whose values read `not frozen`
(or `none`) until the maintainer completes the freeze checklist. The commands that would read
untouched observations call `require_frozen` first, so running them early is an error and not a
quiet loss of the data the protocol exists to protect.

What this is not: a security control or a proof of anything. The record is a text table the
maintainer edits; anyone who can edit it can fill it in. It stops an accident (a run before the
freeze, by the maintainer or by an assistant), not a deliberate bypass. The protocol's step 4,
anchoring the tag outside GitHub's editable history, is what makes a freeze checkable by others.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from datetime import date
from pathlib import Path

PROTOCOL_PATH = Path(__file__).resolve().parents[3] / "docs" / "CONFIRMATORY_PROTOCOL.md"
RESERVED_SEEDS = range(10_000, 10_050)
"""E1's fresh seeds. No earlier run in this repository uses a seed this large."""
E4_RESERVED_SEEDS = range(20_000, 20_010)
"""E4's seeds, kept for the frozen run so exploratory runs (seeds 0-9) cannot use them up."""

_SECTION = "## Freeze record"
_UNFILLED = {"", "not frozen", "none", "tbd", "todo", "n/a", "-"}
_COMMIT = re.compile(r"[0-9a-f]{7,40}")


class NotFrozenError(RuntimeError):
    """The protocol's freeze record is incomplete, so untouched data must not be read."""


def read_freeze_record(path: Path = PROTOCOL_PATH) -> dict[str, str]:
    """The two-column table under `## Freeze record`, as `{field: value}` (header row excluded)."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise NotFrozenError(f"cannot read the protocol at {path}: {exc.strerror or exc}") from exc
    start = text.find(_SECTION)
    if start < 0:
        raise NotFrozenError(f"{path.name} has no '{_SECTION}' section")
    record: dict[str, str] = {}
    for line in text[start + len(_SECTION) :].splitlines():
        if line.startswith("## "):
            break
        if not line.startswith("|"):
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if len(cells) != 2 or set(cells[0]) <= {"-", " ", ":"} or cells[0].lower() == "field":
            continue
        record[cells[0]] = cells[1]
    return record


def _problems(record: dict[str, str]) -> Iterable[str]:
    if not record:
        yield "the freeze record is empty"
        return
    for field, value in record.items():
        if value.strip().strip("`").lower() in _UNFILLED:
            yield f"'{field}' is not filled in (it says {value!r})"
    for field, value in record.items():
        cleaned = value.strip().strip("`")
        if field.lower().startswith("freeze date") and cleaned.lower() not in _UNFILLED:
            try:
                date.fromisoformat(cleaned)
            except ValueError:
                yield f"'{field}' must be an ISO date (YYYY-MM-DD), not {value!r}"
        if field.lower().startswith("freeze commit") and cleaned.lower() not in _UNFILLED:
            if not _COMMIT.fullmatch(cleaned.lower()):
                yield f"'{field}' must be a hexadecimal commit id, not {value!r}"


def require_frozen(path: Path = PROTOCOL_PATH) -> dict[str, str]:
    """Return the freeze record if every field is filled in; otherwise raise `NotFrozenError`
    naming what is missing."""
    record = read_freeze_record(path)
    problems = list(_problems(record))
    if problems:
        raise NotFrozenError(
            "the confirmatory protocol is not frozen, so untouched data and reserved seeds "
            "must not be read yet: "
            + "; ".join(problems)
            + f". Complete the freeze checklist in {path.name} first."
        )
    return record


def require_seeds_allowed(seeds: Iterable[int], path: Path = PROTOCOL_PATH) -> None:
    """A run that includes any reserved seed needs a frozen protocol; other seeds never do."""
    if any(seed in RESERVED_SEEDS or seed in E4_RESERVED_SEEDS for seed in seeds):
        require_frozen(path)
