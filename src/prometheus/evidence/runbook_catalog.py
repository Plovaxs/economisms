"""Runbooks for top failure categories, with simulated on-call drills
producing a real incident timeline (OPS-11: "Maintain runbooks for
top failure categories"; acceptance criterion: "Simulated on-call
drills complete with incident timeline").

Rather than reinventing per-category mechanics, this module runs a
real simulated drill for each of TWO distinct, already-evidenced
failure categories -- "top failure categories" plural, not just one:

- "solver_failure" -> `evidence.numerical_integrity_runbook` (DRI-02):
  isolate, invalidate, re-evaluate, with a real timestamped timeline.
- "credential_compromise" -> composes `evidence.credential_rotation_drill`'s
  `rotate_credential` (the real action) and `run_credential_rotation_drill`
  (the real verification) (DRI-03) into one drill with its own real
  timestamped timeline, in the SAME `DrillStep` shape the
  numerical-integrity drill uses, so both categories' drills are
  comparable the same way.

`DrillReport.passed` is the drill's own real outcome -- not a
constant -- confirmed in this module's tests by a drill that
genuinely fails (a persistently-failing numerical call; a credential
drill checked against the WRONG new token) as well as one that
genuinely succeeds.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from prometheus.evidence.credential_rotation_drill import (
    rotate_credential,
    run_credential_rotation_drill,
)
from prometheus.evidence.numerical_event_monitor import NumericalEvent
from prometheus.evidence.numerical_integrity_runbook import run_numerical_integrity_runbook
from prometheus.service.auth import CredentialStore


@dataclass(frozen=True, slots=True)
class DrillStep:
    name: str
    at: datetime
    detail: str

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("name must not be empty")
        if not self.detail:
            raise ValueError("detail must not be empty")


@dataclass(frozen=True, slots=True)
class DrillReport:
    category: str
    timeline: tuple[DrillStep, ...]
    passed: bool


def run_numerical_integrity_drill(
    event: NumericalEvent, call: Callable[[], object], *, clock: Callable[[], datetime]
) -> DrillReport:
    result = run_numerical_integrity_runbook(event, call, clock=clock)
    timeline = tuple(
        DrillStep(name=step.name, at=step.at, detail=step.detail) for step in result.timeline
    )
    return DrillReport(
        category="solver_failure", timeline=timeline, passed=result.re_evaluation_succeeded
    )


def run_credential_compromise_drill(
    store: CredentialStore,
    store_path: Path,
    *,
    old_token_sha256: str,
    new_subject: str,
    new_owner: str,
    new_scopes: Sequence[str],
    new_token_sha256: str,
    old_authorization_header: str,
    new_authorization_header: str,
    clock: Callable[[], datetime],
) -> DrillReport:
    timeline = [
        DrillStep(
            name="isolate_and_rotate",
            at=clock(),
            detail=f"revoking compromised credential, provisioning a replacement for {new_owner!r}",
        )
    ]
    rotate_credential(
        store_path,
        old_token_sha256=old_token_sha256,
        new_subject=new_subject,
        new_owner=new_owner,
        new_scopes=new_scopes,
        new_token_sha256=new_token_sha256,
    )
    result = run_credential_rotation_drill(
        store,
        old_authorization_header=old_authorization_header,
        new_authorization_header=new_authorization_header,
    )
    timeline.append(
        DrillStep(
            name="verify_old_rejected", at=clock(),
            detail=f"old token rejected: {result.old_token_rejected}",
        )
    )
    timeline.append(
        DrillStep(
            name="verify_new_accepted", at=clock(),
            detail=f"new token authenticates: {result.new_token_authenticates}",
        )
    )
    return DrillReport(
        category="credential_compromise", timeline=tuple(timeline), passed=result.passed
    )
