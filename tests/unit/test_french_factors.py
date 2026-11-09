"""Tests use a REAL Kenneth French Data Library response -- the actual
`F-F_Research_Data_Factors_CSV.zip` archive, captured live during this
connector's own pre-implementation verification -- embedded here as a
base64 string literal so the test suite stays hermetic (no live network
call during `pytest`) while still exercising the parser against a file
it did not invent. Edge cases the real capture happened not to contain
(a bad zip, a missing vintage statement, an empty data section) are
covered by separate, explicitly hand-constructed fixtures below.
"""

import base64
import hashlib
import io
import zipfile
from datetime import date

import pytest

from prometheus.data_ingestion.french_factors import (
    FRENCH_SOURCE_LICENSE,
    FrenchFactorsResponseError,
    fetch_french_factors,
    load_cached_ff3_snapshot,
    save_ff3_snapshot,
)
from prometheus.data_ingestion.transport import HttpResponse
from prometheus.econosim.pit import FutureDataError, PointInTimeStore, require_eligible

# The real archive served by mba.tuck.dartmouth.edu for
# F-F_Research_Data_Factors_CSV.zip at capture time, stating it was
# "created using the 202609 CRSP database".
_REAL_FRENCH_FACTORS_ZIP_B64 = (
    "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"
    "AAAAUEsFBgAAAAABAAEAbwAAAJEyAAAAAA=="
)
_REAL_ZIP_BYTES = base64.b64decode(_REAL_FRENCH_FACTORS_ZIP_B64)


class _ScriptedTransport:
    def __init__(self, body: bytes, *, status_code: int = 200) -> None:
        self._body = body
        self._status_code = status_code
        self.calls: list[tuple[str, dict[str, str]]] = []

    def get(self, url: str, params: dict[str, str]) -> HttpResponse:
        self.calls.append((url, dict(params)))
        return HttpResponse(status_code=self._status_code, body=self._body)


def test_parses_a_real_captured_monthly_response() -> None:
    transport = _ScriptedTransport(_REAL_ZIP_BYTES)
    result = fetch_french_factors(transport)

    assert result.database_vintage == "202609"
    assert "CRSP database" in result.methodological_notes
    assert len(result.observations) == 4812  # 1203 months x 4 factors
    assert all(obs.frequency == "M" for obs in result.observations)
    assert all(obs.series_id.startswith("FF3_") for obs in result.observations)

    expected_hash = hashlib.sha256(_REAL_ZIP_BYTES).hexdigest()
    assert result.raw_hash == expected_hash
    assert all(obs.raw_hash == expected_hash for obs in result.observations)
    assert all(obs.published_at == date(2026, 9, 30) for obs in result.observations)
    expected_license = "Kenneth R. French Data Library (free for academic research use)"
    assert all(obs.source_license == expected_license for obs in result.observations)

    mkt_rf_first = next(
        obs
        for obs in result.observations
        if obs.series_id == "FF3_Mkt-RF" and obs.observation_at == date(1926, 7, 31)
    )
    assert mkt_rf_first.value == pytest.approx(2.89)

    mkt_rf_last = next(
        obs
        for obs in result.observations
        if obs.series_id == "FF3_Mkt-RF" and obs.observation_at == date(2026, 9, 30)
    )
    assert mkt_rf_last.value == pytest.approx(-1.07)

    assert len(transport.calls) == 1


def test_parses_a_real_captured_annual_response() -> None:
    transport = _ScriptedTransport(_REAL_ZIP_BYTES)
    result = fetch_french_factors(transport, frequency="annual")

    assert len(result.observations) == 396  # 99 years x 4 factors
    assert all(obs.frequency == "A" for obs in result.observations)
    assert all(
        obs.observation_at.month == 12 and obs.observation_at.day == 31
        for obs in result.observations
    )

    mkt_rf_first = next(
        obs
        for obs in result.observations
        if obs.series_id == "FF3_Mkt-RF" and obs.observation_at == date(1927, 12, 31)
    )
    assert mkt_rf_first.value == pytest.approx(29.44)

    mkt_rf_last = next(
        obs
        for obs in result.observations
        if obs.series_id == "FF3_Mkt-RF" and obs.observation_at == date(2025, 12, 31)
    )
    assert mkt_rf_last.value == pytest.approx(13.3)


def test_observations_feed_the_point_in_time_store_correctly() -> None:
    transport = _ScriptedTransport(_REAL_ZIP_BYTES)
    result = fetch_french_factors(transport)

    store = PointInTimeStore()
    for obs in result.observations:
        store.record(obs)

    sample = result.observations[0]
    with pytest.raises(FutureDataError):
        require_eligible(store, sample.series_id, sample.observation_at, date(2026, 9, 29))
    recovered = require_eligible(store, sample.series_id, sample.observation_at, date(2026, 9, 30))
    assert recovered == sample


def test_non_200_status_raises() -> None:
    transport = _ScriptedTransport(b"", status_code=503)
    with pytest.raises(FrenchFactorsResponseError, match="503"):
        fetch_french_factors(transport)


def test_malformed_zip_raises() -> None:
    transport = _ScriptedTransport(b"not a zip at all")
    with pytest.raises(FrenchFactorsResponseError, match="zip"):
        fetch_french_factors(transport)


def test_missing_vintage_statement_raises() -> None:
    body = (
        "A free-text header with no vintage statement.\n\n"
        ",Mkt-RF,SMB,HML,RF\n192607,2.96,-2.56,-2.43,0.22\n"
    )
    transport = _ScriptedTransport(_make_zip(body))
    with pytest.raises(FrenchFactorsResponseError, match="vintage"):
        fetch_french_factors(transport)


def test_empty_frequency_section_raises() -> None:
    header = "This file was created using the 202609 CRSP database.\nCopyright line.\n"
    body = header + "\n,Mkt-RF,SMB,HML,RF\n"  # no data rows of either frequency
    transport = _ScriptedTransport(_make_zip(body))
    with pytest.raises(FrenchFactorsResponseError, match="no monthly data rows"):
        fetch_french_factors(transport)


def test_rows_with_non_numeric_values_are_skipped_not_fabricated() -> None:
    header = "This file was created using the 202609 CRSP database.\nCopyright line.\n"
    body = (
        header
        + "\n,Mkt-RF,SMB,HML,RF\n"
        + "192607,bad,data,here,now\n"  # numeric key, non-numeric values -> skipped
        + "192608,2.96,-2.56,-2.43,0.22\n"
    )
    transport = _ScriptedTransport(_make_zip(body))
    result = fetch_french_factors(transport)
    assert len(result.observations) == 4  # only the one valid row, x 4 factors
    assert all(obs.observation_at == date(1926, 8, 31) for obs in result.observations)


def test_unrecognized_date_key_length_raises() -> None:
    header = "This file was created using the 202609 CRSP database.\nCopyright line.\n"
    body = header + "\n,Mkt-RF,SMB,HML,RF\n19260,2.96,-2.56,-2.43,0.22\n"  # 5-digit key
    transport = _ScriptedTransport(_make_zip(body))
    with pytest.raises(FrenchFactorsResponseError, match="unrecognized date key"):
        fetch_french_factors(transport)


def _make_zip(content: str, inner_name: str = "F-F_Research_Data_Factors.csv") -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr(inner_name, content)
    return buffer.getvalue()


def test_snapshot_round_trip_preserves_every_real_monthly_value(tmp_path) -> None:
    """The production offline-fallback path (PR-144): save a real
    fetch's monthly observations, load them back, and confirm every
    value survives exactly -- this is what `orchestration.
    recessionnet_run`/`qmacro_run` fall back to when a live fetch
    fails during a demo."""
    transport = _ScriptedTransport(_REAL_ZIP_BYTES)
    result = fetch_french_factors(transport, frequency="monthly")

    snapshot_path = tmp_path / "ff3_monthly_snapshot.csv"
    save_ff3_snapshot(result, snapshot_path)
    reloaded = load_cached_ff3_snapshot(snapshot_path)

    assert len(reloaded) == len(result.observations)
    original_by_key = {(o.series_id, o.observation_at): o.value for o in result.observations}
    reloaded_by_key = {(o.series_id, o.observation_at): o.value for o in reloaded}
    assert original_by_key == reloaded_by_key
    assert all(o.series_id.startswith("FF3_") for o in reloaded)
    assert all(o.source_license == FRENCH_SOURCE_LICENSE for o in reloaded)
    assert all(o.raw_hash is None for o in reloaded)  # honest provenance gap, not fabricated


def test_save_snapshot_creates_parent_directories(tmp_path) -> None:
    transport = _ScriptedTransport(_REAL_ZIP_BYTES)
    result = fetch_french_factors(transport, frequency="monthly")
    nested_path = tmp_path / "nested" / "dir" / "snapshot.csv"
    save_ff3_snapshot(result, nested_path)
    assert nested_path.exists()


def test_save_snapshot_excludes_annual_rows_from_a_mixed_fetch_result() -> None:
    """`save_ff3_snapshot` only ever writes MONTHLY rows, even if
    handed a result that happens to include annual observations --
    the cached snapshot is specifically the monthly fallback
    `load_cached_ff3_snapshot`'s own reader expects."""
    from prometheus.data_ingestion.french_factors import FrenchFactorsFetchResult

    monthly_transport = _ScriptedTransport(_REAL_ZIP_BYTES)
    monthly_result = fetch_french_factors(monthly_transport, frequency="monthly")
    annual_transport = _ScriptedTransport(_REAL_ZIP_BYTES)
    annual_result = fetch_french_factors(annual_transport, frequency="annual")

    mixed = FrenchFactorsFetchResult(
        observations=monthly_result.observations[:8] + annual_result.observations[:4],
        raw_hash=monthly_result.raw_hash,
        database_vintage=monthly_result.database_vintage,
        methodological_notes=monthly_result.methodological_notes,
    )

    import tempfile
    from pathlib import Path

    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "mixed_snapshot.csv"
        save_ff3_snapshot(mixed, path)
        reloaded = load_cached_ff3_snapshot(path)
        assert len(reloaded) == 8  # only the 2 real months x 4 factors, annual rows excluded
