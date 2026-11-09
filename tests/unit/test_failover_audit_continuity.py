import json
from datetime import date

import pytest

from prometheus.evidence.failover_audit_continuity import (
    read_job_events,
    restore_registry_entry,
    serialize_registry_entry,
)
from prometheus.evidence.model_registry import IllegalTransitionError, ModelRegistryEntry
from prometheus.jobs.artifacts import ArtifactStore
from prometheus.jobs.store import JobStore
from prometheus.jobs.worker import Worker
from prometheus.orchestration.recipes import default_recipe
from prometheus.recovery.snapshot import create_snapshot, generate_key, restore_snapshot


def test_a_real_failover_round_trip_preserves_every_audit_event_for_a_job(tmp_path) -> None:
    """A REAL simulated failover: submit and complete a real job
    (building a real submitted/claimed/finished event trail), snapshot
    the store via the actual `recovery.snapshot.create_snapshot`/
    `restore_snapshot` round trip this repository already uses for
    backup/recovery, and confirm the restored store's job event
    history is IDENTICAL -- not merely that the hash chain still
    verifies (REL-11 already covers that), but that every individual
    event body survived byte-for-byte."""
    source = tmp_path / "source"
    source.mkdir()
    store = JobStore(source / "jobs.sqlite3")
    objects = ArtifactStore(source / "artifacts")
    config = default_recipe("economy")
    config.update(n_steps=2, productivity_shock_step=2)
    job = store.submit("economy", config, owner="alice", idempotency_key="k")
    result = Worker(store, objects, worker_id="w").run_once()
    assert result.status == "succeeded"

    events_before = read_job_events(source / "jobs.sqlite3", job.job_id)
    assert [e["event"] for e in events_before] == ["submitted", "claimed", "finished"]

    key = tmp_path / "key"
    generate_key(key)
    snapshot_path = tmp_path / "snapshot.enc"
    create_snapshot(source, snapshot_path, key_file=key)

    destination = tmp_path / "restored"
    receipt = restore_snapshot(snapshot_path, destination, key_file=key)
    assert receipt.source_audit_head_sha256 == receipt.current_audit_head_sha256

    events_after = read_job_events(destination / "jobs.sqlite3", job.job_id)
    assert events_after == events_before


def test_a_real_model_approval_history_survives_a_full_serialize_restore_round_trip() -> None:
    """A real candidate -> evaluated -> approved lifecycle, including
    a real content_hash on the approval transition (AUD-06's own
    requirement), restored through a full JSON round trip and
    REPLAYED through `transition()` itself -- confirming both the
    data and the legality of the restored sequence."""
    entry = ModelRegistryEntry(model_id="hedge-policy-v3")
    entry.transition(
        "evaluated", "quant-lead", date(2026, 1, 1), "backtest passed", approved_by="quant-lead"
    )
    entry.transition(
        "approved", "risk-lead", date(2026, 1, 5), "promoted after review",
        approved_by="risk-lead", content_hash="a" * 64,
    )

    serialized = serialize_registry_entry(entry)
    restored = restore_registry_entry(serialized)

    assert restored.model_id == entry.model_id
    assert restored.state == entry.state == "approved"
    assert restored.history == entry.history
    assert restored.history[-1].approved_by == "risk-lead"
    assert restored.history[-1].content_hash == "a" * 64


def test_a_tampered_history_order_fails_to_restore_rather_than_silently_round_tripping() -> None:
    """The discriminating half: if the serialized history were
    corrupted into an illegal order (approved before evaluated),
    `restore_registry_entry` must raise, not silently reconstruct an
    entry with a history that could never have legally occurred."""
    entry = ModelRegistryEntry(model_id="m")
    entry.transition(
        "evaluated", "a", date(2026, 1, 1), "r", approved_by="a"
    )
    entry.transition(
        "approved", "b", date(2026, 1, 2), "r", approved_by="b", content_hash="0" * 64
    )
    serialized = serialize_registry_entry(entry)
    payload = json.loads(serialized)
    payload["history"] = list(reversed(payload["history"]))  # approved first -- illegal
    tampered = json.dumps(payload)

    with pytest.raises(IllegalTransitionError):
        restore_registry_entry(tampered)
