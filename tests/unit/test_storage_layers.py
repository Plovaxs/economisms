import pytest

from prometheus.econosim.storage_layers import (
    ImmutableWriteError,
    LayerPermissionError,
    StorageLayer,
)


def test_a_layer_can_write_and_read_its_own_key() -> None:
    raw = StorageLayer("raw")
    raw.write("series-1", {"value": 100.0})
    assert raw.read("series-1") == {"value": 100.0}


def test_writing_the_same_key_twice_is_rejected() -> None:
    """The immutability half of DAT-06's acceptance criterion."""
    raw = StorageLayer("raw")
    raw.write("series-1", {"value": 100.0})
    with pytest.raises(ImmutableWriteError, match="already written"):
        raw.write("series-1", {"value": 999.0})
    assert raw.read("series-1") == {"value": 100.0}  # the original value survives


def test_a_different_key_can_still_be_written() -> None:
    """The immutability check is per-key, not a blanket freeze of the
    whole layer after its first write."""
    raw = StorageLayer("raw")
    raw.write("series-1", 1.0)
    raw.write("series-2", 2.0)
    assert raw.read("series-1") == 1.0
    assert raw.read("series-2") == 2.0


@pytest.mark.parametrize(
    ("upstream", "downstream"),
    [("raw", "normalized"), ("normalized", "features"), ("features", "artifacts")],
)
def test_each_layer_may_read_directly_from_its_own_immediate_upstream(
    upstream: str, downstream: str
) -> None:
    source = StorageLayer(upstream)  # type: ignore[arg-type]
    sink = StorageLayer(downstream)  # type: ignore[arg-type]
    source.write("k", "v")
    assert sink.read_from(source, "k") == "v"


def test_features_may_not_read_directly_from_raw_skipping_normalized() -> None:
    """The layer-permissions half of DAT-06's acceptance criterion: a
    layer may only read from the ONE layer immediately upstream of it,
    not reach further back up the pipeline."""
    raw = StorageLayer("raw")
    features = StorageLayer("features")
    raw.write("k", "v")
    with pytest.raises(LayerPermissionError, match="may not read directly"):
        features.read_from(raw, "k")


def test_artifacts_may_not_read_directly_from_normalized_or_raw() -> None:
    normalized = StorageLayer("normalized")
    raw = StorageLayer("raw")
    artifacts = StorageLayer("artifacts")
    raw.write("k", "v")
    normalized.write("k", "v")
    with pytest.raises(LayerPermissionError):
        artifacts.read_from(raw, "k")
    with pytest.raises(LayerPermissionError):
        artifacts.read_from(normalized, "k")


def test_raw_may_not_read_from_anything_it_is_the_source() -> None:
    raw = StorageLayer("raw")
    other_raw = StorageLayer("raw")
    other_raw.write("k", "v")
    with pytest.raises(LayerPermissionError):
        raw.read_from(other_raw, "k")


def test_reading_a_missing_key_raises_key_error_not_silently_none() -> None:
    raw = StorageLayer("raw")
    with pytest.raises(KeyError):
        raw.read("missing")
