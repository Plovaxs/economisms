"""Run the research API with private service credentials and separate workers."""

from __future__ import annotations

import argparse
import hashlib
import ipaddress
import json
import logging
import os
import re
import secrets
from pathlib import Path

from prometheus.jobs.artifacts import ArtifactStore
from prometheus.jobs.store import JobStore
from prometheus.service.application import ResearchService
from prometheus.service.auth import CredentialStore
from prometheus.service.schema import openapi_document


def provision_credentials(path: Path, token_file: Path, *, owner: str, read_only: bool) -> None:
    if re.fullmatch(r"[A-Za-z0-9._:@-]{1,128}", owner) is None:
        raise ValueError("owner requires a bounded opaque identity")
    if path.absolute() == token_file.absolute():
        raise ValueError("token and credential paths must differ")
    token = secrets.token_urlsafe(32)
    config = {
        "schema_version": 1,
        "credentials": [
            {
                "subject": owner,
                "owner": owner,
                "scopes": ["read"] if read_only else ["read", "write"],
                "token_sha256": hashlib.sha256(token.encode("ascii")).hexdigest(),
            }
        ],
    }
    created: list[Path] = []
    try:
        for target, text in ((token_file, token + "\n"), (path, json.dumps(config, indent=2))):
            target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            descriptor = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            created.append(target)
            with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
                stream.write(text)
                stream.flush()
                os.fsync(stream.fileno())
    except BaseException:
        for target in created:
            target.unlink(missing_ok=True)
        raise


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="action", required=True)
    setup = commands.add_parser("init-auth")
    setup.add_argument("--credentials", type=Path, required=True)
    setup.add_argument("--token-file", type=Path, required=True)
    setup.add_argument("--owner", required=True)
    setup.add_argument("--read-only", action="store_true")
    schema = commands.add_parser("openapi")
    schema.add_argument("--output", type=Path, required=True)
    serve = commands.add_parser("serve")
    serve.add_argument("--root", type=Path, required=True)
    serve.add_argument("--credentials", type=Path, required=True)
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8765)
    serve.add_argument("--tls-cert", type=Path)
    serve.add_argument("--tls-key", type=Path)
    args = parser.parse_args(argv)
    try:
        if args.action == "init-auth":
            provision_credentials(
                args.credentials, args.token_file, owner=args.owner, read_only=args.read_only
            )
            print(
                json.dumps(
                    {"credentials": str(args.credentials), "token_file": str(args.token_file)}
                )
            )
        elif args.action == "openapi":
            args.output.parent.mkdir(parents=True, exist_ok=True)
            with args.output.open("x", encoding="utf-8") as stream:
                json.dump(openapi_document(), stream, indent=2, sort_keys=True, allow_nan=False)
        else:
            address = ipaddress.ip_address(args.host)
            if not 0 <= args.port <= 65535:
                raise ValueError("port must be in [0,65535]")
            if bool(args.tls_cert) != bool(args.tls_key):
                raise ValueError("TLS requires both certificate and key")
            if not address.is_loopback and args.tls_cert is None:
                raise ValueError("non-loopback binding requires TLS")
            credentials = CredentialStore(args.credentials)
            jobs = JobStore(args.root / "jobs.sqlite3")
            artifacts = ArtifactStore(
                args.root / "artifacts",
                max_bytes=jobs.policy.max_artifact_bytes,
                max_total_bytes=jobs.policy.max_store_bytes,
            )
            app = ResearchService(jobs, artifacts, credentials)
            import uvicorn

            logging.basicConfig(level=logging.INFO, format="%(message)s")
            uvicorn.run(
                app,
                host=args.host,
                port=args.port,
                workers=1,
                loop="asyncio",
                http="h11",
                ws="none",
                interface="asgi3",
                lifespan="on",
                proxy_headers=False,
                access_log=False,
                limit_concurrency=32,
                backlog=64,
                timeout_keep_alive=5,
                timeout_graceful_shutdown=20,
                h11_max_incomplete_event_size=16384,
                ssl_certfile=str(args.tls_cert) if args.tls_cert else None,
                ssl_keyfile=str(args.tls_key) if args.tls_key else None,
            )
    except (ValueError, OSError) as exc:
        parser.error(str(exc))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
