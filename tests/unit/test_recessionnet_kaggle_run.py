import json
from dataclasses import asdict
from datetime import date
from pathlib import Path

import pytest

from prometheus.orchestration.recessionnet_kaggle_run import (
    DEFAULT_CSV_PATH,
    RecessionNetKaggleRunConfig,
    main,
    run_recessionnet_kaggle_job,
)


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


def test_patience_60_shows_real_signal_in_every_seed_and_no_brier_only_win() -> None:
    """PR-177, re-measured in PR-197 on the corrected grid.

    Original PR-177 finding (on the PR-145 grid, whose GDP column contained a
    point-in-time look-ahead): a 5-seed sweep at `patience=60` gave
    `hybrid_quantum` real discrimination in 4 seeds (ROC-AUC 0.86-0.92) but
    exposed a Brier-score blind spot in seed 0 -- a "quantum_better" verdict
    (CI excludes zero) with ROC-AUC 0.479, worse than random. After the look-ahead
    was removed that counter-example NO LONGER REPRODUCES: at `patience=60` every
    seed ranks genuinely (ROC-AUC 0.76-0.88), 4 of 5 seeds are `quantum_better`,
    and seed 0 is simply `inconclusive` (its Brier 0.0955 is worse than the
    base rate's 0.0743). The seed-0 "blind spot" was partly produced by the
    look-ahead, not a property of the method -- a finding that is itself recorded
    (docs/RESULTS_AND_LIMITATIONS.md Finding 13) rather than quietly dropped.
    What survives is the methodological rule: never certify a win on Brier alone
    (`test_default_patience_seed_3_...` shows the diagnostic still matters)."""
    results = []
    for seed in range(5):
        config = RecessionNetKaggleRunConfig(seed=seed, patience=60)
        result = run_recessionnet_kaggle_job(config)
        payload = result.evidence_bundle["recessionnet_kaggle"]
        hq = payload["models"]["hybrid_quantum"]
        results.append((seed, hq["roc_auc"], payload["verdict"]))

    assert all(auc > 0.7 for _, auc, _ in results), "every seed should show real discrimination"
    wins = [(seed, auc) for seed, auc, verdict in results if verdict == "quantum_better"]
    assert len(wins) >= 4
    assert all(auc > 0.55 for _, auc in wins), "no win should rest on a near-random ranking"


def test_default_patience_seed_3_inverted_ranking_is_never_certified_as_a_win() -> None:
    """On the corrected grid, the production default (`patience=20`) at seed 3
    produces an INVERTED ranking (ROC-AUC 0.252, calibration slope -3.01) -- the
    same kind of failure the second diagnostic exists to catch. Here the Brier
    comparison does not turn it into a win (the verdict is `inconclusive`), which
    is exactly why a verdict must never rest on the Brier score alone."""
    result = run_recessionnet_kaggle_job(RecessionNetKaggleRunConfig(seed=3, patience=20))
    payload = result.evidence_bundle["recessionnet_kaggle"]
    hq = payload["models"]["hybrid_quantum"]
    assert hq["roc_auc"] < 0.5
    assert hq["calibration_slope"] < 0
    assert payload["verdict"] != "quantum_better"


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


def test_kaggle_config_from_dict_round_trips_a_valid_recipe() -> None:
    config = RecessionNetKaggleRunConfig(max_epochs=7, bootstrap_resamples=11)
    assert RecessionNetKaggleRunConfig.from_dict(asdict(config)) == config


def test_kaggle_config_from_dict_rejects_a_missing_or_extra_field() -> None:
    payload = asdict(RecessionNetKaggleRunConfig())
    del payload["max_epochs"]
    with pytest.raises(ValueError, match="complete configuration fields"):
        RecessionNetKaggleRunConfig.from_dict(payload)
    payload = asdict(RecessionNetKaggleRunConfig())
    payload["unknown"] = 1
    with pytest.raises(ValueError, match="complete configuration fields"):
        RecessionNetKaggleRunConfig.from_dict(payload)


def test_kaggle_config_from_dict_decodes_string_dates() -> None:
    payload = asdict(RecessionNetKaggleRunConfig())
    payload["validation_split_date"] = "2002-01-01"
    config = RecessionNetKaggleRunConfig.from_dict(payload)
    assert config.validation_split_date == date(2002, 1, 1)


def test_run_recessionnet_kaggle_job_produces_a_real_manifest_and_evidence_bundle() -> None:
    config = RecessionNetKaggleRunConfig(
        max_epochs=2, patience=1, window=2, horizon=1, bootstrap_resamples=5,
        validation_split_date=date(2001, 1, 1), test_split_date=date(2002, 1, 1),
    )
    result = run_recessionnet_kaggle_job(config)
    assert result.manifest.seed == config.seed
    payload = result.evidence_bundle["recessionnet_kaggle"]
    assert payload["accounting_convention"] == "classifier-benchmark-v1"
    assert payload["schema_version"] == 1
    assert payload["data_source"] == "kaggle_local_snapshot"
    assert result.evidence_bundle["run_manifest"]["result_hash"] == result.manifest.result_hash
