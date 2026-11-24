# Release runbook

Every step below was done by hand for the latest releases (0.5.2 and 0.5.3); this is the recipe, so that it does not live in one
person's head. A release is cut only on the maintainer's say-so, and only from a commit on `main` whose workflows
are all green.

## Before the tag

1. **Version.** Bump it in `pyproject.toml`; in `uv.lock` (the one `version =` line under `name =
   "prometheus-econ"`, then `uv lock --check`); in `frontend/package.json` and twice in
   `frontend/package-lock.json`; in the README's version badge; in `CITATION.cff` (`version` and `date-released`).
2. **SBOM.** `uv export --locked --extra service --extra recovery --no-dev --format cyclonedx1.5 -o
   docs/release/dependency-sbom.cdx.json`. Only the serial number, the timestamp and the three version lines
   should change.
3. **Changelog.** Move the `[Unreleased]` entries under `## [X.Y.Z] -- YYYY-MM-DD -- title` and leave an empty
   `[Unreleased]`. A test ties the `CITATION.cff` date to this heading, and the release workflow refuses to run if
   the changelog or the citation does not name the version.
4. **Counts.** Put the test counts in the README from a CI log, not from a local run (the CI image lacks
   `desktop-file-utils`, so it skips three tests that a developer machine runs).
5. **Green.** Commit and push to `main`; wait for CI (four Python versions), `codeql`, `docker-build`,
   `frontend-ci`, `security` and, when it is triggered, `installer-smoke` and `mutation-check`. Do not tag a red
   or still-running commit.

## The tag

```
git tag -a vX.Y.Z <commit> -m "vX.Y.Z: <what it is>"
git push origin vX.Y.Z
```

The `release` workflow then runs: `version` (the tag must equal `pyproject.toml`'s version; the changelog and the
citation must name it), `wheel` (built twice from independent source snapshots and compared), `web`, `container`,
and, only for a tag, `publish`, the one job that can write: it gathers the files and checksums, **attests their
build provenance**, and creates the release. Nothing is published if any earlier job or the attestation fails.

## After the tag: verify the release, do not assume it

1. `gh release view vX.Y.Z` lists seven files: the wheel, the web build, the source archive, `install-linux.sh`,
   the SBOM, `build_receipt.json` and `SHA256SUMS`.
2. In a scratch folder: `sha256sum -c SHA256SUMS`, then `gh attestation verify <file> --repo Plovaxs/economisms`
   for each file ([VERIFYING.md](./VERIFYING.md)).
3. Install from the release, not from your checkout: download `install-linux.sh`, run it with
   `HOME`, `ECONOSIM_INSTALL_DIR`, `ECONOSIM_BIN` and `XDG_DATA_HOME` pointed at a scratch directory, then
   `econosim desktop --check` and `econosim doctor` (both must say "all clear"), then `--uninstall`.
4. Update the README if a count changed, and the notes.

## If a release is wrong

Do not edit or replace its files and do not move its tag: a tag that changes under people breaks every checksum and
attestation that named it. Publish a corrected `X.Y.Z+1` that says what was wrong. Deleting a release is the
maintainer's decision, not a routine step.

## Not part of the workflow, on purpose

No container image is pushed to a registry, nothing is signed with a long-lived key, and no desktop binary is built
(a bundled Qt would carry LGPL obligations; see `docs/LICENSE_INVENTORY.md`). A DOI needs the maintainer to connect
an archive such as Zenodo to the repository once; after that, each release is archived.
