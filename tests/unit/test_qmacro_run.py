import calendar
import csv
import io
import json
import zipfile
from dataclasses import asdict
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pytest

from prometheus.data_ingestion.transport import HttpResponse
from prometheus.econosim.pit import MacroObservation
from prometheus.experiments.bootstrap import BootstrapResult
from prometheus.orchestration.qmacro_run import (
    QMacroRunConfig,
    _verdict,
    main,
    run_qmacro_demo,
    run_qmacro_job,
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
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr(inner_name, content)
    return buffer.getvalue()


def _small_synthetic_zip(n_months: int = 60) -> bytes:
    """A small, clearly SYNTHETIC archive -- used only to exercise the
    CLI's plumbing, never presented as a real regression result."""
    header = "This file was created using the 999901 CRSP database.\nSynthetic test fixture.\n"
    rows = []
    year, month = 1990, 1
    for i in range(n_months):
        rows.append(f"{year}{month:02d},{0.3 * ((i % 7) - 3)},{-0.05 * i},{0.02 * i},0.01")
        month += 1
        if month > 12:
            month = 1
            year += 1
    body = header + "\n,Mkt-RF,SMB,HML,RF\n" + "\n".join(rows) + "\n"
    return _make_zip(body)


def _month_end(year: int, month: int) -> date:
    return date(year, month, calendar.monthrange(year, month)[1])


def _load_real_ff3_observations() -> list[MacroObservation]:
    observations: list[MacroObservation] = []
    with _FIXTURE_CSV.open() as f:
        for row in csv.DictReader(f):
            year, month = int(row["date"][:4]), int(row["date"][4:6])
            observation_at = _month_end(year, month)
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
        QMacroRunConfig(seed=-1)


def test_config_rejects_non_positive_max_epochs() -> None:
    with pytest.raises(ValueError, match="max_epochs"):
        QMacroRunConfig(max_epochs=0)


def test_config_rejects_non_positive_patience() -> None:
    with pytest.raises(ValueError, match="patience"):
        QMacroRunConfig(patience=0)


def test_config_rejects_non_positive_window() -> None:
    with pytest.raises(ValueError, match="window"):
        QMacroRunConfig(window=0)


def test_config_rejects_non_positive_horizon() -> None:
    with pytest.raises(ValueError, match="horizon"):
        QMacroRunConfig(horizon=0)


def test_config_rejects_non_positive_ar_order() -> None:
    with pytest.raises(ValueError, match="ar_order"):
        QMacroRunConfig(ar_order=0)


def test_config_rejects_non_positive_bootstrap_resamples() -> None:
    with pytest.raises(ValueError, match="bootstrap_resamples"):
        QMacroRunConfig(bootstrap_resamples=0)


def test_config_rejects_empty_feature_series_ids() -> None:
    with pytest.raises(ValueError, match="feature_series_ids"):
        QMacroRunConfig(feature_series_ids=())


def test_config_rejects_a_validation_split_not_before_the_test_split() -> None:
    with pytest.raises(ValueError, match="validation_split_date"):
        QMacroRunConfig(validation_split_date=date(2005, 1, 1), test_split_date=date(2000, 1, 1))


def test_verdict_is_inconclusive_when_the_bootstrap_ci_includes_zero() -> None:
    report = SimpleNamespace(
        quantum_vs_best_classical=BootstrapResult(
            point_estimate=0.0001, ci_low=-0.001, ci_high=0.002, confidence=0.95, n_resamples=100
        )
    )
    assert _verdict(report) == "inconclusive"  # type: ignore[arg-type]


def test_verdict_is_quantum_better_when_the_ci_excludes_zero_below() -> None:
    report = SimpleNamespace(
        quantum_vs_best_classical=BootstrapResult(
            point_estimate=-0.01, ci_low=-0.02, ci_high=-0.005, confidence=0.95, n_resamples=100
        )
    )
    assert _verdict(report) == "quantum_better"  # type: ignore[arg-type]


def test_run_qmacro_demo_matches_the_real_observed_result() -> None:
    """Locks in the real, reproducible seed=0 finding (see
    `test_macrocore_quantum_benchmark.py`): AR(3), the classical MLP
    and the hybrid quantum regressor all land in a tight band, clearly
    ahead of naive persistence, with no significant difference among
    the sophisticated candidates."""
    config = QMacroRunConfig(seed=0, max_epochs=500, patience=20, bootstrap_resamples=200)
    result = run_qmacro_demo(_REAL_OBSERVATIONS, config)

    assert result.n_train_samples > 0
    assert result.n_validation_samples > 0
    assert result.n_test_samples > 0
    assert set(result.report.metrics) == {
        "persistence",
        "ar",
        "linear_regression",
        "classical_matched_mlp",
        "hybrid_quantum",
    }
    for name in ("ar", "linear_regression", "classical_matched_mlp", "hybrid_quantum"):
        assert result.report.metrics[name].mase < result.report.metrics["persistence"].mase
    assert result.verdict == "inconclusive"
    assert result.report.quantum_vs_best_classical.excludes_zero() is False


def test_main_writes_output_and_prints_a_json_summary(tmp_path, capsys) -> None:
    output_path = tmp_path / "report.json"
    transport = _ScriptedTransport(_small_synthetic_zip(n_months=90))
    exit_code = main(
        [
            "--seed", "0",
            "--max-epochs", "5",
            "--patience", "3",
            "--window", "2",
            "--horizon", "1",
            "--ar-order", "1",
            "--validation-split-date", "1993-01-01",
            "--test-split-date", "1995-01-01",
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
    assert saved["run_manifest"]["model_id"] == "qmacro-hybrid-quantum-v1"
    assert set(saved["models"]) == {
        "persistence",
        "ar",
        "linear_regression",
        "classical_matched_mlp",
        "hybrid_quantum",
    }


def test_main_rejects_an_invalid_date(capsys) -> None:
    with pytest.raises(SystemExit):
        main(["--validation-split-date", "not-a-date"], transport=_ScriptedTransport(b""))
    assert "invalid" in capsys.readouterr().err.lower()


def test_main_rejects_an_invalid_config_value(capsys) -> None:
    with pytest.raises(SystemExit):
        main(["--max-epochs", "0"], transport=_ScriptedTransport(b""))
    assert "max_epochs" in capsys.readouterr().err


def test_an_uninjected_transport_uses_the_real_allowlisted_default(monkeypatch, capsys) -> None:
    """SEC-10: a real invocation (no `transport=` injected) must go through
    `egress_allowlist.default_ingestion_transport`, not a bare
    `UrllibTransport` -- confirmed by monkeypatching that exact factory
    (never making a real network call) and checking it was actually
    called."""
    import prometheus.orchestration.qmacro_run as module

    calls: list[None] = []
    scripted = _ScriptedTransport(_small_synthetic_zip(n_months=90))

    def _fake_default_ingestion_transport() -> _ScriptedTransport:
        calls.append(None)
        return scripted

    monkeypatch.setattr(module, "default_ingestion_transport", _fake_default_ingestion_transport)
    exit_code = main(
        [
            "--max-epochs", "2",
            "--patience", "1",
            "--ar-order", "1",
            "--bootstrap-resamples", "5",
            "--validation-split-date", "1993-01-01",
            "--test-split-date", "1995-01-01",
        ],
    )
    assert exit_code == 0
    assert calls == [None]
    assert scripted.calls


def test_from_dict_round_trips_a_valid_recipe() -> None:
    config = QMacroRunConfig(max_epochs=7, bootstrap_resamples=11)
    payload = asdict(config)
    assert QMacroRunConfig.from_dict(payload) == config


def test_from_dict_rejects_a_missing_field() -> None:
    payload = asdict(QMacroRunConfig())
    del payload["max_epochs"]
    with pytest.raises(ValueError, match="complete configuration fields"):
        QMacroRunConfig.from_dict(payload)


def test_from_dict_rejects_an_extra_field() -> None:
    payload = asdict(QMacroRunConfig())
    payload["unknown"] = 1
    with pytest.raises(ValueError, match="complete configuration fields"):
        QMacroRunConfig.from_dict(payload)


def test_from_dict_decodes_string_dates_and_a_json_list_series_ids() -> None:
    payload = asdict(QMacroRunConfig())
    payload["validation_split_date"] = "1990-01-01"
    payload["test_split_date"] = "1995-01-01"
    payload["feature_series_ids"] = list(payload["feature_series_ids"])
    config = QMacroRunConfig.from_dict(payload)
    assert config.validation_split_date == date(1990, 1, 1)
    assert isinstance(config.feature_series_ids, tuple)


def test_run_qmacro_job_produces_a_real_manifest_and_evidence_bundle(monkeypatch) -> None:
    """The job-kind adapter: a real (scripted, hermetic) transport is
    injected the same way `test_an_uninjected_transport_uses_the_real_
    allowlisted_default` confirms the un-injected path works -- here
    confirming the job adapter itself (no `transport=` parameter at
    all, unlike `main()`) still reaches the real pipeline."""
    import prometheus.orchestration.qmacro_run as module

    scripted = _ScriptedTransport(_small_synthetic_zip(n_months=90))
    monkeypatch.setattr(module, "default_ingestion_transport", lambda: scripted)
    config = QMacroRunConfig(
        max_epochs=2, patience=1, ar_order=1, bootstrap_resamples=5,
        validation_split_date=date(1993, 1, 1), test_split_date=date(1995, 1, 1),
    )
    result = run_qmacro_job(config)
    assert result.manifest.seed == config.seed
    assert result.evidence_bundle["qmacro"]["accounting_convention"] == (
        "quantum-classical-benchmark-v1"
    )
    assert result.evidence_bundle["qmacro"]["schema_version"] == 1
    assert result.evidence_bundle["run_manifest"]["result_hash"] == result.manifest.result_hash
