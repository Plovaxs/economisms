"""Private-file hashed service credentials with per-request rotation/revocation.

This is local service-token authentication, not an OIDC/SSO or vault claim.
Plain tokens are never persisted by this reader or returned in diagnostics.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import re
import stat
from dataclasses import dataclass
from pathlib import Path

from prometheus.evidence.integrity import is_sha256
from prometheus.evidence.jsonio import strict_json_loads


class AuthenticationError(ValueError):
    pass


class CredentialUnavailable(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class Principal:
    subject: str
    owner: str
    scopes: frozenset[str]


class CredentialStore:
    def __init__(self, path: Path) -> None:
        self.path = path.absolute()
        self._load()  # Refuse invalid startup configuration.

    def check_ready(self) -> None:
        self._load()

    def _load(self) -> tuple[tuple[str, Principal], ...]:
        try:
            flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
            with os.fdopen(os.open(self.path, flags), "rb") as stream:
                info = os.fstat(stream.fileno())
                if (
                    not stat.S_ISREG(info.st_mode)
                    or info.st_uid != os.getuid()
                    or info.st_mode & 0o077
                    or info.st_size > 65_536
                ):
                    raise ValueError("credentials require a private bounded owner-controlled file")
                raw = stream.read(65_537)
            if len(raw) > 65_536:
                raise ValueError("credential file exceeds byte budget")
            config = strict_json_loads(raw.decode("utf-8"))
            if (
                not isinstance(config, dict)
                or set(config) != {"schema_version", "credentials"}
                or type(config["schema_version"]) is not int
                or config["schema_version"] != 1
                or not isinstance(config["credentials"], list)
                or not 1 <= len(config["credentials"]) <= 128
            ):
                raise ValueError("invalid credential schema")
            bindings: list[tuple[str, Principal]] = []
            for item in config["credentials"]:
                if not isinstance(item, dict) or set(item) != {
                    "subject",
                    "owner",
                    "scopes",
                    "token_sha256",
                }:
                    raise ValueError("invalid credential fields")
                for name in ("subject", "owner"):
                    if (
                        not isinstance(item[name], str)
                        or re.fullmatch(r"[A-Za-z0-9._:@-]{1,128}", item[name]) is None
                    ):
                        raise ValueError("invalid credential identity")
                scopes = item["scopes"]
                if (
                    not isinstance(scopes, list)
                    or not scopes
                    or any(scope not in ("read", "write") for scope in scopes)
                    or len(scopes) != len(set(scopes))
                    or "read" not in scopes
                    or not is_sha256(item["token_sha256"])
                    or any(digest == item["token_sha256"] for digest, _ in bindings)
                ):
                    raise ValueError("invalid credential scopes or digest")
                bindings.append(
                    (
                        item["token_sha256"],
                        Principal(item["subject"], item["owner"], frozenset(scopes)),
                    )
                )
            return tuple(bindings)
        except (OSError, ValueError, TypeError, UnicodeError, RecursionError) as exc:
            raise CredentialUnavailable("service credentials are unavailable") from exc

    def authenticate(self, authorization: str | None) -> Principal:
        if (
            authorization is None
            or re.fullmatch(r"Bearer [A-Za-z0-9_-]{43,128}", authorization) is None
        ):
            raise AuthenticationError("valid bearer credentials are required")
        digest = hashlib.sha256(authorization[7:].encode("ascii")).hexdigest()
        matched = None
        for expected, principal in self._load():
            if hmac.compare_digest(expected, digest):
                matched = principal
        if matched is None:
            raise AuthenticationError("valid bearer credentials are required")
        return matched
