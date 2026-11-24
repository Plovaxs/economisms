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


def _fail_the_nth_fsync(monkeypatch, which: int, error: OSError) -> None:
    """Make the `which`-th `os.fsync` call raise: 1 is the artifact's own data, 2 and 3 are the two
    directory syncs after it has been linked into place."""
    from prometheus.jobs import artifacts

    real, calls = artifacts.os.fsync, {"n": 0}

    def flaky(fd):
        calls["n"] += 1
        if calls["n"] == which:
            raise error
        return real(fd)

    monkeypatch.setattr(artifacts.os, "fsync", flaky)


def _only_the_lock_remains(store) -> bool:
    return [p.name for p in store.root.rglob("*") if p.is_file()] == ["publish.lock"]


def test_a_full_disk_while_writing_publishes_nothing_and_leaves_no_debris(
    tmp_path, bundle, monkeypatch
):
    """ENOSPC while the artifact's bytes are being made durable: the call fails loudly, no artifact
    is visible, no staging file is left behind, and the store is not wedged: the same bundle can
    be published once the disk has room."""
    import errno

    store = ArtifactStore(tmp_path / "objects")
    with monkeypatch.context() as patch:
        _fail_the_nth_fsync(patch, 1, OSError(errno.ENOSPC, "No space left on device"))
        with pytest.raises(OSError, match="No space left"):
            store.put(bundle)
    assert _only_the_lock_remains(store)  # nothing published, no orphan staging file
    saved = store.put(bundle)  # the disk has room again
    assert store.get(saved.content_sha256)["run_manifest"]["result_hash"] == saved.result_hash


@pytest.mark.parametrize("which", [2, 3], ids=["parent-directory-sync", "root-directory-sync"])
def test_a_failure_after_the_artifact_is_linked_leaves_a_complete_verified_object(
    tmp_path, bundle, monkeypatch, which
):
    """The data were already durable and linked into place when a directory sync failed: the caller
    sees the error, and what is on disk is a COMPLETE object that verifies, never a half-written
    one. Publishing again returns it as a duplicate."""
    import errno

    store = ArtifactStore(tmp_path / "objects")
    with monkeypatch.context() as patch:
        _fail_the_nth_fsync(patch, which, OSError(errno.EIO, "Input/output error"))
        with pytest.raises(OSError, match="Input/output error"):
            store.put(bundle)
    objects = [p for p in store.root.rglob("*.json")]
    assert len(objects) == 1
    digest = objects[0].stem
    assert store.get(digest)["run_manifest"]["result_hash"]  # complete, and verified on read
    assert [p.name for p in objects[0].parent.iterdir()] == [objects[0].name]  # no staging file
    again = store.put(bundle)
    assert again.content_sha256 == digest


def test_a_store_that_cannot_make_its_directory_publishes_nothing(tmp_path, bundle):
    import os

    store = ArtifactStore(tmp_path / "objects")
    store.root.chmod(0o500)  # read-only: no new prefix directory can be created
    try:
        if os.access(store.root, os.W_OK):
            pytest.skip("running as a user that can write to a read-only directory")
        with pytest.raises(OSError):
            store.put(bundle)
    finally:
        store.root.chmod(0o700)
    assert _only_the_lock_remains(store) or not [p for p in store.root.rglob("*.json")]
