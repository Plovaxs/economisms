"""The dataset registry and the data-quality report (audit items D-01, D-06, D-08).

Two kinds of test. The committed outputs must equal what the code produces from the data now (so a
changed snapshot, or a changed rule, cannot leave stale documentation), and the checks themselves
are exercised on small synthetic files where the right answer is known. What the real data show is
pinned too: the gaps and warnings found today are listed, so a NEW one fails the test and has to be
read and acknowledged here rather than slipping in.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from prometheus.data_ingestion import dataset_registry as registry
from prometheus.data_ingestion.dataset_registry import (
    build_qa,
    build_registry,
    infer_frequency,
    parse_date,
    qa_file,
)

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data_cache"


def _csv(tmp_path: Path, rows: list[str], header: str = "date,x") -> Path:
    path = tmp_path / "t.csv"
    path.write_text("\n".join([header, *rows]) + "\n")
    return path


def test_the_committed_registry_and_qa_report_equal_what_the_code_produces_now() -> None:
    for name, build in ((registry.REGISTRY_NAME, build_registry), (registry.QA_NAME, build_qa)):
        committed = (ROOT / "docs" / "data" / name).read_text(encoding="utf-8")
        assert committed == registry._dump(build()), f"{name} is stale: run `write`"
    assert registry.main(["check"]) == 0


def test_every_snapshot_is_registered_with_the_digest_the_manifest_records() -> None:
    manifest = json.loads((DATA / "MANIFEST.sha256.json").read_text())["files"]
    entries = build_registry()["datasets"]
    assert [e["file"] for e in entries] == sorted(p.name for p in DATA.glob("*.csv"))
    for entry in entries:
        assert entry["sha256"] == manifest[entry["file"]]["sha256"]
        assert entry["rows"] > 0 and entry["first_date"] <= entry["last_date"]
        assert entry["frequency"] in {"daily", "monthly"}
        assert entry["license"] and entry["source"] and entry["source_url"], entry["file"]


def test_the_only_provenance_gap_today_is_the_french_factor_snapshot_with_no_metadata() -> None:
    """Found by the registry: `ff3_monthly_snapshot.csv` has no `.meta.json`, so its download date
    and raw-file digest are not recorded. The connector's own constants fill source and licence;
    the rest stays a flagged gap. Fixing it means recording that provenance, then removing this
    entry."""
    entries = build_registry()["datasets"]
    gaps = {e["file"]: e["registry_gaps"] for e in entries if e["registry_gaps"]}
    assert list(gaps) == ["ff3_monthly_snapshot.csv"]
    assert "no .meta.json" in gaps["ff3_monthly_snapshot.csv"][0]


def test_the_warnings_the_qa_report_finds_in_the_real_data_are_the_ones_known_today() -> None:
    report = build_qa()["files"]
    found = {name: f["warnings"] for name, f in report.items() if f["warnings"]}
    assert found == {
        "kaggle_fed_policy_monthly.csv": ["no_blank_cells"],
        "kaggle_sp500_daily_close.csv": ["no_gap_over_seven_days"],
        "kaggle_sp500_spliced_daily_close.csv": ["no_gap_over_seven_days"],
        "kaggle_term_spread_monthly.csv": ["header_matches_declared_columns"],
        "kaggle_us_macro_extended_monthly.csv": ["no_blank_cells"],
        "us_cpi_monthly.csv": ["no_blank_cells", "no_missing_months"],
    }


def test_the_missing_month_the_qa_report_finds_is_the_one_the_source_documents() -> None:
    """A gap the report finds should be a gap the metadata already explains (BLS published no index
    for 2025-10); an unexplained one would be a defect."""
    qa = build_qa()["files"]["us_cpi_monthly.csv"]["checks"]["no_missing_months"]["detail"]
    meta = json.loads((DATA / "us_cpi_monthly.meta.json").read_text())
    assert qa["missing_months"] == ["2025-10"] == list(meta["real_data_gap"])


@pytest.mark.parametrize(
    ("text", "expected"),
    [("202304", (2023, 4, 1)), ("2023-04", (2023, 4, 1)), ("2023-04-28", (2023, 4, 28))],
)
def test_the_three_date_formats_in_the_snapshots_parse(
    text: str, expected: tuple[int, int, int]
) -> None:
    assert parse_date(text).timetuple()[:3] == expected


def test_frequency_is_inferred_from_the_median_spacing() -> None:
    monthly = [parse_date(f"2020-{m:02d}") for m in range(1, 9)]
    daily = [
        parse_date("2020-01-01").fromordinal(parse_date("2020-01-01").toordinal() + i)
        for i in range(9)
    ]
    assert infer_frequency(monthly) == "monthly" and infer_frequency(daily) == "daily"
    assert infer_frequency(monthly[:2]) == "unknown"


def test_a_clean_file_has_no_warning(tmp_path: Path) -> None:
    rows = [f"2020-{m:02d},{m * 1.5}" for m in range(1, 13)]
    report = qa_file(_csv(tmp_path, rows), ["x"])
    assert report["warnings"] == [] and report["to_review"] == []
    assert (report["rows"], report["frequency"]) == (12, "monthly")


def test_each_kind_of_defect_is_reported_by_its_own_check(tmp_path: Path) -> None:
    rows = [f"2020-{m:02d},{m},{m * 2.5}" for m in range(1, 13)]
    rows[3] = "2020-04,,10.0"  # a blank
    rows[5] = "2020-06,abc,15.0"  # not a number
    del rows[8]  # a missing month
    rows.append("2020-12,12,30.0")  # a duplicate, out-of-order date at the end
    report = qa_file(_csv(tmp_path, rows, header="date,x,y"), ["x"])
    checks = report["checks"]
    assert checks["dates_strictly_increasing"]["status"] == "warn"
    assert checks["no_missing_months"]["detail"]["missing_months"] == ["2020-09"]
    assert checks["no_blank_cells"]["detail"]["blank_cells_by_column"] == {"x": 1}
    assert checks["all_cells_numeric"]["detail"]["by_column"] == {"x": 1}
    assert checks["header_matches_declared_columns"]["detail"] == {
        "in_file_not_declared": ["y"],
        "declared_not_in_file": [],
    }


def test_a_constant_column_and_unparsable_dates_are_reported(tmp_path: Path) -> None:
    path = _csv(tmp_path, ["2020-01,5", "2020-02,5", "2020-03,5", "not-a-date,5"])
    checks = qa_file(path)["checks"]
    assert checks["no_constant_column"]["detail"] == {"columns": ["x"]}
    assert checks["dates_parse"]["status"] == "warn"


def test_an_outlier_is_listed_for_review_not_called_an_error(tmp_path: Path) -> None:
    values = [100.0 + (i % 5) * 0.1 for i in range(80)]
    values[40] = 400.0
    rows = [f"{1990 + i // 12}-{i % 12 + 1:02d},{v}" for i, v in enumerate(values)]
    report = qa_file(_csv(tmp_path, rows))
    check = report["checks"]["no_outlier_in_first_difference"]
    assert check["status"] == "review" and "no_outlier_in_first_difference" in report["to_review"]
    assert check["detail"]["by_column"]["x"]["points_over_threshold"] >= 1
    assert report["warnings"] == []


def test_a_daily_series_with_a_long_gap_is_flagged(tmp_path: Path) -> None:
    days = [f"2020-01-{d:02d},{100 + d}" for d in range(1, 11)] + [
        f"2020-02-{d:02d},{120 + d}" for d in range(1, 6)
    ]
    check = qa_file(_csv(tmp_path, days))["checks"]["no_gap_over_seven_days"]
    assert check["status"] == "warn" and check["detail"]["count"] == 1


def test_the_check_command_fails_when_the_committed_outputs_are_stale(tmp_path: Path) -> None:
    (tmp_path / "out").mkdir()
    assert registry.main(["check", "--output-dir", str(tmp_path / "out")]) == 1  # nothing there yet
    assert registry.main(["write", "--output-dir", str(tmp_path / "out")]) == 0
    assert registry.main(["check", "--output-dir", str(tmp_path / "out")]) == 0
    (tmp_path / "out" / registry.QA_NAME).write_text("{}\n")
    assert registry.main(["check", "--output-dir", str(tmp_path / "out")]) == 1
