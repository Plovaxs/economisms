import json
from dataclasses import asdict
from datetime import date
from pathlib import Path

import pytest

from prometheus.orchestration.inflationcast_run import (
    DEFAULT_CPI_CSV_PATH,
    DEFAULT_MACRO_CSV_PATH,
    InflationcastRunConfig,
    main,
    run_inflationcast_job,
)


def _write_small_fixtures(tmp_path: Path) -> tuple[Path, Path]:
    """A small, clearly SYNTHETIC pair of CSVs -- enough months to
    exercise a chronological 3-way split -- never presented as real
    data."""
    cpi_path = tmp_path / "small_cpi.csv"
    macro_path = tmp_path / "small_macro.csv"
    cpi_rows = ["date,CPI_U_INDEX_NSA,CPI_YOY"]
    macro_rows = ["date,GDP_YOY,CLAIMS_YOY,FEDFUNDS,M2_YOY,NASDAQ_YOY"]
    year, month = 1999, 1
    for i in range(48):
        cpi_rows.append(f"{year}-{month:02d}-01,{200.0 + i},{2.0 + 0.05 * (i % 10)}")
        macro_rows.append(
            f"{year}{month:02d},{2.0 + 0.1 * (i % 5)},{3.0 - 0.2 * i},5.0,6.0,{1.0 * ((i % 7) - 3)}"
        )
        month += 1
        if month > 12:
            month = 1
            year += 1
    cpi_path.write_text("\n".join(cpi_rows) + "\n")
    macro_path.write_text("\n".join(macro_rows) + "\n")
    return cpi_path, macro_path


def test_default_csv_paths_point_at_the_committed_real_snapshots() -> None:
    assert DEFAULT_CPI_CSV_PATH.name == "us_cpi_monthly.csv"
    assert DEFAULT_CPI_CSV_PATH.exists()
    assert DEFAULT_MACRO_CSV_PATH.name == "kaggle_us_macro_monthly.csv"
    assert DEFAULT_MACRO_CSV_PATH.exists()


def test_main_runs_fully_offline_against_the_real_committed_snapshots(tmp_path, capsys) -> None:
    """The actual demo-day invocation: no arguments beyond defaults,
    no network call of any kind, reading the real committed BLS CPI
    series and Kaggle-sourced macro snapshot directly."""
    output_path = tmp_path / "report.json"
    exit_code = main(["--output", str(output_path), "--bootstrap-resamples", "200"])
    assert exit_code == 0

    saved = json.loads(output_path.read_text())
    printed = json.loads(capsys.readouterr().out)
    assert printed == saved
    assert saved["data_source"] == "bls_public_api_and_kaggle_local_snapshot"
    assert saved["verdict"] in {"gru_better", "classical_better", "inconclusive"}
    assert saved["run_manifest"]["model_id"] == "inflationcast-gru-v1"
    assert set(saved["models"]) == {
        "naive_persistence", "linear_regression", "classical_matched_mlp",
        "hybrid_quantum", "gru",
    }
    assert "gru_calibration" in saved
    assert "gru_calibration_temperature" in saved
    assert "gru_calibration_after_temperature" in saved
    assert "gru_vs_best_classical" in saved


def test_main_runs_against_small_synthetic_fixtures(tmp_path, capsys) -> None:
    cpi_path, macro_path = _write_small_fixtures(tmp_path)
    output_path = tmp_path / "report.json"
    exit_code = main(
        [
            "--seed", "0",
            "--max-epochs", "5",
            "--patience", "3",
            "--window", "2",
            "--validation-split-date", "2000-06-01",
            "--test-split-date", "2001-06-01",
            "--bootstrap-resamples", "20",
            "--output", str(output_path),
        ],
        cpi_csv_path=cpi_path,
        macro_csv_path=macro_path,
    )
    assert exit_code == 0
    saved = json.loads(output_path.read_text())
    assert saved["data_source"] == "bls_public_api_and_kaggle_local_snapshot"


def test_main_rejects_an_invalid_date(capsys) -> None:
    with pytest.raises(SystemExit):
        main(["--validation-split-date", "not-a-date"])
    assert "invalid" in capsys.readouterr().err.lower()


def test_main_rejects_an_invalid_config_value(capsys) -> None:
    with pytest.raises(SystemExit):
        main(["--max-epochs", "0"])
    assert "max_epochs" in capsys.readouterr().err


def test_main_rejects_validation_split_date_not_before_test_split_date(capsys) -> None:
    with pytest.raises(SystemExit):
        main(["--validation-split-date", "2022-01-01", "--test-split-date", "2022-01-01"])
    assert "validation_split_date" in capsys.readouterr().err


def test_config_from_dict_round_trips_a_valid_recipe() -> None:
    config = InflationcastRunConfig(max_epochs=7, bootstrap_resamples=11)
    assert InflationcastRunConfig.from_dict(asdict(config)) == config


def test_config_from_dict_rejects_a_missing_or_extra_field() -> None:
    payload = asdict(InflationcastRunConfig())
    del payload["max_epochs"]
    with pytest.raises(ValueError, match="complete configuration fields"):
        InflationcastRunConfig.from_dict(payload)
    payload = asdict(InflationcastRunConfig())
    payload["unknown"] = 1
    with pytest.raises(ValueError, match="complete configuration fields"):
        InflationcastRunConfig.from_dict(payload)


def test_config_from_dict_decodes_string_dates() -> None:
    payload = asdict(InflationcastRunConfig())
    payload["validation_split_date"] = "2020-01-01"
    config = InflationcastRunConfig.from_dict(payload)
    assert config.validation_split_date == date(2020, 1, 1)


@pytest.mark.parametrize("seed", range(5))
def test_gru_calibration_is_robustly_bad_but_post_hoc_scaling_robustly_helps(seed: int) -> None:
    """A direct numeric sweep (80 real training runs: 8 hidden sizes x
    10 seeds, see docs/PR_LEDGER.md's PR-176 entry) found InflationGRU's
    raw miscalibration is not a seed-0 fluke or a capacity artifact --
    it rejects at every hidden size and every seed tried -- and that
    post-hoc variance temperature scaling (fit on the validation split
    alone, `fit_variance_temperature`) reliably raises observed test
    coverage without ever fully closing the gap to the 90% nominal
    target. This locks in that exact finding on the real, committed
    BLS CPI-U / Kaggle snapshot, at the production default hidden_size
    (24), across 5 of the swept seeds, rather than leaving it as a
    one-off script result."""
    config = InflationcastRunConfig(seed=seed, bootstrap_resamples=20)
    result = run_inflationcast_job(config)
    payload = result.evidence_bundle["inflationcast"]
    raw = payload["gru_calibration"]
    calibrated = payload["gru_calibration_after_temperature"]

    assert raw["p_value"] < 0.01, "raw GRU calibration should fail (this is the known finding)"
    assert calibrated["observed_coverage"] > raw["observed_coverage"], (
        "post-hoc temperature scaling should raise observed coverage relative to raw"
    )
    assert calibrated["p_value"] < 0.05, (
        "temperature scaling helps but should NOT fully fix calibration on this real, "
        "regime-shifted test split -- a passing calibration here would mean this test's "
        "own premise (a partial, not full, fix) has silently changed and needs re-checking"
    )


def test_run_inflationcast_job_produces_a_real_manifest_and_evidence_bundle() -> None:
    config = InflationcastRunConfig(max_epochs=2, patience=1, window=2, bootstrap_resamples=5)
    result = run_inflationcast_job(config)
    assert result.manifest.seed == config.seed
    payload = result.evidence_bundle["inflationcast"]
    assert payload["accounting_convention"] == "calibrated-nowcast-v1"
    assert payload["schema_version"] == 1
    assert result.evidence_bundle["run_manifest"]["result_hash"] == result.manifest.result_hash
