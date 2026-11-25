# Installing ECONOSIM with no network

For a machine that cannot reach the internet (an air-gapped lab, a train, a locked-down workstation). Audit item
L-05. Linux only, like the installer itself.

## The two steps

**1. On a machine WITH network** (the same CPU architecture and the same Python minor version as the target: wheels are
specific to both, so a 3.12 bundle does not install on 3.11):

```bash
curl -fsSLO https://github.com/Plovaxs/economisms/releases/latest/download/install-linux.sh
bash install-linux.sh --make-offline-bundle ./econosim-bundle      # about 400 MB (measured: 393 MB for Python 3.14 on x86_64; PyTorch is about half)
```

This downloads the release's source archive and checks it against the release's `SHA256SUMS`, downloads every
dependency as a wheel (the same versions `uv.lock` records, the CPU build of PyTorch) plus the build tools the
editable install needs, and writes a `SHA256SUMS` over all of it and an `OFFLINE-BUNDLE` file recording the Python
version and architecture. It uses `--only-binary`: a dependency that ships only source would need a compiler on the
offline machine, so the bundle step fails instead.

**2. Copy the directory to the offline machine** (USB drive, `scp`) **and run:**

```bash
ECONOSIM_OFFLINE_DIR=./econosim-bundle bash install-linux.sh
```

Before it changes anything it checks that the bundle is for this Python and this architecture, then checks every file
against the bundle's `SHA256SUMS`. It then installs with `pip --no-index`, which cannot reach a package index, and
takes the source archive from the bundle directory. Everything else is the normal installer: the same private
virtual environment, the same menu entry and icon, the same `--uninstall`.

## What was verified, and what was not

`scripts/installer-smoke.sh` with `SMOKE_OFFLINE=1` makes a bundle, then runs the install, an upgrade over it and the
uninstall inside a Linux network namespace with no interface at all (first checking that `pypi.org` is unreachable
there), then `econosim desktop --check` and `econosim doctor`. CI runs it on a fresh Ubuntu 24.04 runner (the
`offline` job of `installer-smoke.yml`). The unit tests in `tests/unit/test_install_script.py` cover the refusals: not a
bundle, wrong Python, wrong architecture, a corrupted wheel or archive.

Also run by hand, outside CI: an install from the bundle into a scratch directory inside the same kind of namespace, then
`python -m prometheus.confirmatory reproduce` there: all 16 checks matched (2 min 40 s), so the committed data and the
code paths the labs use work with no network.

Not verified: other distributions or architectures, a bundle made on a different machine from the one it is installed
on (CI makes and uses it on the same runner), or any Python other than the runner's.

The bundle's checksums catch a corrupted or truncated copy. They do not prove the bundle is honest: someone who can
change the wheels can change the list. For that, check the source archive against the release's own `SHA256SUMS`
(`sha256sum econosim-source-*.tar.gz` and compare) and read `docs/release/VERIFYING.md` for the signed attestations.

## What works offline once installed, and what does not

The datasets the labs read are committed (`data_cache/`, `confirmatory_data/`) and ship inside the source archive, so
the labs, the desktop application, `econosim doctor` and `python -m prometheus.confirmatory reproduce` run with no
network. These need the network:

| Task | Why |
| --- | --- |
| `python -m prometheus.confirmatory fetch-cpi` | reads the BLS API (`api.bls.gov`); it is write-once and prints no values |
| Rebuilding a dataset from its source (Kaggle files, the French data library, FRED, World Bank, Treasury) | the connectors in `prometheus.data_ingestion` call those hosts through an egress allowlist |
| Refreshing the data past the committed snapshot | the same connectors |
| Installing or upgrading the application | making a new bundle needs network once |
