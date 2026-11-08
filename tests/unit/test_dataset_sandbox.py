"""Hand-built adversarial-input cases for `dataset_sandbox` (SEC-08).
The general "never crashes with an unexpected exception type" fuzz
property over randomly generated entry names lives in
`tests/property/test_dataset_sandbox_fuzz.py`, mirroring this
repository's existing extreme-input-robustness property tests.
"""

import io
import zipfile

import pytest

from prometheus.data_ingestion.dataset_sandbox import (
    SandboxLimits,
    UnsafeDatasetError,
    validate_zip_archive,
)


def _make_zip(entries: list[tuple[str, bytes | str]], *, deflate: bool = False) -> bytes:
    buffer = io.BytesIO()
    compression = zipfile.ZIP_DEFLATED if deflate else zipfile.ZIP_STORED
    with zipfile.ZipFile(buffer, "w", compression=compression, compresslevel=9) as archive:
        for name, content in entries:
            archive.writestr(name, content)
    return buffer.getvalue()


def test_sandbox_limits_rejects_a_non_positive_max_entries() -> None:
    with pytest.raises(ValueError, match="max_entries"):
        SandboxLimits(max_entries=0)


def test_sandbox_limits_rejects_a_non_positive_max_total_uncompressed_bytes() -> None:
    with pytest.raises(ValueError, match="max_total_uncompressed_bytes"):
        SandboxLimits(max_total_uncompressed_bytes=0)


def test_sandbox_limits_rejects_a_non_positive_max_compression_ratio() -> None:
    with pytest.raises(ValueError, match="max_compression_ratio"):
        SandboxLimits(max_compression_ratio=0)


def test_not_a_zip_at_all_raises() -> None:
    with pytest.raises(UnsafeDatasetError, match="not a valid zip archive"):
        validate_zip_archive(b"definitely not a zip file")


@pytest.mark.parametrize(
    "name",
    [
        "../../etc/passwd",
        "a/../../etc/passwd",
        "/etc/passwd",
        "\\etc\\passwd",
        "C:\\Windows\\System32\\evil.dll",
        "..",
    ],
)
def test_zip_slip_entry_names_are_rejected(name: str) -> None:
    data = _make_zip([(name, "payload")])
    with pytest.raises(UnsafeDatasetError, match="escape|absolute"):
        validate_zip_archive(data)


@pytest.mark.parametrize("name", ["normal/path/file.csv", "file.csv", "a/b/../c.csv"])
def test_benign_relative_entry_names_are_accepted(name: str) -> None:
    data = _make_zip([(name, "payload")])
    validate_zip_archive(data)  # must not raise


def test_a_genuine_decompression_bomb_is_rejected() -> None:
    """A real DEFLATE-compressed archive expanding ~1000x, built the
    same way a malicious upload would be -- not a hand-waved assertion
    about what a bomb 'would' do."""
    data = _make_zip([("bomb.txt", "0" * 50_000_000)], deflate=True)
    with pytest.raises(UnsafeDatasetError, match="compression ratio"):
        validate_zip_archive(data)


def test_a_real_captured_benign_archive_is_accepted() -> None:
    """Grounded against the SAME real Kenneth French archive
    `test_french_factors.py` captured live -- its true ~4x compression
    ratio must stay comfortably under the default 100x threshold."""
    from tests.unit.test_french_factors import _REAL_ZIP_BYTES

    validate_zip_archive(_REAL_ZIP_BYTES)  # must not raise


def test_too_many_entries_is_rejected() -> None:
    data = _make_zip([(f"file{i}.txt", "x") for i in range(5)])
    with pytest.raises(UnsafeDatasetError, match="entries"):
        validate_zip_archive(data, limits=SandboxLimits(max_entries=4))


def test_total_uncompressed_size_over_the_limit_is_rejected() -> None:
    data = _make_zip([("a.txt", "x" * 1000), ("b.txt", "y" * 1000)])
    with pytest.raises(UnsafeDatasetError, match="total uncompressed size"):
        validate_zip_archive(data, limits=SandboxLimits(max_total_uncompressed_bytes=500))


def test_an_empty_stored_entry_does_not_trigger_a_division_by_zero() -> None:
    data = _make_zip([("empty.txt", "")])
    validate_zip_archive(data)  # must not raise ZeroDivisionError or anything else
