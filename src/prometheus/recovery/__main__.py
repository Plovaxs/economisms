"""Local encrypted snapshots: keygen, create, verify and restore to a new root."""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from pathlib import Path

from prometheus.recovery.snapshot import (
    RecoveryError,
    create_snapshot,
    generate_key,
    restore_snapshot,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="action", required=True)
    keygen = commands.add_parser("keygen")
    keygen.add_argument("--output", type=Path, required=True)
    create = commands.add_parser("create")
    create.add_argument("--root", type=Path, required=True)
    create.add_argument("--output", type=Path, required=True)
    create.add_argument("--key-file", type=Path, required=True)
    for name in ("verify", "restore"):
        command = commands.add_parser(name)
        command.add_argument("--input", type=Path, required=True)
        command.add_argument("--key-file", type=Path, required=True)
        command.add_argument("--expected-snapshot-sha256")
        if name == "restore":
            command.add_argument("--destination", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.action == "keygen":
            generate_key(args.output)
            response = {"key_file": str(args.output), "created": True}
        else:
            if args.action == "create":
                receipt = create_snapshot(args.root, args.output, key_file=args.key_file)
            else:
                receipt = restore_snapshot(
                    args.input,
                    args.destination if args.action == "restore" else None,
                    key_file=args.key_file,
                    expected_sha256=args.expected_snapshot_sha256,
                )
            response = asdict(receipt)
        print(json.dumps(response, sort_keys=True, indent=2))
    except (RecoveryError, ValueError, OSError) as exc:
        parser.error(str(exc))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
