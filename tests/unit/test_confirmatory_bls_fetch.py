"""The BLS fetch tool: hermetic (a canned response, no network) and careful about what it prints.

The tool exists so that the protocol's untouched data can be acquired and locked without anyone
reading the values, so the tests pin three properties: the parse is strict, a locked file can
never be overwritten, and nothing returned for display contains a level.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from prometheus.confirmatory import __main__ as cli
from prometheus.confirmatory import bls_fetch
from prometheus.confirmatory.bls_fetch import BlsFetchError, fetch_series, write_locked
from prometheus.confirmatory.e2_inflation import parse_new_levels

_LEVELS = {
    f"{2022 + (i // 12)}-{i % 12 + 1:02d}": f"{300.0 + i * 0.7311:.3f}" for i in range(15)
}  # 2022-01 .. 2023-03


def _response(
    points: dict[str, str] | None = None, extra: list[dict[str, Any]] | None = None
) -> bytes:
    data = [
        {"year": m[:4], "period": f"M{int(m[5:]):02d}", "periodName": "x", "value": v}
        for m, v in sorted(
            (_LEVELS if points is None else points).items(), reverse=True
        )  # BLS lists newest first
    ]
    data += extra or []
    document = {
        "status": "REQUEST_SUCCEEDED",
        "message": [],
        "Results": {"series": [{"seriesID": "CUSR0000SA0", "data": data}]},
    }
    return json.dumps(document).encode()


class _Poster:
    def __init__(self, body: bytes) -> None:
        self.body, self.calls = body, []  # type: ignore[var-annotated]

    def post_json(self, url: str, payload: dict[str, Any]) -> bytes:
        self.calls.append((url, payload))
        return self.body


def test_the_request_and_the_parse() -> None:
    body = _response(extra=[{"year": "2022", "period": "M13", "value": "999.9"}])
    poster = _Poster(body)
    series = fetch_series("CUSR0000SA0", 2022, 2023, poster)
    assert poster.calls == [
        (
            "https://api.bls.gov/publicAPI/v1/timeseries/data/",
            {"seriesid": ["CUSR0000SA0"], "startyear": "2022", "endyear": "2023"},
        )
    ]
    assert series.months[0] == "2022-01" and series.months[-1] == "2023-03"
    assert len(series.months) == 15  # the annual average (M13) is not a monthly level
    assert series.levels == tuple(_LEVELS[m] for m in series.months)  # strings kept verbatim
    assert series.raw_sha256 == hashlib.sha256(body).hexdigest()


@pytest.mark.parametrize(
    ("body", "message"),
    [
        (b"not json", "not JSON"),
        (
            json.dumps({"status": "REQUEST_NOT_PROCESSED", "message": ["daily limit"]}).encode(),
            "daily limit",
        ),
        (
            json.dumps({"status": "REQUEST_SUCCEEDED", "Results": {"series": []}}).encode(),
            "no data for series",
        ),
        (_response({"2022-01": "300.0", "2022-03": "301.0"}), "not consecutive"),
        (_response({"2022-01": "300.0", "2022-02": "-1"}), "positive finite"),
        (_response({"2022-01": "300.0", "2022-02": "nan"}), "positive finite"),
        (_response({"2022-01": "300.0", "2022-02": "abc"}), "not a number"),
        (_response({"2022-01": "-", "2022-02": "-"}), "no monthly levels"),
        (_response({}), "no monthly levels"),
    ],
)
def test_a_response_that_cannot_be_trusted_is_refused(body: bytes, message: str) -> None:
    with pytest.raises(BlsFetchError, match=message):
        fetch_series("CUSR0000SA0", 2022, 2023, _Poster(body))


def test_a_month_listed_twice_is_refused() -> None:
    extra = [{"year": "2022", "period": "M01", "value": "300.5"}]
    with pytest.raises(BlsFetchError, match="twice"):
        fetch_series("CUSR0000SA0", 2022, 2023, _Poster(_response(extra=extra)))


@pytest.mark.parametrize(
    ("series_id", "start", "end"),
    [
        ("CU/../x", 2022, 2023),
        ("CUSR0000SA0", 2023, 2022),
        ("CUSR0000SA0", 2010, 2026),
        ("CUSR0000SA0", 1900, 1901),
    ],
)
def test_a_request_the_endpoint_cannot_serve_is_refused_before_any_call(
    series_id: str, start: int, end: int
) -> None:
    poster = _Poster(_response())
    with pytest.raises(BlsFetchError):
        fetch_series(series_id, start, end, poster)
    assert poster.calls == []


def test_a_locked_file_round_trips_through_the_e2_loader_and_is_write_once(tmp_path: Path) -> None:
    series = fetch_series("CUSR0000SA0", 2022, 2023, _Poster(_response()))
    out = tmp_path / "locked" / "cpi.csv"
    fixed = datetime(2026, 11, 24, 12, 0, tzinfo=UTC)
    meta = write_locked(series, out, now=lambda: fixed)

    content = out.read_bytes()
    assert meta["csv_sha256"] == hashlib.sha256(content).hexdigest()
    assert meta["retrieved_at_utc"] == "2026-11-24T12:00:00+00:00"
    assert (meta["first_month"], meta["last_month"], meta["n_months"]) == ("2022-01", "2023-03", 15)
    assert "public domain" in meta["license"] and "vintage" in meta["vintage_note"]
    assert json.loads(out.with_suffix(".meta.json").read_text()) == meta
    months, levels = parse_new_levels(content, meta["csv_sha256"])
    assert len(months) == 15 and levels[0] == pytest.approx(float(_LEVELS["2022-01"]))

    with pytest.raises(BlsFetchError, match="write-once"):
        write_locked(series, out)
    assert out.read_bytes() == content  # untouched by the refused second write


def test_nothing_returned_for_display_contains_a_level(tmp_path: Path) -> None:
    series = fetch_series("CUSR0000SA0", 2022, 2023, _Poster(_response()))
    meta = write_locked(series, tmp_path / "cpi.csv")
    shown = json.dumps(meta)
    for level in _LEVELS.values():
        assert level not in shown


def test_the_command_locks_a_series_and_prints_only_labels_and_digests(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    monkeypatch.setattr(bls_fetch, "UrllibPoster", lambda: _Poster(_response()))
    out = tmp_path / "cpi.csv"
    code = cli.main(["fetch-cpi", "--start-year", "2022", "--end-year", "2023", "--out", str(out)])
    assert code == 0 and out.exists()
    shown = capsys.readouterr().out
    assert json.loads(shown)["n_months"] == 15
    for level in _LEVELS.values():
        assert level not in shown
    again = cli.main(["fetch-cpi", "--start-year", "2022", "--end-year", "2023", "--out", str(out)])
    assert again == 2 and "write-once" in capsys.readouterr().err


def test_a_month_bls_published_no_value_for_is_a_listed_gap_not_an_error(tmp_path: Path) -> None:
    points = dict(_LEVELS)
    points["2022-08"] = "-"  # as for October 2025: no index was published
    series = fetch_series("CUSR0000SA0", 2022, 2023, _Poster(_response(points)))
    assert series.missing_months == ("2022-08",)
    assert len(series.months) == 15 and series.levels[7] == ""
    meta = write_locked(series, tmp_path / "gap.csv")
    assert (
        meta["missing_months"] == ["2022-08"] and "published no index level" in meta["missing_note"]
    )
    rows = (tmp_path / "gap.csv").read_text().splitlines()
    assert rows[8] == "2022-08,"  # a blank level, in its place
    months, levels = parse_new_levels((tmp_path / "gap.csv").read_bytes(), meta["csv_sha256"])
    assert len(months) == 15 and bool(np.isnan(levels[7]))
