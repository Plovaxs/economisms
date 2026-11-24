"""The freeze guard: untouched data and reserved seeds stay unread until the protocol is frozen.

The guard reads the protocol's own freeze record, so these tests run against the REAL file (which
must say "not frozen" until the maintainer freezes it) and against temporary copies in every state
a maintainer could leave it in.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from prometheus.confirmatory.freeze import (
    PROTOCOL_PATH,
    RESERVED_SEEDS,
    NotFrozenError,
    read_freeze_record,
    require_frozen,
    require_seeds_allowed,
)

_TEMPLATE = """# Protocol

## Freeze checklist

1. Something | with a pipe

## Freeze record

| Field | Value |
| --- | --- |
| Freeze date | {date} |
| Freeze commit | {commit} |
| Recipe hash, `rl_hedge` | {recipe} |
| External anchor (registry or DOI) | {anchor} |

## Deviation log

| Date | What changed |
| --- | --- |
| none | |
"""


def _protocol(
    tmp_path: Path,
    *,
    date: str = "2026-12-01",
    commit: str = "82dfee7",
    recipe: str = "`abc123`",
    anchor: str = "OSF, https://osf.io/xxxxx",
) -> Path:
    path = tmp_path / "protocol.md"
    path.write_text(
        _TEMPLATE.format(date=date, commit=commit, recipe=recipe, anchor=anchor), encoding="utf-8"
    )
    return path


def _unfrozen(tmp_path: Path) -> Path:
    return _protocol(
        tmp_path, date="not frozen", commit="not frozen", recipe="not frozen", anchor="none"
    )


def test_the_real_protocol_has_a_freeze_record_the_guard_can_read() -> None:
    """True before and after the freeze: the table exists, and the guard's verdict is consistent
    with what the table says."""
    record = read_freeze_record(PROTOCOL_PATH)
    assert set(record) >= {"Freeze date", "Freeze commit", "External anchor (registry or DOI)"}
    try:
        returned = require_frozen(PROTOCOL_PATH)
    except NotFrozenError as exc:
        assert "not frozen" in str(exc)
    else:
        assert returned == record


def test_an_unfrozen_record_blocks_the_run_and_names_every_missing_field(tmp_path: Path) -> None:
    with pytest.raises(NotFrozenError, match="not frozen") as caught:
        require_frozen(_unfrozen(tmp_path))
    message = str(caught.value)
    for field in ("Freeze date", "Freeze commit", "Recipe hash", "External anchor"):
        assert field in message


def test_a_complete_record_is_accepted(tmp_path: Path) -> None:
    record = require_frozen(_protocol(tmp_path))
    assert record["Freeze commit"] == "82dfee7"
    assert record["Freeze date"] == "2026-12-01"


@pytest.mark.parametrize(
    ("field", "value", "fragment"),
    [
        ("date", "not frozen", "Freeze date"),
        ("commit", "not frozen", "Freeze commit"),
        ("recipe", "TBD", "Recipe hash"),
        ("anchor", "none", "External anchor"),
        ("anchor", "", "External anchor"),
        ("date", "24 November 2026", "ISO date"),
        ("commit", "not-a-hash", "hexadecimal commit id"),
        ("commit", "82dfee", "hexadecimal commit id"),
    ],
)
def test_every_unfilled_or_malformed_field_blocks_the_run(
    tmp_path: Path, field: str, value: str, fragment: str
) -> None:
    path = _protocol(tmp_path, **{field: value})
    with pytest.raises(NotFrozenError, match=fragment):
        require_frozen(path)


def test_a_protocol_with_no_freeze_record_blocks_the_run(tmp_path: Path) -> None:
    path = tmp_path / "protocol.md"
    path.write_text("# Protocol\n\nNothing here.\n", encoding="utf-8")
    with pytest.raises(NotFrozenError, match="no '## Freeze record' section"):
        require_frozen(path)


def test_a_protocol_that_cannot_be_read_blocks_the_run_instead_of_crashing(tmp_path: Path) -> None:
    with pytest.raises(NotFrozenError, match="cannot read the protocol"):
        require_frozen(tmp_path / "missing.md")


def test_only_the_freeze_record_table_is_read_not_the_deviation_log(tmp_path: Path) -> None:
    record = read_freeze_record(_protocol(tmp_path))
    assert "Date" not in record and "none" not in record


def test_the_reserved_seeds_are_a_hundred_large_seeds_no_earlier_run_used() -> None:
    assert RESERVED_SEEDS == range(10_000, 10_050)


def test_old_seeds_never_need_a_freeze_but_reserved_ones_do(tmp_path: Path) -> None:
    unfrozen = _unfrozen(tmp_path)
    require_seeds_allowed(range(8), unfrozen)
    require_seeds_allowed([10_050], unfrozen)
    for seeds in ([10_000], [10_049], [3, 10_020], range(9_999, 10_001)):
        with pytest.raises(NotFrozenError):
            require_seeds_allowed(seeds, unfrozen)
    frozen_dir = tmp_path / "frozen"
    frozen_dir.mkdir()
    require_seeds_allowed([10_000, 10_049], _protocol(frozen_dir))
