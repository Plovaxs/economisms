"""The confirmatory command line: what it refuses before the freeze, and that it wires the pieces.

The point of the guard is order: an untouched-data command must say no BEFORE it reads the data file
or trains anything, so the refusal tests hand it a file that does not exist and a runner that fails
the test if it is ever called.
"""

from __future__ import annotations

import hashlib
import json
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from prometheus.confirmatory import __main__ as cli
from prometheus.confirmatory.intervals import bonferroni_confidence

_FROZEN = """# Protocol

## Freeze record

| Field | Value |
| --- | --- |
| Freeze date | 2026-12-01 |
| Freeze commit | 82dfee7 |
| Recipe hash, `rl_hedge` | abc123 |
| External anchor (registry or DOI) | OSF, https://osf.io/xxxxx |
"""


def _frozen(tmp_path: Path) -> Path:
    path = tmp_path / "frozen.md"
    path.write_text(_FROZEN, encoding="utf-8")
    return path


def _unfrozen(tmp_path: Path) -> Path:
    path = tmp_path / "unfrozen.md"
    path.write_text(
        _FROZEN.replace("2026-12-01", "not frozen").replace("82dfee7", "not frozen"),
        encoding="utf-8",
    )
    return path


def _must_not_run(*_args: Any, **_kwargs: Any) -> Any:
    raise AssertionError("an untouched-data analysis ran before the protocol was frozen")


def test_a_reserved_seed_run_is_refused_before_anything_trains(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    monkeypatch.setattr(cli.e1_hedging, "run_e1", _must_not_run)
    assert cli.main(["--protocol", str(_unfrozen(tmp_path)), "e1", "--seeds", "10000-10049"]) == 2
    err = capsys.readouterr().err
    assert err.startswith("refused:") and "not frozen" in err


@pytest.mark.parametrize("command", ["e2", "e3"])
def test_untouched_data_commands_are_refused_before_the_file_is_read(
    command: str, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code = cli.main(
        [
            "--protocol", str(_unfrozen(tmp_path)), command,
            "--new", str(tmp_path / "does-not-exist.csv"),
            "--new-sha256", "0" * 64,
            "--scored-from", "2023-05-04",
        ]
    )  # fmt: skip
    assert code == 2
    assert "refused:" in capsys.readouterr().err  # not a FileNotFoundError: it never got that far


def test_old_seeds_need_no_freeze_and_use_the_protocols_interval_level(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    calls: list[tuple[list[int], float]] = []

    def fake(seeds: list[int], *, confidence: float, **_kw: Any) -> dict[str, Any]:
        calls.append((list(seeds), confidence))
        return {"endpoint": "E1", "stub": True}

    monkeypatch.setattr(cli.e1_hedging, "run_e1", fake)
    out = tmp_path / "e1.json"
    assert (
        cli.main(
            ["--protocol", str(_unfrozen(tmp_path)), "--output", str(out), "e1", "--seeds", "0-2"]
        )
        == 0
    )
    assert calls == [([0, 1, 2], bonferroni_confidence())]
    assert json.loads(capsys.readouterr().out) == {"endpoint": "E1", "stub": True}
    assert json.loads(out.read_text()) == {"endpoint": "E1", "stub": True}


@pytest.mark.parametrize(
    ("text", "expected"), [("5", [5]), ("1,4,9", [1, 4, 9]), ("3-6", [3, 4, 5, 6])]
)
def test_seed_lists_parse(text: str, expected: list[int]) -> None:
    assert cli._parse_seeds(text) == expected


def test_a_frozen_protocol_runs_e2_end_to_end_on_the_committed_series_plus_new_months(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    months = [f"2023-{m:02d}" for m in range(4, 13)] + [f"2024-{m:02d}" for m in range(1, 6)]
    level, rows = 301.808, []
    for i, month in enumerate(months):
        level *= 1.0 + 0.002 + 0.001 * (i % 3)
        rows.append(f"{month},{level:.3f}")
    content = ("month,level\n" + "\n".join(rows) + "\n").encode()
    new = tmp_path / "cpi_new.csv"
    new.write_bytes(content)
    code = cli.main(
        [
            "--protocol", str(_frozen(tmp_path)), "e2",
            "--new", str(new), "--new-sha256", hashlib.sha256(content).hexdigest(),
            "--scored-from", "2023-04-30",
        ]
    )  # fmt: skip
    assert code == 0
    report = json.loads(capsys.readouterr().out)
    assert report["endpoint"] == "E2" and report["n_months"] == 14
    assert report["first_month"] == "2023-04-30" and report["last_month"] == "2024-05-31"
    assert report["interval"]["confidence"] == pytest.approx(bonferroni_confidence())
    assert report["outcome"] in {"better", "worse", "equivalent", "inconclusive"}
    assert set(report["sensitivity"]) == {"6", "12"}


def test_a_file_that_does_not_match_its_stated_hash_is_refused(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    new = tmp_path / "cpi_new.csv"
    new.write_bytes(b"month,level\n2023-04,301.9\n")
    code = cli.main(
        [
            "--protocol", str(_frozen(tmp_path)), "e2",
            "--new", str(new), "--new-sha256", "0" * 64,
            "--scored-from", "2023-04-30",
        ]
    )  # fmt: skip
    assert code == 2
    assert "does not match the SHA-256 stated" in capsys.readouterr().err


def test_a_frozen_protocol_runs_e3_end_to_end_on_the_committed_series_plus_new_days(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    rng = np.random.default_rng(11)
    days = [date(2023, 5, 4) + timedelta(days=i) for i in range(40)]
    prices = 4090.75 * np.exp(np.cumsum(rng.normal(0.0, 0.01, size=40)))
    rows = [f"{d.isoformat()},{p:.2f}" for d, p in zip(days, prices, strict=True)]
    content = ("date,close\n" + "\n".join(rows) + "\n").encode()
    new = tmp_path / "px_new.csv"
    new.write_bytes(content)
    code = cli.main(
        [
            "--protocol", str(_frozen(tmp_path)), "e3",
            "--new", str(new), "--new-sha256", hashlib.sha256(content).hexdigest(),
            "--scored-from", "2023-05-04",
        ]
    )  # fmt: skip
    assert code == 0
    report = json.loads(capsys.readouterr().out)
    assert report["endpoint"] == "E3" and report["n_days"] == 40
    cell = report["coverage"]["alpha_0.99"]["garch_fhs"]
    assert cell["rate_interval_confidence"] == pytest.approx(bonferroni_confidence())


@pytest.mark.parametrize(("all_match", "code"), [(True, 0), (False, 1)])
def test_reproduce_exits_nonzero_when_a_documented_number_is_not_reproduced(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], all_match: bool, code: int
) -> None:
    seen: list[bool] = []

    def fake(*, include_e1: bool = True, **_kw: Any) -> dict[str, Any]:
        seen.append(include_e1)
        return {"all_checks_match": all_match, "n_checks": 1}

    monkeypatch.setattr(cli, "reproduce", fake)
    assert cli.main(["reproduce", "--skip-e1"]) == code
    assert seen == [False]
    assert json.loads(capsys.readouterr().out)["all_checks_match"] is all_match
