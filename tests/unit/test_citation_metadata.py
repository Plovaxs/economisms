"""`CITATION.cff` exists, parses, and cannot drift from the release it describes.

A citation file that names last month's version is worse than none: someone cites a release
that is not the one they ran. So the version and the release date are tied to `pyproject.toml`
and to the dated section of `CHANGELOG.md`, and the release workflow checks the same version
before it publishes anything.

It deliberately does not check for a DOI: none exists (minting one needs the owner to connect
the repository to an archive such as Zenodo), and a test must not demand a field the project
cannot honestly fill.
"""

from __future__ import annotations

import re
import tomllib
from datetime import date
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]


def _citation() -> dict[str, object]:
    loaded = yaml.safe_load((ROOT / "CITATION.cff").read_text(encoding="utf-8"))
    assert isinstance(loaded, dict)
    return loaded


def _project_version() -> str:
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    return str(pyproject["project"]["version"])


def test_the_file_has_the_fields_the_format_requires() -> None:
    citation = _citation()
    assert citation["cff-version"] == "1.2.0"
    for required in ("message", "title", "authors"):
        assert citation.get(required), f"CITATION.cff has no {required!r}"
    authors = citation["authors"]
    assert isinstance(authors, list) and authors
    for author in authors:
        assert isinstance(author, dict)
        assert author.get("name") or author.get("family-names"), "an author needs a name"


def test_the_version_is_the_version_that_pyproject_declares() -> None:
    assert str(_citation()["version"]) == _project_version()


def test_the_release_date_is_the_date_the_changelog_gives_that_version() -> None:
    version = _project_version()
    changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    heading = rf"^## \[{re.escape(version)}\] -- (\d{{4}}-\d{{2}}-\d{{2}})"
    match = re.search(heading, changelog, re.MULTILINE)
    assert match, f"CHANGELOG.md has no dated section for {version}"
    released = _citation()["date-released"]
    assert isinstance(released, date), "date-released must be an ISO date"
    assert released.isoformat() == match.group(1)


def test_the_licence_and_repository_match_the_project() -> None:
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    citation = _citation()
    assert citation["license"] == pyproject["project"]["license"]
    installer = (ROOT / "scripts" / "install-linux.sh").read_text(encoding="utf-8")
    default_repo = re.search(r'REPO="\$\{ECONOSIM_REPO:-([^}]+)\}"', installer)
    assert default_repo, "could not find the installer's default repository"
    assert citation["repository-code"] == f"https://github.com/{default_repo.group(1)}"


def test_the_release_workflow_refuses_to_publish_stale_citation_metadata() -> None:
    workflow = (ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")
    assert "CITATION.cff" in workflow, "the release's version job must check CITATION.cff"
