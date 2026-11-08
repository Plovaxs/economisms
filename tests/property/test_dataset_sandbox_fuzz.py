"""Property-based fuzz testing for `data_ingestion.dataset_sandbox`
(SEC-08: "Validate and sandbox untrusted uploaded dataset formats";
acceptance criterion: "Fuzz/test suite blocks unsafe deserialization
paths"), mirroring this repository's existing
`test_extreme_input_robustness.py` pattern: the invariant tested is
deliberately permissive about *rejection* (`validate_zip_archive` may
legitimately raise `UnsafeDatasetError` for any entry name) but strict
about *crashing* -- no OTHER exception type (an uncaught
`UnicodeEncodeError`, `OverflowError`, `ZeroDivisionError`, etc.) may
ever escape, regardless of how adversarial or nonsensical the randomly
generated entry name is.
"""

from __future__ import annotations

import io
import zipfile

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from prometheus.data_ingestion.dataset_sandbox import UnsafeDatasetError, validate_zip_archive

_SUPPRESS = settings(max_examples=300, suppress_health_check=[HealthCheck.too_slow])

_entry_names = st.text(min_size=1, max_size=60).filter(lambda s: "\x00" not in s)


@given(name=_entry_names)
@_SUPPRESS
def test_validate_zip_archive_never_crashes_on_an_arbitrary_entry_name(name: str) -> None:
    buffer = io.BytesIO()
    try:
        with zipfile.ZipFile(buffer, "w") as archive:
            archive.writestr(name, "payload")
    except Exception:
        return  # zipfile itself rejected the name while building the fixture

    try:
        validate_zip_archive(buffer.getvalue())
    except UnsafeDatasetError:
        pass  # a legitimate rejection -- the exact invariant being tested for


@given(garbage=st.binary(min_size=0, max_size=200))
@_SUPPRESS
def test_validate_zip_archive_never_crashes_on_arbitrary_bytes(garbage: bytes) -> None:
    try:
        validate_zip_archive(garbage)
    except UnsafeDatasetError:
        pass
