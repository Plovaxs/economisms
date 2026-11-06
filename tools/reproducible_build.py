"""Build and compare two wheels from independent, explicit source snapshots.

Uses the project's locked build group in a fresh private environment. No
credentials/state directory or arbitrary repository files enter snapshots.
The JSON receipt records local repeatability, not signatures or approval.
"""

from __future__ import annotations

import argparse
import base64
import csv
import hashlib
import io
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import tomllib
import zipfile
from pathlib import Path
from typing import Any

SOURCE_DATE_EPOCH = 946684800
ROOT_INPUTS = (
    "pyproject.toml",
    "uv.lock",
    ".python-version",
    "README.md",
    "LICENSE",
    "tools/reproducible_build.py",
)


def digest_file(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1_048_576), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def source_manifest(project: Path) -> dict[str, str]:
    paths = [project / name for name in ROOT_INPUTS]
    paths.extend(sorted((project / "src/prometheus").rglob("*.py")))
    if not (project / "src/prometheus/__init__.py").is_file():
        raise ValueError("project must contain the PROMETHEUS package")
    result = {}
    for path in paths:
        if path.is_symlink() or not path.is_file() or path.resolve() != path.absolute():
            raise ValueError("build inputs require regular files without symlink traversal")
        result[path.relative_to(project).as_posix()] = digest_file(path)
    return dict(sorted(result.items()))


def snapshot_source(project: Path, target: Path, expected: dict[str, str], *, mtime: int) -> None:
    target.mkdir(mode=0o700)
    for name, digest in expected.items():
        source, destination = project / name, target / name
        destination.parent.mkdir(mode=0o755, parents=True, exist_ok=True)
        flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK
        with os.fdopen(os.open(source, flags), "rb") as original:
            if not stat.S_ISREG(os.fstat(original.fileno()).st_mode):
                raise ValueError("snapshot source must remain a regular file")
            with destination.open("xb") as copied:
                shutil.copyfileobj(original, copied)
        destination.chmod(0o644)
        os.utime(destination, (mtime, mtime))
        if digest_file(destination) != digest:
            raise ValueError("source changed while snapshotting")


def verify_wheel(wheel: Path, snapshot: Path, expected: dict[str, str]) -> int:
    with zipfile.ZipFile(wheel) as archive:
        names = archive.namelist()
        if len(names) != len(set(names)) or any(
            name.startswith("/") or ".." in Path(name).parts or "\\" in name for name in names
        ):
            raise ValueError("wheel contains duplicate or unsafe paths")
        records = [name for name in names if name.endswith(".dist-info/RECORD")]
        if len(records) != 1:
            raise ValueError("wheel must have one RECORD")
        rows = list(csv.reader(io.StringIO(archive.read(records[0]).decode("utf-8"))))
        if (
            any(len(row) != 3 for row in rows)
            or len(rows) != len(names)
            or {row[0] for row in rows} != set(names)
        ):
            raise ValueError("wheel RECORD differs from its members")
        for name, digest, size in rows:
            if name == records[0]:
                if digest or size:
                    raise ValueError("wheel RECORD must not hash itself")
                continue
            data = archive.read(name)
            expected_hash = "sha256=" + base64.urlsafe_b64encode(
                hashlib.sha256(data).digest()
            ).decode().rstrip("=")
            if digest != expected_hash or size != str(len(data)):
                raise ValueError("wheel member failed RECORD verification")
        expected_python = {
            name.removeprefix("src/"): digest
            for name, digest in expected.items()
            if name.startswith("src/") and name.endswith(".py")
        }
        observed_python = {
            name: hashlib.sha256(archive.read(name)).hexdigest()
            for name in names
            if name.endswith(".py")
        }
        if observed_python != expected_python:
            raise ValueError("installed package source would differ from the reviewed snapshot")
        # Confirm the original snapshot remains the input, not a mutation performed by its backend.
        if any(digest_file(snapshot / name) != digest for name, digest in expected.items()):
            raise ValueError("build backend modified a declared input")
        return len(expected_python)


def build_reproducibly(
    project: Path, output: Path, *, uv: Path, python: Path, offline: bool = False
) -> dict[str, Any]:
    project, output, uv, python = (
        project.resolve(),
        output.absolute(),
        uv.resolve(),
        python.resolve(),
    )
    if output.exists() or output.is_symlink():
        raise ValueError("output must be a new directory")
    metadata = tomllib.loads((project / "pyproject.toml").read_text())
    inputs = source_manifest(project)
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="prometheus-build-") as temporary:
        working = Path(temporary)
        environment = working / "build-environment"
        env = os.environ.copy()
        env.update(
            UV_PROJECT_ENVIRONMENT=str(environment),
            UV_LINK_MODE="copy",
            SOURCE_DATE_EPOCH=str(SOURCE_DATE_EPOCH),
            PYTHONHASHSEED="0",
            TZ="UTC",
        )
        commands = [
            str(uv),
            "sync",
            "--project",
            str(project),
            "--locked",
            "--only-group",
            "build",
            "--no-install-project",
            "--no-build",
            "--python",
            str(python),
        ]
        if offline:
            commands.append("--offline")
        subprocess.run(commands, env=env, check=True, stdout=sys.stderr, stderr=sys.stderr)
        interpreter = environment / "bin/python"
        versions = json.loads(
            subprocess.check_output(
                [
                    str(interpreter),
                    "-I",
                    "-c",
                    "import importlib.metadata,json,platform; "
                    "print(json.dumps({'python':platform.python_version(),"
                    "'dependencies':{name:importlib.metadata.version(name) for name in "
                    "('build','setuptools','wheel','packaging','pyproject-hooks')}}))",
                ],
                text=True,
            )
        )
        wheels = []
        for index, directory in enumerate(("first-checkout", "independent-second-checkout")):
            snapshot = working / directory
            snapshot_source(project, snapshot, inputs, mtime=SOURCE_DATE_EPOCH + 3600 * (index + 1))
            artifacts = working / f"dist-{index}"
            subprocess.run(
                [
                    str(interpreter),
                    "-I",
                    "-m",
                    "build",
                    "--wheel",
                    "--no-isolation",
                    "--outdir",
                    str(artifacts),
                    str(snapshot),
                ],
                env=env,
                check=True,
                stdout=sys.stderr,
                stderr=sys.stderr,
                umask=0o022,
            )
            candidates = list(artifacts.glob("*.whl"))
            if len(candidates) != 1:
                raise ValueError("backend must produce exactly one wheel")
            count = verify_wheel(candidates[0], snapshot, inputs)
            wheels.append(candidates[0])
        digests = [digest_file(wheel) for wheel in wheels]
        if wheels[0].name != wheels[1].name or digests[0] != digests[1]:
            raise ValueError("independent builds differ")
        if source_manifest(project) != inputs:
            raise ValueError("worktree inputs changed during the build")
        receipt = {
            "schema_version": 1,
            "scope": "Local two-snapshot wheel reproducibility; no signing/approval",
            "project": metadata["project"]["name"],
            "version": metadata["project"]["version"],
            "uv_version": subprocess.check_output([str(uv), "--version"], text=True).strip(),
            "build_environment": versions,
            "source_date_epoch": SOURCE_DATE_EPOCH,
            "source_inputs": inputs,
            "source_tree_sha256": hashlib.sha256(
                json.dumps(inputs, sort_keys=True).encode()
            ).hexdigest(),
            "lock_sha256": inputs["uv.lock"],
            "wheel": wheels[0].name,
            "independent_wheel_sha256": digests,
            "wheel_bytes": wheels[0].stat().st_size,
            "verified_python_files": count,
            "record_verified": True,
            "different_checkout_paths_and_source_mtimes": True,
            "network_disabled_for_backend_builds": False,
            "offline_dependency_sync_requested": offline,
        }
        # Backend isolation is dependency isolation, not a network sandbox. Be explicit above.
        output.mkdir(mode=0o700)
        try:
            shutil.copyfile(wheels[0], output / wheels[0].name)
            (output / "build_receipt.json").write_text(
                json.dumps(receipt, indent=2, sort_keys=True) + "\n"
            )
        except BaseException:
            shutil.rmtree(output)
            raise
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--uv", type=Path, required=True)
    parser.add_argument("--python", type=Path, default=Path(sys.executable))
    parser.add_argument("--offline", action="store_true")
    args = parser.parse_args()
    receipt = build_reproducibly(
        args.project, args.output, uv=args.uv, python=args.python, offline=args.offline
    )
    print(
        json.dumps(
            {
                "wheel": receipt["wheel"],
                "sha256": receipt["independent_wheel_sha256"][0],
                "receipt": str(args.output / "build_receipt.json"),
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
