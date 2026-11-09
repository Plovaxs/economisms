import json
from pathlib import Path

import pytest

from prometheus.orchestration.recessionnet_kaggle_run import DEFAULT_CSV_PATH, main


def _write_small_fixture(tmp_path: Path) -> Path:
    """A small, clearly synthetic grid -- enough months to exercise a
    chronological 3-way split, never presented as real data."""
    path = tmp_path / "small_kaggle_macro.csv"
    header = "date,GDP_YOY,CLAIMS_YOY,FEDFUNDS,M2_YOY,NASDAQ_YOY\n"
    rows = []
    year, month = 1999, 1
    for i in range(36):
        gdp, claims, nasdaq = 2.0 + 0.1 * (i % 5), 3.0 - 0.2 * i, 1.0 * ((i % 7) - 3)
        rows.append(f"{year}{month:02d},{gdp},{claims},5.0,6.0,{nasdaq}")
        month += 1
        if month > 12:
            month = 1
            year += 1
    path.write_text(header + "\n".join(rows) + "\n")
    return path


def test_default_csv_path_points_at_the_committed_real_snapshot() -> None:
    assert DEFAULT_CSV_PATH.name == "kaggle_us_macro_monthly.csv"
    assert DEFAULT_CSV_PATH.exists()


def test_main_runs_fully_offline_against_the_real_committed_snapshot(tmp_path, capsys) -> None:
    """The actual demo-day invocation: no arguments beyond defaults,
    no network call of any kind, reading the real committed Kaggle-
    sourced snapshot directly."""
    output_path = tmp_path / "report.json"
    exit_code = main(["--output", str(output_path), "--bootstrap-resamples", "200"])
    assert exit_code == 0

    saved = json.loads(output_path.read_text())
    printed = json.loads(capsys.readouterr().out)
    assert printed == saved
    assert saved["data_source"] == "kaggle_local_snapshot"
    assert saved["verdict"] in {"quantum_better", "classical_better", "inconclusive"}
    assert saved["run_manifest"]["model_id"] == "recessionnet-hybrid-quantum-v1"
    assert set(saved["models"]) == {
        "base_rate",
        "logistic_regression",
        "classical_matched_mlp",
        "hybrid_quantum",
    }
    # Locks in the real, reproducible seed=0 finding on this real dataset
    # (validation 2001-01-01, test 2008-01-01, the CLI's own defaults):
    # base rate is the strongest classical candidate here, and quantum
    # shows no significant difference against it.
    assert saved["best_classical_challenger"] == "base_rate"
    assert saved["verdict"] == "inconclusive"


def test_main_runs_against_a_small_synthetic_fixture(tmp_path, capsys) -> None:
    fixture = _write_small_fixture(tmp_path)
    output_path = tmp_path / "report.json"
    exit_code = main(
        [
            "--seed", "0",
            "--max-epochs", "5",
            "--patience", "3",
            "--window", "2",
            "--horizon", "1",
            "--validation-split-date", "2000-01-01",
            "--test-split-date", "2001-01-01",
            "--bootstrap-resamples", "20",
            "--output", str(output_path),
        ],
        csv_path=fixture,
    )
    assert exit_code == 0
    saved = json.loads(output_path.read_text())
    assert saved["data_source"] == "kaggle_local_snapshot"


def test_main_rejects_an_invalid_date(capsys) -> None:
    with pytest.raises(SystemExit):
        main(["--validation-split-date", "not-a-date"])
    assert "invalid" in capsys.readouterr().err.lower()


def test_main_rejects_an_invalid_config_value(capsys) -> None:
    with pytest.raises(SystemExit):
        main(["--max-epochs", "0"])
    assert "max_epochs" in capsys.readouterr().err
