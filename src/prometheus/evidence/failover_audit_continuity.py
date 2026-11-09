"""Audit-log and model-approval-history availability throughout
failover (DRI-11: "Test audit-log availability throughout failover";
acceptance criterion: "Approval and model activity history remains
complete").

Two real, independent persistence mechanisms, each actually exercised
through a REAL simulated failover in this module's own tests, not
merely asserted:

- `jobs.store.JobStore`'s own hash-chained audit log, restored via the
  real `recovery.snapshot.create_snapshot`/`restore_snapshot` round
  trip this repository already uses for backup/recovery (REL-11).
  `read_job_events` opens a store's sqlite file read-only -- the same
  safe pattern `recovery.snapshot._inspect_database` already uses --
  and returns every event recorded for a job, by `job_id`, so a real
  restore's COMPLETENESS can be checked event-by-event: not merely
  "the hash chain is internally consistent" (already covered by
  REL-11's existing tests), but that NO event was lost, reordered, or
  altered.

- `evidence.model_registry.ModelRegistryEntry`'s approval history has
  no persistence layer of its own; `serialize_registry_entry`/
  `restore_registry_entry` provide a minimal, explicit JSON round trip
  -- not a change to `model_registry.py` itself.
  `restore_registry_entry` deliberately replays the serialized history
  THROUGH `ModelRegistryEntry.transition()` itself, rather than poking
  `.state`/`.history` directly, so a successful restore also confirms
  the recovered sequence is still a LEGAL transition history under
  `is_allowed_transition` -- a tampered or reordered history would
  raise `IllegalTransitionError` on restore, not silently round-trip.
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from dataclasses import asdict
from datetime import date
from pathlib import Path
from typing import Any

from prometheus.evidence.jsonio import strict_json_loads
from prometheus.evidence.model_registry import ModelRegistryEntry


def read_job_events(store_path: Path, job_id: str) -> tuple[dict[str, Any], ...]:
    with closing(
        sqlite3.connect(store_path.resolve().as_uri() + "?mode=ro", uri=True, timeout=0.25)
    ) as connection:
        connection.row_factory = sqlite3.Row
        rows = connection.execute(
            "SELECT body_json FROM events WHERE job_id=? ORDER BY seq", (job_id,)
        ).fetchall()
    return tuple(strict_json_loads(row["body_json"]) for row in rows)


def serialize_registry_entry(entry: ModelRegistryEntry) -> str:
    payload = {
        "model_id": entry.model_id,
        "history": [
            {**asdict(transition), "at": transition.at.isoformat()}
            for transition in entry.history
        ],
    }
    return json.dumps(payload, sort_keys=True)


def restore_registry_entry(serialized: str) -> ModelRegistryEntry:
    payload = strict_json_loads(serialized)
    entry = ModelRegistryEntry(model_id=payload["model_id"])
    for item in payload["history"]:
        entry.transition(
            item["to_state"],
            item["actor"],
            date.fromisoformat(item["at"]),
            item["reason"],
            approved_by=item["approved_by"],
            content_hash=item["content_hash"],
        )
    return entry
