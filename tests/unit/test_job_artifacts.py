import pytest

from prometheus.econosim.price_economy import EconomyRunConfig
from prometheus.jobs.artifacts import ArtifactError, ArtifactStore
from prometheus.orchestration.economy_run import run_economy


@pytest.fixture(scope="module")
def bundle():
    return run_economy(EconomyRunConfig(n_steps=2, productivity_shock_step=2)).evidence_bundle


def test_artifact_publication_is_no_clobber_deduplicated_and_verified_on_read(tmp_path, bundle):
    store = ArtifactStore(tmp_path / "objects")
    first = store.put(bundle)
    path = store._path(first.content_sha256)
    before = path.read_bytes()
    again = store.put(bundle)
    assert again == first and path.read_bytes() == before
    loaded = store.get(first.content_sha256)
    assert loaded["run_manifest"]["result_hash"] == first.result_hash
    assert first.size_bytes == path.stat().st_size
    assert path.stat().st_mode & 0o222 == 0
    assert list(path.parent.iterdir()) == [path]


def test_corrupt_existing_objects_are_not_replaced_or_served(tmp_path, bundle):
    store = ArtifactStore(tmp_path / "objects")
    saved = store.put(bundle)
    path = store._path(saved.content_sha256)
    path.chmod(0o600)
    path.write_text('{"tampered": true}')
    with pytest.raises(ArtifactError):
        store.get(saved.content_sha256)
    with pytest.raises(ArtifactError):
        store.put(bundle)
    assert path.read_text() == '{"tampered": true}'
    assert list(path.parent.iterdir()) == [path]


def test_oversized_objects_and_path_traversal_are_rejected(tmp_path, bundle):
    store = ArtifactStore(tmp_path / "objects", max_bytes=10)
    with pytest.raises(ArtifactError, match="budget"):
        store.put(bundle)
    assert not list(store.root.iterdir())
    for bad in ("../other", "a" * 63, "G" * 64):
        with pytest.raises(ArtifactError):
            store.get(bad)


def test_symlink_leaf_and_directory_cannot_escape_storage_root(tmp_path, bundle):
    store = ArtifactStore(tmp_path / "objects")
    saved = store.put(bundle)
    path = store._path(saved.content_sha256)
    original = path.read_bytes()
    path.unlink()
    outside = tmp_path / "outside.json"
    outside.write_bytes(original)
    path.symlink_to(outside)
    with pytest.raises(ArtifactError):
        store.get(saved.content_sha256)
    path.unlink()
    path.parent.rmdir()
    path.parent.symlink_to(tmp_path, target_is_directory=True)
    with pytest.raises(ArtifactError):
        store.get(saved.content_sha256)
    assert outside.read_bytes() == original


def test_total_storage_budget_is_enforced_and_existing_objects_still_deduplicate(tmp_path, bundle):
    first_store = ArtifactStore(tmp_path / "objects")
    first = first_store.put(bundle)
    bounded = ArtifactStore(tmp_path / "objects", max_total_bytes=first.size_bytes)
    assert bounded.put(bundle).content_sha256 == first.content_sha256
    changed = dict(bundle, additional_note="a different full artifact")
    with pytest.raises(ArtifactError, match="total byte budget"):
        bounded.put(changed)
    assert bounded.get(first.content_sha256)["run_manifest"]["result_hash"] == first.result_hash


def test_fifo_object_is_rejected_without_waiting_for_a_writer(tmp_path):
    import os

    store = ArtifactStore(tmp_path)
    prefix = tmp_path / "aa"
    prefix.mkdir()
    os.mkfifo(prefix / ("a" * 64 + ".json"), 0o600)
    with pytest.raises(ArtifactError):
        store.get("a" * 64)
