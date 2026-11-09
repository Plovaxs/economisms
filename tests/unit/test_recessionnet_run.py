import calendar
import csv
import io
import json
import zipfile
from datetime import date
from pathlib import Path

import pytest

from prometheus.data_ingestion.transport import HttpResponse
from prometheus.econosim.pit import MacroObservation
from prometheus.experiments.bootstrap import BootstrapResult
from prometheus.orchestration.recessionnet_run import (
    RecessionNetRunConfig,
    _verdict,
    load_real_ff3_observations,
    load_real_ff3_observations_or_cached,
    main,
    run_recessionnet_demo,
)

_FIXTURE_CSV = Path(__file__).resolve().parents[1] / "fixtures" / "ff3_monthly_real.csv"


class _ScriptedTransport:
    def __init__(self, body: bytes, *, status_code: int = 200) -> None:
        self._body = body
        self._status_code = status_code
        self.calls: list[tuple[str, dict[str, str]]] = []

    def get(self, url: str, params: dict[str, str]) -> HttpResponse:
        self.calls.append((url, dict(params)))
        return HttpResponse(status_code=self._status_code, body=self._body)


def _make_zip(content: str, inner_name: str = "F-F_Research_Data_Factors.csv") -> bytes:
    """Duplicated from `test_french_factors.py` (not cross-imported --
    this project's established convention)."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr(inner_name, content)
    return buffer.getvalue()


def _small_synthetic_zip(n_months: int = 20) -> bytes:
    """A small, CLEARLY SYNTHETIC (not real) French-factors-formatted
    archive spanning 1999-01 through however many months are needed to
    cross a 2000-01-01 split -- used only to exercise the CLI's
    plumbing (arg parsing, config validation, output writing), never
    presented as real data or a real recession-prediction result."""
    header = "This file was created using the 999901 CRSP database.\nSynthetic test fixture.\n"
    rows = []
    year, month = 1999, 1
    for i in range(n_months):
        rows.append(f"{year}{month:02d},{0.1 * i},{-0.05 * i},{0.02 * i},0.01")
        month += 1
        if month > 12:
            month = 1
            year += 1
    body = header + "\n,Mkt-RF,SMB,HML,RF\n" + "\n".join(rows) + "\n"
    return _make_zip(body)


def _load_real_ff3_observations() -> list[MacroObservation]:
    """Duplicated (not cross-imported) from the other `recessionnet`
    test modules."""
    observations: list[MacroObservation] = []
    with _FIXTURE_CSV.open() as f:
        for row in csv.DictReader(f):
            year, month = int(row["date"][:4]), int(row["date"][4:6])
            observation_at = date(year, month, calendar.monthrange(year, month)[1])
            for factor in ("Mkt-RF", "SMB", "HML", "RF"):
                observations.append(
                    MacroObservation(
                        series_id=f"FF3_{factor}",
                        observation_at=observation_at,
                        published_at=observation_at,
                        value=float(row[factor]),
                    )
                )
    return observations


_REAL_OBSERVATIONS = _load_real_ff3_observations()


def test_config_rejects_a_negative_seed() -> None:
    with pytest.raises(ValueError, match="seed"):
        RecessionNetRunConfig(seed=-1)


def test_config_rejects_non_positive_max_epochs() -> None:
    with pytest.raises(ValueError, match="max_epochs"):
        RecessionNetRunConfig(max_epochs=0)


def test_config_rejects_non_positive_patience() -> None:
    with pytest.raises(ValueError, match="patience"):
        RecessionNetRunConfig(patience=0)


def test_config_rejects_a_validation_split_not_before_the_test_split() -> None:
    with pytest.raises(ValueError, match="validation_split_date"):
        RecessionNetRunConfig(
            validation_split_date=date(2005, 1, 1), test_split_date=date(2000, 1, 1)
        )


def test_config_rejects_non_positive_window() -> None:
    with pytest.raises(ValueError, match="window"):
        RecessionNetRunConfig(window=0)


def test_config_rejects_non_positive_horizon() -> None:
    with pytest.raises(ValueError, match="horizon"):
        RecessionNetRunConfig(horizon=0)


def test_config_rejects_non_positive_bootstrap_resamples() -> None:
    with pytest.raises(ValueError, match="bootstrap_resamples"):
        RecessionNetRunConfig(bootstrap_resamples=0)


def test_config_rejects_empty_series_ids() -> None:
    with pytest.raises(ValueError, match="series_ids"):
        RecessionNetRunConfig(series_ids=())


def test_load_real_ff3_observations_unwraps_a_scripted_response() -> None:
    transport = _ScriptedTransport(_small_synthetic_zip(n_months=3))
    observations = load_real_ff3_observations(transport)
    assert len(observations) == 3 * 4  # 3 months x 4 factors
    assert all(obs.series_id.startswith("FF3_") for obs in observations)
    assert len(transport.calls) == 1


def test_load_or_cached_returns_live_data_and_tags_it_as_live_on_success() -> None:
    transport = _ScriptedTransport(_small_synthetic_zip(n_months=3))
    observations, data_source = load_real_ff3_observations_or_cached(transport)
    assert data_source == "live"
    assert len(observations) == 3 * 4


def test_load_or_cached_falls_back_to_the_snapshot_on_a_bad_http_status(tmp_path) -> None:
    """The scenario this whole fallback exists for: a live fetch
    fails (here, a non-200 response -> FrenchFactorsResponseError),
    and the CLI must not hard-fail -- it falls back to the committed
    offline snapshot instead."""
    from prometheus.data_ingestion.french_factors import save_ff3_snapshot
    from prometheus.data_ingestion.transport import HttpResponse as _HttpResponse

    class _AlwaysFailsTransport:
        def get(self, url: str, params: dict[str, str]) -> _HttpResponse:
            return _HttpResponse(status_code=503, body=b"")

    good_transport = _ScriptedTransport(_small_synthetic_zip(n_months=5))
    good_observations = load_real_ff3_observations(good_transport)
    from prometheus.data_ingestion.french_factors import FrenchFactorsFetchResult

    snapshot_path = tmp_path / "snapshot.csv"
    save_ff3_snapshot(
        FrenchFactorsFetchResult(
            observations=tuple(good_observations),
            raw_hash="0" * 64,
            database_vintage="999901",
            methodological_notes="synthetic",
        ),
        snapshot_path,
    )

    observations, data_source = load_real_ff3_observations_or_cached(
        _AlwaysFailsTransport(), cache_path=snapshot_path
    )
    assert data_source == "cached_snapshot_fallback"
    assert len(observations) == len(good_observations)


def test_load_or_cached_falls_back_on_a_network_error(tmp_path) -> None:
    from prometheus.data_ingestion.french_factors import (
        FrenchFactorsFetchResult,
        save_ff3_snapshot,
    )
    from prometheus.data_ingestion.transport import HttpRequestError

    class _NetworkDownTransport:
        def get(self, url: str, params: dict[str, str]) -> HttpResponse:
            raise HttpRequestError("simulated network failure")

    good_transport = _ScriptedTransport(_small_synthetic_zip(n_months=3))
    good_observations = load_real_ff3_observations(good_transport)
    snapshot_path = tmp_path / "snapshot.csv"
    save_ff3_snapshot(
        FrenchFactorsFetchResult(
            observations=tuple(good_observations),
            raw_hash="1" * 64,
            database_vintage="999901",
            methodological_notes="synthetic",
        ),
        snapshot_path,
    )

    observations, data_source = load_real_ff3_observations_or_cached(
        _NetworkDownTransport(), cache_path=snapshot_path
    )
    assert data_source == "cached_snapshot_fallback"
    assert len(observations) == len(good_observations)


def test_verdict_is_inconclusive_when_the_bootstrap_ci_includes_zero() -> None:
    from types import SimpleNamespace

    inconclusive_report = SimpleNamespace(
        quantum_vs_best_classical=BootstrapResult(
            point_estimate=0.001, ci_low=-0.01, ci_high=0.02, confidence=0.95, n_resamples=100
        )
    )
    assert _verdict(inconclusive_report) == "inconclusive"  # type: ignore[arg-type]


def test_verdict_is_quantum_better_when_the_ci_excludes_zero_below() -> None:
    from types import SimpleNamespace

    quantum_better_report = SimpleNamespace(
        quantum_vs_best_classical=BootstrapResult(
            point_estimate=-0.05, ci_low=-0.08, ci_high=-0.02, confidence=0.95, n_resamples=100
        )
    )
    assert _verdict(quantum_better_report) == "quantum_better"  # type: ignore[arg-type]


def test_run_recessionnet_demo_matches_the_real_observed_result() -> None:
    """Locks in the real, reproducible seed=0 finding for this CLI's
    default configuration (window=6, horizon=6, validation split
    1988-01-01, test split 2000-01-01, early stopping with
    max_epochs=500/patience=20 -- PR-144's methodology, matching
    Q-MACRO's CLI from the start rather than this module's own earlier,
    superseded fixed-epoch behavior): the hybrid quantum classifier's
    Brier score (~0.087) sits close to its best classical challenger's
    (classical_matched_mlp, ~0.083), and the paired bootstrap CI
    includes zero -- "inconclusive," the same honest finding
    `test_recessionnet_evaluation.py`'s equivalent end-to-end test
    already locks in directly against `run_recessionnet_benchmark_
    with_early_stopping`. Training is fully deterministic given a
    fixed seed, so this is a legitimate regression check."""
    config = RecessionNetRunConfig(seed=0, max_epochs=500, patience=20, bootstrap_resamples=200)
    result = run_recessionnet_demo(_REAL_OBSERVATIONS, config)

    assert result.n_train_samples > 0
    assert result.n_validation_samples > 0
    assert result.n_test_samples > 0
    assert result.n_train_positive > 0
    assert result.n_test_positive > 0
    assert set(result.report.metrics) == {
        "base_rate",
        "logistic_regression",
        "classical_matched_mlp",
        "hybrid_quantum",
    }
    assert result.report.best_classical_challenger == "classical_matched_mlp"
    assert result.report.metrics["hybrid_quantum"].brier_score == pytest.approx(0.0874, abs=0.01)
    assert result.verdict == "inconclusive"
    assert result.report.quantum_vs_best_classical.excludes_zero() is False


def test_main_writes_output_and_prints_a_json_summary(tmp_path, capsys) -> None:
    output_path = tmp_path / "report.json"
    transport = _ScriptedTransport(_small_synthetic_zip(n_months=20))
    exit_code = main(
        [
            "--seed", "0",
            "--max-epochs", "5",
            "--patience", "3",
            "--window", "2",
            "--horizon", "1",
            "--validation-split-date", "1999-08-01",
            "--test-split-date", "2000-01-01",
            "--bootstrap-resamples", "20",
            "--output", str(output_path),
        ],
        transport=transport,
    )
    assert exit_code == 0

    printed = json.loads(capsys.readouterr().out)
    saved = json.loads(output_path.read_text())
    assert printed == saved
    assert saved["data_source"] == "live"
    assert saved["verdict"] in {"quantum_better", "classical_better", "inconclusive"}
    assert saved["run_manifest"]["model_id"] == "recessionnet-hybrid-quantum-v1"
    assert set(saved["models"]) == {
        "base_rate",
        "logistic_regression",
        "classical_matched_mlp",
        "hybrid_quantum",
    }


def test_main_rejects_an_invalid_split_date(capsys) -> None:
    with pytest.raises(SystemExit):
        main(["--validation-split-date", "not-a-date"], transport=_ScriptedTransport(b""))
    assert "invalid" in capsys.readouterr().err.lower()


def test_main_rejects_an_invalid_config_value(capsys) -> None:
    with pytest.raises(SystemExit):
        main(["--max-epochs", "0"], transport=_ScriptedTransport(b""))
    assert "max_epochs" in capsys.readouterr().err
