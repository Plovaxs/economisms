"""A generic, tamper-evident hash-chained log (AUD-07: "keep
access-control changes and privileged actions logged"; acceptance
criterion: "regular audit review confirms tamper-evident retention").

Reuses the SAME hash-chaining technique `jobs.store.JobStore.
verify_audit_chain` already established for job-lifecycle events
(confirmed directly by reading its own implementation: each entry's
hash covers the previous entry's hash plus its own event body, exactly
as here) -- generalized to any caller-supplied event payload, not
duplicating that job-specific fixed schema. Access-control changes and
privileged actions have no natural home in a job-lifecycle-specific
audit chain, so this module gives them the same tamper-evidence
technique in their own right.

`append` is the only way to add an entry; there is deliberately no
"edit" or "delete" method, so the only way an entry's content could
ever differ from what `append` originally wrote is by modifying the
stored data directly, bypassing this class entirely -- exactly the
scenario `verify` exists to catch: it re-derives every entry's hash
from scratch and raises `TamperEvidenceError` at the first link that no
longer matches, rather than trusting the stored `event_sha256` values
at face value.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from prometheus.experiments.manifest import compute_result_hash

_GENESIS_HASH = "0" * 64


class TamperEvidenceError(ValueError):
    """Raised by `verify` at the first entry whose hash no longer
    matches what `append` would have computed for it."""


@dataclass(frozen=True, slots=True)
class LogEntry:
    seq: int
    previous_sha256: str
    event: Mapping[str, Any]
    event_sha256: str


@dataclass(slots=True)
class TamperEvidentLog:
    entries: list[LogEntry] = field(default_factory=list, init=False)

    def append(self, event: Mapping[str, Any]) -> LogEntry:
        previous = self.entries[-1].event_sha256 if self.entries else _GENESIS_HASH
        event_copy = dict(event)
        event_sha256 = compute_result_hash({"previous_sha256": previous, "event": event_copy})
        entry = LogEntry(
            seq=len(self.entries) + 1,
            previous_sha256=previous,
            event=event_copy,
            event_sha256=event_sha256,
        )
        self.entries.append(entry)
        return entry

    def verify(self) -> str:
        """Re-walks every entry, re-deriving each hash from scratch
        rather than trusting the stored one, and returns the head hash
        if the whole chain verifies. Raises `TamperEvidenceError` at
        the first entry whose linkage or content hash no longer
        matches -- "regular audit review," run as often as a caller
        likes."""
        previous = _GENESIS_HASH
        for entry in self.entries:
            expected = compute_result_hash({"previous_sha256": previous, "event": entry.event})
            if entry.previous_sha256 != previous or entry.event_sha256 != expected:
                raise TamperEvidenceError(
                    f"audit chain broken at seq={entry.seq}: recorded hash no longer "
                    "matches the entry's own content -- the log has been tampered with"
                )
            previous = expected
        return previous
