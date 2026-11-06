import base64
import csv
import hashlib
import io
import runpy
import zipfile
from pathlib import Path

import pytest

TOOL = Path(__file__).resolve().parents[2] / "tools/reproducible_build.py"
functions = runpy.run_path(str(TOOL))


def project(tmp_path):
    for name in functions["ROOT_INPUTS"]:
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("input " + name)
    package = tmp_path / "src/prometheus"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text('"""package"""\n')
    return tmp_path


def test_snapshots_have_explicit_allowlist_and_ignore_state_credentials_and_caches(tmp_path):
    root = project(tmp_path / "project")
    (root / ".credentials").write_text("private")
    cache = root / "src/prometheus/__pycache__"
    cache.mkdir()
    (cache / "secret.pyc").write_text("not a source file")
    manifest = functions["source_manifest"](root)
    target = tmp_path / "snapshot"
    functions["snapshot_source"](root, target, manifest, mtime=946684800)
    assert (
        not (target / ".credentials").exists()
        and not (target / "src/prometheus/__pycache__").exists()
    )
    assert functions["source_manifest"](target) == manifest


def test_source_drift_and_symlinks_fail_the_build_snapshot(tmp_path):
    root = project(tmp_path / "project")
    manifest = functions["source_manifest"](root)
    (root / "README.md").write_text("changed")
    with pytest.raises(ValueError, match="changed"):
        functions["snapshot_source"](root, tmp_path / "snapshot", manifest, mtime=946684800)
    (root / "README.md").unlink()
    (root / "README.md").symlink_to(root / "LICENSE")
    with pytest.raises(ValueError, match="symlink"):
        functions["source_manifest"](root)


def wheel(path, files):
    record = "example-0.1.dist-info/RECORD"
    output = io.StringIO()
    writer = csv.writer(output)
    with zipfile.ZipFile(path, "w") as archive:
        for name, content in files.items():
            archive.writestr(name, content)
            digest = base64.urlsafe_b64encode(hashlib.sha256(content).digest()).decode().rstrip("=")
            writer.writerow([name, "sha256=" + digest, len(content)])
        writer.writerow([record, "", ""])
        archive.writestr(record, output.getvalue())


def test_wheel_record_and_exact_package_contents_are_verified(tmp_path):
    root = project(tmp_path / "project")
    manifest = functions["source_manifest"](root)
    package = (root / "src/prometheus/__init__.py").read_bytes()
    path = tmp_path / "valid.whl"
    wheel(path, {"prometheus/__init__.py": package})
    assert functions["verify_wheel"](path, root, manifest) == 1
    wheel(path, {"prometheus/__init__.py": b"changed"})
    with pytest.raises(ValueError, match="source"):
        functions["verify_wheel"](path, root, manifest)
    wheel(path, {"prometheus/__init__.py": package, "../../escape": b"invalid"})
    with pytest.raises(ValueError, match="unsafe"):
        functions["verify_wheel"](path, root, manifest)


def test_build_will_never_clobber_an_existing_output_directory(tmp_path):
    root = project(tmp_path / "project")
    output = tmp_path / "existing"
    output.mkdir()
    (output / "receipt").write_text("keep")
    with pytest.raises(ValueError, match="new directory"):
        functions["build_reproducibly"](root, output, uv=Path("missing"), python=Path("missing"))
    assert (output / "receipt").read_text() == "keep"


def test_lock_is_hashed_and_explicitly_scopes_the_cpu_index_to_torch():
    import tomllib

    root = TOOL.parents[1]
    config = tomllib.loads((root / "pyproject.toml").read_text())
    lock = tomllib.loads((root / "uv.lock").read_text())
    assert config["tool"]["uv"]["sources"] == {"torch": {"index": "pytorch-cpu"}}
    assert all(index["explicit"] for index in config["tool"]["uv"]["index"])
    for package in lock["package"]:
        if "registry" not in package["source"]:
            continue
        assert package["wheels"]
        for archive in package["wheels"]:
            assert archive["hash"].startswith("sha256:") and len(archive["hash"]) == 71
        if "pytorch.org" in package["source"]["registry"]:
            assert package["name"] == "torch"
