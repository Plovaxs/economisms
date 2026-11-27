"""The FDIC bank snapshot: the parsing rules on small fakes, and the committed numbers against
well-known history (the 2009 charge-off peak, the 2008 and 2023 failures)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from prometheus.data_ingestion.fdic_banks import (
    ANNUAL_COLUMNS,
    FAILURES_COLUMNS,
    FdicError,
    failures_annual,
    fetch_failures,
    fetch_national_summary,
    load_bank_annual,
    load_failures_annual,
    national_annual,
    refresh,
    to_csv,
)
from prometheus.data_ingestion.transport import HttpResponse


class _Fake:
    def __init__(self, bodies: dict[str, bytes], status: int = 200) -> None:
        self.bodies, self.status, self.calls = bodies, status, []

    def get(self, url: str, params: dict[str, str]) -> HttpResponse:
        self.calls.append((url, params))
        return HttpResponse(status_code=self.status, body=self.bodies[url.rsplit("/", 1)[1]])


def _envelope(rows: list[dict[str, object]], total: int | None = None) -> bytes:
    return json.dumps(
        {
            "meta": {"total": len(rows) if total is None else total},
            "data": [{"data": r} for r in rows],
        }
    ).encode()


def _summary_row(year: int, kind: str, **values: float) -> dict[str, object]:
    base = {
        "STNAME": "All States and Territories",
        "YEAR": str(year),
        "CB_SI": kind,
        "BANKS": 10,
        "ASSET": 100,
        "LNLS": 60,
        "SC": 20,
        "CHBAL": 8,
        "DEP": 85,
        "EQ": 9,
        "NTLNLS": 1,
        "NETINC": 1,
        "INTINC": 5,
        "EINTEXP": 2,
        "NIM": 3,
        "NCLNLS": 2,
    }
    return {**base, **values}


def test_national_rows_add_commercial_banks_and_savings_institutions() -> None:
    rows = [
        _summary_row(1990, "CB"),
        _summary_row(1990, "SI", ASSET=50, LNLS=30),
        {**_summary_row(1990, "CB"), "STNAME": "Ohio", "ASSET": 7},  # a state row is ignored
    ]
    (out,) = national_annual(rows)
    assert out["date"] == "1990-12-31"
    assert out["assets"] == 150 and out["loans"] == 90 and out["banks"] == 20


def test_a_field_reported_as_zero_for_the_whole_year_is_stored_blank() -> None:
    (out,) = national_annual([_summary_row(1950, "CB", EQ=0, NCLNLS=0)])
    assert out["equity"] is None and out["noncurrent_loans"] is None
    assert out["assets"] == 100  # a real number stays


def test_a_year_without_a_commercial_bank_row_is_refused() -> None:
    with pytest.raises(FdicError, match="commercial-bank"):
        national_annual([_summary_row(1990, "SI")])
    with pytest.raises(FdicError, match="no national rows"):
        national_annual([{**_summary_row(1990, "CB"), "STNAME": "Ohio"}])


def test_failures_are_counted_per_year_with_assistance_apart_and_the_partial_year_cut() -> None:
    rows = [
        {"FAILYR": "1990", "RESTYPE": "FAILURE", "QBFASSET": 10, "QBFDEP": 8},
        {"FAILYR": "1990", "RESTYPE": "FAILURE", "QBFASSET": 5, "QBFDEP": 4},
        {"FAILYR": "1990", "RESTYPE": "ASSISTANCE", "QBFASSET": 1000, "QBFDEP": 900},
        {"FAILYR": "1992", "RESTYPE": "FAILURE", "QBFASSET": 7, "QBFDEP": None},
        {"FAILYR": "2030", "RESTYPE": "FAILURE", "QBFASSET": 99, "QBFDEP": 99},
    ]
    out = {r["date"][:4]: r for r in failures_annual(rows, 1992)}
    assert out["1990"]["failures"] == 2 and out["1990"]["failed_assets"] == 15
    assert out["1990"]["assistance_transactions"] == 1 and out["1990"]["assisted_assets"] == 1000
    assert out["1991"]["failures"] == 0 and out["1992"]["failed_deposits"] == 0
    assert "2030" not in out and min(out) == "1934"
    with pytest.raises(FdicError, match="resolution type"):
        failures_annual([{"FAILYR": "1990", "RESTYPE": "MERGER", "QBFASSET": 1}], 1990)


def test_a_response_that_disagrees_with_its_own_total_is_refused() -> None:
    fake = _Fake({"summary": _envelope([_summary_row(1990, "CB")], total=5)})
    with pytest.raises(FdicError, match="reports 5 rows"):
        fetch_national_summary(fake)
    with pytest.raises(FdicError, match="unexpected"):
        fetch_failures(_Fake({"failures": b"not json"}))
    with pytest.raises(FdicError, match="HTTP 503"):
        fetch_failures(_Fake({"failures": b""}, status=503))


def test_refresh_writes_both_snapshots_with_metadata(tmp_path: Path) -> None:
    fake = _Fake(
        {
            "summary": _envelope([_summary_row(1990, "CB"), _summary_row(1991, "CB", EQ=0)]),
            "failures": _envelope(
                [{"FAILYR": "1991", "RESTYPE": "FAILURE", "QBFASSET": 5, "QBFDEP": 4}]
            ),
        }
    )
    written = refresh(tmp_path, fake, "2026-01-01")
    assert {p.name for p in written} == {
        "fdic_bank_annual.csv",
        "fdic_bank_annual.meta.json",
        "fdic_bank_failures_annual.csv",
        "fdic_bank_failures_annual.meta.json",
    }
    annual = (tmp_path / "fdic_bank_annual.csv").read_text().splitlines()
    assert annual[0].split(",") == list(ANNUAL_COLUMNS) and len(annual) == 3
    assert annual[2].split(",")[ANNUAL_COLUMNS.index("equity")] == ""  # blank, not zero
    meta = json.loads((tmp_path / "fdic_bank_annual.meta.json").read_text())
    assert (
        meta["license"].startswith("US Government work") and meta["downloaded_at"] == "2026-01-01"
    )
    # the failures file stops at the last year of the summary, not at the last failure
    last = (tmp_path / "fdic_bank_failures_annual.csv").read_text().splitlines()[-1]
    assert last.startswith("1991-12-31")


def test_csv_writer_renders_none_as_blank() -> None:
    assert to_csv([{"a": 1, "b": None}], ("a", "b")) == "a,b\n1,\n"


# --- the committed snapshots ---


def test_committed_annual_snapshot_matches_known_banking_history() -> None:
    annual = load_bank_annual()
    assert min(annual) == 1934 and max(annual) >= 2023
    assert annual[1950]["equity"] is None and annual[1983]["equity"] is None
    assert annual[1984]["equity"] is not None
    nco = {y: annual[y]["net_charge_offs"] / annual[y]["loans"] for y in annual if y >= 1984}
    assert max(nco, key=nco.__getitem__) in (2009, 2010)  # the charge-off peak of the crisis
    assert 0.024 < nco[2009] < 0.028
    equity = {y: annual[y]["equity"] / annual[y]["assets"] for y in annual if y >= 1984}
    assert 0.045 < min(equity.values()) and max(equity.values()) < 0.125
    assert 12e9 < annual[2008]["assets"] < 15e9  # about 13.8 trillion dollars, in thousands


def test_committed_failures_snapshot_matches_known_failures() -> None:
    failures = load_failures_annual()
    assert set(failures[2008]) == set(FAILURES_COLUMNS) - {"date"}
    assert failures[1989]["failures"] > 400 and failures[2009]["failures"] > 100
    assert failures[2023]["failed_assets"] > 4e8  # SVB, First Republic and Signature, in thousands
    assert failures[2008]["failed_assets"] > 3.5e8  # Washington Mutual
    assert failures[1999]["failures"] < 10
    annual = load_bank_annual()
    assert max(failures) == max(annual)  # both stop at the last complete year
