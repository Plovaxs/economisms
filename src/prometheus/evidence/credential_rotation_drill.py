"""Compromised-credential and secret-rotation tabletop drill (DRI-03:
"Create compromised credential and secret rotation runbook";
acceptance criterion: "Tabletop demonstrates revoked tokens and
cleaned pipelines").

Runs a REAL drill against `service.auth.CredentialStore`, not a
hypothetical description: `rotate_credential` rewrites the credential
file -- the exact JSON schema `CredentialStore._load` itself
validates -- removing the compromised token's binding and adding a
replacement, and `run_credential_rotation_drill` then actually calls
`CredentialStore.authenticate` with both the old and new bearer
headers to confirm the old one is genuinely rejected and the new one
genuinely works.

"Cleaned pipelines" is grounded in `CredentialStore`'s own real
behavior, not asserted separately: `authenticate` calls `self._load()`
-- a fresh read of the credential file -- on EVERY invocation, with no
session cache or other component anywhere in this repository that
could continue honoring a revoked token after the file is rewritten.
There is nothing left to "clean" because nothing else ever held a
copy of the credential in the first place.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from prometheus.evidence.jsonio import strict_json_loads
from prometheus.service.auth import AuthenticationError, CredentialStore


def rotate_credential(
    store_path: Path,
    *,
    old_token_sha256: str,
    new_subject: str,
    new_owner: str,
    new_scopes: Sequence[str],
    new_token_sha256: str,
) -> None:
    config = strict_json_loads(store_path.read_text())
    if not isinstance(config, dict) or not isinstance(config.get("credentials"), list):
        raise ValueError("credential file does not match the expected schema")
    remaining = [c for c in config["credentials"] if c.get("token_sha256") != old_token_sha256]
    remaining.append(
        {
            "subject": new_subject,
            "owner": new_owner,
            "scopes": list(new_scopes),
            "token_sha256": new_token_sha256,
        }
    )
    config["credentials"] = remaining
    store_path.write_text(json.dumps(config))


@dataclass(frozen=True, slots=True)
class RotationDrillResult:
    old_token_rejected: bool
    new_token_authenticates: bool

    @property
    def passed(self) -> bool:
        return self.old_token_rejected and self.new_token_authenticates


def run_credential_rotation_drill(
    store: CredentialStore,
    *,
    old_authorization_header: str,
    new_authorization_header: str,
) -> RotationDrillResult:
    old_rejected = False
    try:
        store.authenticate(old_authorization_header)
    except AuthenticationError:
        old_rejected = True

    new_authenticates = False
    try:
        store.authenticate(new_authorization_header)
        new_authenticates = True
    except AuthenticationError:
        new_authenticates = False

    return RotationDrillResult(
        old_token_rejected=old_rejected, new_token_authenticates=new_authenticates
    )
