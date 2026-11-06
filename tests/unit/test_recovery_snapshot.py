import hashlib
import json
import os
import shutil
import sqlite3
import struct
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing

import pytest
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from prometheus.evidence.integrity import INTEGRITY_KEY, artifact_content_hash, seal_evidence_bundle
from prometheus.jobs.artifacts import ArtifactStore
from prometheus.jobs.store import JobStore, LeaseLost, QueuePolicy
from prometheus.jobs.worker import Worker
from prometheus.orchestration.recipes import default_recipe
from prometheus.orchestration.replay import replay_evidence_bundle
from prometheus.recovery.__main__ import main
from prometheus.recovery.snapshot import (
    MAGIC,
    RecoveryError,
    RecoveryLimits,
    create_snapshot,
    generate_key,
    read_key,
    restore_snapshot,
)


@pytest.fixture(scope="module")
def populated(tmp_path_factory):
    root = tmp_path_factory.mktemp("recovery-source")
    store, objects = JobStore(root / "jobs.sqlite3"), ArtifactStore(root / "artifacts")
    config = default_recipe("economy")
    config.update(n_steps=2, productivity_shock_step=2)
    complete = store.submit("economy", config, owner="alice", idempotency_key="complete")
    assert Worker(store, objects, worker_id="reference").run_once().status == "succeeded"
    active = store.submit("economy", config, owner="alice", idempotency_key="active")
    lease = store.claim("original-worker")
    assert lease.job.job_id == active.job_id
    queued = store.submit("economy", config, owner="bob", idempotency_key="queued")
    (root / "auth.json").write_text("credential-canary-must-not-enter-snapshot")
    key = root / "key"
    generate_key(key)
    return root, complete.job_id, active.job_id, queued.job_id, lease


@pytest.fixture
def state(tmp_path, populated):
    base, complete, active, queued, lease = populated
    root = tmp_path / "source"
    shutil.copytree(base, root)
    return root, complete, active, queued, lease


def snapshot(state, tmp_path):
    root = state[0]
    output = tmp_path / "snapshot.enc"
    receipt = create_snapshot(root, output, key_file=root / "key")
    return output, receipt


def plaintext(snapshot, key):
    data = snapshot.read_bytes()
    header = data[: len(MAGIC) + 12]
    decoded = AESGCM(key).decrypt(header[-12:], data[len(header) :], header)
    length = struct.unpack(">I", decoded[:4])[0]
    return json.loads(decoded[4 : 4 + length]), decoded[4 + length :]


def forge(source, key, output, change):
    manifest, content = plaintext(source, key)
    changed = change(manifest, content)
    if changed is not None:
        content = changed
    manifest.pop(INTEGRITY_KEY)
    manifest = seal_evidence_bundle(manifest)
    encoded = json.dumps(manifest, sort_keys=True).encode()
    payload = struct.pack(">I", len(encoded)) + encoded + content
    header = MAGIC + os.urandom(12)
    output.write_bytes(header + AESGCM(key).encrypt(header[-12:], payload, header))


def test_snapshot_restore_replays_terminal_artifact_and_fences_even_unexpired_leases(
    state, tmp_path
):
    root, complete, active, queued, lease = state
    before = (root / "jobs.sqlite3").read_bytes()
    output, created = snapshot(state, tmp_path)
    assert (root / "jobs.sqlite3").read_bytes() == before
    assert output.stat().st_mode & 0o777 == 0o600
    verified = restore_snapshot(
        output, None, key_file=root / "key", expected_sha256=created.snapshot_sha256
    )
    assert verified.copied_leases_fenced == 0
    assert verified.source_audit_head_sha256 == verified.current_audit_head_sha256
    destination = tmp_path / "restored"
    recovered = restore_snapshot(
        output, destination, key_file=root / "key", expected_sha256=created.snapshot_sha256
    )
    assert recovered.copied_leases_fenced == 1
    assert recovered.job_count == 3 and recovered.artifact_count == 1
    assert recovered.current_audit_head_sha256 != recovered.source_audit_head_sha256
    restored = JobStore(destination / "jobs.sqlite3")
    assert restored.get(active, owner="alice").status == "queued"
    assert restored.get(queued, owner="bob").status == "queued"
    assert JobStore(root / "jobs.sqlite3").get(active, owner="alice").status == "running"
    with pytest.raises(LeaseLost):
        restored.heartbeat(lease)
    old = restored.get(complete, owner="alice")
    artifact = ArtifactStore(destination / "artifacts").get(old.artifact_sha256)
    assert replay_evidence_bundle(artifact, require_integrity=True).matches
    assert not (destination / "auth.json").exists() and not (destination / "key").exists()
    assert not list(tmp_path.glob(".prometheus-restore-*"))
    assert not list(tmp_path.glob(".prometheus-snapshot-*"))
    done = Worker(
        restored, ArtifactStore(destination / "artifacts"), worker_id="restored-worker"
    ).run_once()
    assert done.job_id == active and done.status == "succeeded" and done.attempts == 2
    assert restored.verify_audit_chain() != recovered.current_audit_head_sha256


def test_rel_11_restored_artifacts_are_readable_and_hash_consistent(state, tmp_path):
    """REL-11: "run backup restore and integrity validation ... restore
    artifacts are readable and hash-consistent." States that claim
    explicitly rather than inferring it from the scattered assertions in
    the test above: after a genuine create_snapshot/restore_snapshot
    round trip, the restored artifact is read by its own content digest
    (ArtifactStore.get re-verifies the hash on every read, via
    `audit_evidence_bundle`) AND, independently of that internal check,
    this test itself recomputes `artifact_content_hash` directly on the
    returned body and confirms it still equals the very digest the
    artifact was addressed by -- an artifact here is content-addressed
    by a canonical-JSON hash of its parsed body, not a raw-byte file
    hash (re-serializing changes whitespace/formatting but not meaning),
    so that is the correct, and only correct, notion of "hash-consistent"
    for this store."""
    root, complete, active, queued, lease = state
    output, created = snapshot(state, tmp_path)
    destination = tmp_path / "restored"
    restore_snapshot(
        output, destination, key_file=root / "key", expected_sha256=created.snapshot_sha256
    )

    restored_jobs = JobStore(destination / "jobs.sqlite3")
    completed_job = restored_jobs.get(complete, owner="alice")
    artifact_digest = completed_job.artifact_sha256
    assert artifact_digest is not None

    restored_artifacts = ArtifactStore(destination / "artifacts")
    body = restored_artifacts.get(artifact_digest)  # readable
    assert isinstance(body, dict)

    independent_digest = artifact_content_hash(body)
    assert independent_digest == artifact_digest  # hash-consistent


def test_encryption_nonce_varies_and_only_referenced_database_objects_are_included(state, tmp_path):
    root = state[0]
    first, _ = snapshot(state, tmp_path)
    second = tmp_path / "second.enc"
    create_snapshot(root, second, key_file=root / "key")
    assert first.read_bytes()[: len(MAGIC)] == MAGIC
    assert (
        first.read_bytes()[len(MAGIC) : len(MAGIC) + 12]
        != second.read_bytes()[len(MAGIC) : len(MAGIC) + 12]
    )
    manifest, content = plaintext(first, read_key(root / "key"))
    assert [item["path"] for item in manifest["files"]][0] == "jobs.sqlite3"
    assert len(manifest["files"]) == 2
    assert b"credential-canary" not in content
    assert b"payroll_target" not in first.read_bytes()


@pytest.mark.parametrize("position", [0, len(MAGIC), len(MAGIC) + 20, -1])
def test_tampering_never_parses_plaintext_or_publishes_a_directory(
    state, tmp_path, monkeypatch, position
):
    output, _ = snapshot(state, tmp_path)
    data = bytearray(output.read_bytes())
    data[position] ^= 1
    output.write_bytes(data)
    import prometheus.recovery.snapshot as module

    def forbidden(*args, **kwargs):
        pytest.fail("unauthenticated content must never be parsed")

    monkeypatch.setattr(module, "_manifest_validate", forbidden)
    destination = tmp_path / "restored"
    with pytest.raises(RecoveryError):
        restore_snapshot(output, destination, key_file=state[0] / "key")
    assert not destination.exists() and not list(tmp_path.glob(".prometheus-restore-*"))


def test_wrong_key_external_pin_and_truncation_preserve_existing_state(state, tmp_path):
    output, _ = snapshot(state, tmp_path)
    key = tmp_path / "wrong-key"
    generate_key(key)
    with pytest.raises(RecoveryError, match="authentication"):
        restore_snapshot(output, tmp_path / "restored", key_file=key)
    with pytest.raises(RecoveryError, match="checkpoint"):
        restore_snapshot(
            output, tmp_path / "restored", key_file=state[0] / "key", expected_sha256="0" * 64
        )
    data = output.read_bytes()
    for length in (0, 8, 20, 25, len(data) - 1):
        output.write_bytes(data[:length])
        with pytest.raises(RecoveryError):
            restore_snapshot(output, tmp_path / "restored", key_file=state[0] / "key")
    assert not (tmp_path / "restored").exists()


@pytest.mark.parametrize(
    "change",
    [
        lambda m, c: m.update(schema_version=True),
        lambda m, c: m.update(extra="forbidden"),
        lambda m, c: m.update(job_count=True),
        lambda m, c: m.update(event_count=10**9),
        lambda m, c: m.update(status_counts={"invalid": 3}),
        lambda m, c: m.update(created_at="2026-11-03"),
        lambda m, c: m.update(runtime={"fake": True}),
        lambda m, c: m.update(queue_policy={}),
        lambda m, c: m["files"][0].update(path="../../outside"),
        lambda m, c: m["files"][0].update(path="/absolute"),
        lambda m, c: m["files"][0].update(size_bytes=True),
        lambda m, c: m["files"][0].update(sha256="0" * 64),
        lambda m, c: m["files"].append(dict(m["files"][0])),
        lambda m, c: m["files"][1].update(path="artifacts/00/" + "f" * 64 + ".json"),
    ],
)
def test_even_authenticated_malformed_snapshots_are_rejected_before_publication(
    state, tmp_path, change
):
    original, _ = snapshot(state, tmp_path)
    malformed = tmp_path / "malformed.enc"
    forge(original, read_key(state[0] / "key"), malformed, change)
    with pytest.raises(RecoveryError):
        restore_snapshot(malformed, tmp_path / "restored", key_file=state[0] / "key")
    assert not (tmp_path / "restored").exists() and not (tmp_path.parent / "outside").exists()


def test_authenticated_database_projection_tampering_is_detected(state, tmp_path):
    original, _ = snapshot(state, tmp_path)

    def corrupt_database(manifest, content):
        size = manifest["files"][0]["size_bytes"]
        database = tmp_path / "tampered.sqlite3"
        database.write_bytes(content[:size])
        with closing(sqlite3.connect(database, isolation_level=None)) as connection:
            connection.execute("UPDATE jobs SET version=version+1 WHERE job_id=?", (state[1],))
        changed = database.read_bytes()
        manifest["files"][0].update(
            size_bytes=len(changed), sha256=hashlib.sha256(changed).hexdigest()
        )
        return changed + content[size:]

    malformed = tmp_path / "tampered.enc"
    forge(original, read_key(state[0] / "key"), malformed, corrupt_database)
    with pytest.raises(RecoveryError):
        restore_snapshot(malformed, tmp_path / "restored", key_file=state[0] / "key")
    assert not (tmp_path / "restored").exists()


def test_missing_referenced_object_and_undeclared_trailing_content_are_rejected(state, tmp_path):
    original, _ = snapshot(state, tmp_path)

    def remove_object(manifest, content):
        manifest["files"] = manifest["files"][:1]
        return content[: manifest["files"][0]["size_bytes"]]

    missing, trailing = tmp_path / "missing.enc", tmp_path / "trailing.enc"
    forge(original, read_key(state[0] / "key"), missing, remove_object)
    forge(original, read_key(state[0] / "key"), trailing, lambda m, c: c + b"undeclared")
    for source in (missing, trailing):
        with pytest.raises(RecoveryError):
            restore_snapshot(source, tmp_path / "restored", key_file=state[0] / "key")


def test_restore_and_snapshot_refuse_to_overwrite_even_empty_destinations(state, tmp_path):
    output, _ = snapshot(state, tmp_path)
    before = output.read_bytes()
    with pytest.raises(RecoveryError):
        create_snapshot(state[0], output, key_file=state[0] / "key")
    destination = tmp_path / "restored"
    destination.mkdir()
    with pytest.raises(RecoveryError):
        restore_snapshot(output, destination, key_file=state[0] / "key")
    assert output.read_bytes() == before and list(destination.iterdir()) == []


def test_atomic_restore_publication_cannot_replace_a_destination_created_during_verification(
    state, tmp_path, monkeypatch
):
    import prometheus.recovery.snapshot as module

    output, _ = snapshot(state, tmp_path)
    destination = tmp_path / "restored"
    original = module._publish_directory

    def concurrent_creator(staging, target):
        target.mkdir()
        original(staging, target)

    monkeypatch.setattr(module, "_publish_directory", concurrent_creator)
    with pytest.raises(RecoveryError):
        restore_snapshot(output, destination, key_file=state[0] / "key")
    assert list(destination.iterdir()) == []


def test_private_binary_keys_reject_modes_symlinks_fifos_and_wrong_lengths(tmp_path):
    key = tmp_path / "key"
    generate_key(key)
    before = key.read_bytes()
    with pytest.raises(FileExistsError):
        generate_key(key)
    assert key.read_bytes() == before and len(read_key(key)) == 32
    key.chmod(0o644)
    with pytest.raises(RecoveryError):
        read_key(key)
    key.chmod(0o600)
    link = tmp_path / "link"
    link.symlink_to(key)
    with pytest.raises(RecoveryError):
        read_key(link)
    fifo = tmp_path / "fifo"
    os.mkfifo(fifo, 0o600)
    with pytest.raises(RecoveryError):
        read_key(fifo)
    key.write_bytes(b"short")
    with pytest.raises(RecoveryError):
        read_key(key)


def test_budgets_fail_without_published_snapshot_or_restore(state, tmp_path):
    output, _ = snapshot(state, tmp_path)
    for limits in (
        RecoveryLimits(max_snapshot_bytes=32),
        RecoveryLimits(max_database_bytes=1),
        RecoveryLimits(max_manifest_bytes=8),
        RecoveryLimits(max_jobs=1),
        RecoveryLimits(operation_seconds=1e-9),
    ):
        with pytest.raises(RecoveryError):
            restore_snapshot(
                output, tmp_path / "restored", key_file=state[0] / "key", limits=limits
            )
        assert not (tmp_path / "restored").exists()
    with pytest.raises(RecoveryError):
        create_snapshot(
            state[0],
            tmp_path / "too-small.enc",
            key_file=state[0] / "key",
            limits=RecoveryLimits(max_snapshot_bytes=32),
        )
    assert not (tmp_path / "too-small.enc").exists()


def test_requested_cancellation_and_exhausted_attempts_are_terminal_on_restore(tmp_path):
    root = tmp_path / "source"
    policy = QueuePolicy(max_attempts=1)
    store = JobStore(root / "jobs.sqlite3", policy=policy)
    ArtifactStore(root / "artifacts")
    first = store.submit("economy", default_recipe("economy"), owner="alice")
    store.claim("worker-1")
    second = store.submit("economy", default_recipe("economy"), owner="alice")
    store.claim("worker-2")
    store.cancel(second.job_id, owner="alice")
    key = tmp_path / "key"
    generate_key(key)
    output = tmp_path / "snapshot.enc"
    create_snapshot(root, output, key_file=key)
    restored_root = tmp_path / "restored"
    result = restore_snapshot(output, restored_root, key_file=key)
    restored = JobStore(restored_root / "jobs.sqlite3", policy=policy)
    assert result.copied_leases_fenced == 2
    failed = restored.get(first.job_id, owner="alice")
    assert failed.status == "failed" and failed.error_code == "restore_interrupted"
    assert restored.get(second.job_id, owner="alice").status == "cancelled"
    assert restored.verify_audit_chain() == result.current_audit_head_sha256


def test_cli_reports_receipts_without_printing_keys_or_recipes(state, tmp_path, capsys):
    root = state[0]
    key, output, restored = tmp_path / "new.key", tmp_path / "snapshot.enc", tmp_path / "restored"
    assert main(["keygen", "--output", str(key)]) == 0
    assert (
        main(["create", "--root", str(root), "--output", str(output), "--key-file", str(key)]) == 0
    )
    assert main(["verify", "--input", str(output), "--key-file", str(key)]) == 0
    assert (
        main(
            [
                "restore",
                "--input",
                str(output),
                "--key-file",
                str(key),
                "--destination",
                str(restored),
            ]
        )
        == 0
    )
    text = capsys.readouterr().out
    assert "payroll_target" not in text and key.read_bytes().hex() not in text


def test_source_corruption_refuses_backup_and_preserves_old_snapshot(state, tmp_path):
    output, _ = snapshot(state, tmp_path)
    before = output.read_bytes()
    store = JobStore(state[0] / "jobs.sqlite3")
    job = store.get(state[1], owner="alice")
    path = ArtifactStore(state[0] / "artifacts")._path(job.artifact_sha256)
    path.chmod(0o600)
    path.write_text("corrupt")
    with pytest.raises(ValueError):
        create_snapshot(state[0], tmp_path / "new.enc", key_file=state[0] / "key")
    assert output.read_bytes() == before and not (tmp_path / "new.enc").exists()


def test_online_backup_remains_consistent_while_other_connections_submit_jobs(state, tmp_path):
    root = state[0]
    store = JobStore(root / "jobs.sqlite3")

    def writer():
        for index in range(10):
            store.submit(
                "economy",
                default_recipe("economy"),
                owner="writer",
                idempotency_key=f"concurrent-{index}",
            )
            time.sleep(0.005)

    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(writer)
        output, created = snapshot(state, tmp_path)
        future.result(timeout=5)
    verified = restore_snapshot(output, None, key_file=root / "key")
    assert 3 <= created.job_count <= 13 and verified.job_count == created.job_count
    assert verified.source_audit_head_sha256 == created.source_audit_head_sha256
