#!/usr/bin/env bash
# Installs the ECONOSIM desktop application for the current user on Linux: no root, nothing outside
# your home directory, and it can be undone with `scripts/install-linux.sh --uninstall`.
#
#   curl -fsSLO https://github.com/Plovaxs/economisms/releases/latest/download/install-linux.sh
#   less install-linux.sh && bash install-linux.sh        # read it first; it is short
#
# What it does: downloads the release's source archive and its SHA256SUMS, checks the archive against
# them (an integrity check, not a signature), unpacks it under ~/.local/share/econosim-app, installs it
# into a private virtualenv in editable mode with the CPU build of PyTorch and the quantum extra, puts
# `econosim` on your PATH and adds ECONOSIM, with its icon, to the application menu and to your desktop
# (ECONOSIM_NO_DESKTOP_ICON=1 skips the desktop icon).
#
# Why the source and not the wheel: the labs read the committed `data_cache/` next to the source tree,
# and a wheel does not carry it, so a wheel install opens but its data-driven labs cannot run.
# Overrides: ECONOSIM_INSTALL_DIR (default ~/.local/share/econosim-app), ECONOSIM_BIN, ECONOSIM_VERSION,
# ECONOSIM_REPO, ECONOSIM_TORCH_INDEX, ECONOSIM_NO_DESKTOP_ICON, ECONOSIM_OFFLINE_DIR. ECONOSIM_HOME is the
# application's state directory and is never used for installing; the installer refuses to touch it.
#
# Offline: on a machine WITH network, `bash install-linux.sh --make-offline-bundle DIR` downloads the source
# archive and every wheel (PyTorch included, about 400 MB) into DIR; copy DIR to the offline machine (same
# Linux architecture and same Python minor version) and run `ECONOSIM_OFFLINE_DIR=DIR bash install-linux.sh`.
# That install makes no network request: pip runs with --no-index. See docs/release/OFFLINE_INSTALL.md.
# Research software: NO-GO for trading or advice.
set -euo pipefail

REPO="${ECONOSIM_REPO:-Plovaxs/economisms}"
VERSION="${ECONOSIM_VERSION:-latest}"
# NOT ECONOSIM_HOME: that variable is the APPLICATION's state directory (where your results are kept), and an
# installer that took it for its own directory would delete your results when it reinstalls or uninstalls.
HOME_DIR="${ECONOSIM_INSTALL_DIR:-${XDG_DATA_HOME:-$HOME/.local/share}/econosim-app}"
BIN_DIR="${ECONOSIM_BIN:-$HOME/.local/bin}"
TORCH_INDEX="${ECONOSIM_TORCH_INDEX:-https://download.pytorch.org/whl/cpu}"

say() { printf '==> %s\n' "$*"; }
die() { printf 'error: %s\n' "$*" >&2; exit 1; }

MARKER="$HOME_DIR/.econosim-install"

# True for a directory this installer made: it carries the marker, or (installs made before the marker
# existed) it holds a source tree of this project and its own venv.
is_ours() {
  [ -f "$MARKER" ] && return 0
  [ -x "$HOME_DIR/venv/bin/econosim" ] && grep -q '^name = "prometheus-econ"' "$HOME_DIR/src/pyproject.toml" 2>/dev/null
}

# Refuse to touch a directory that could hold something else: the home directory, the root, the
# application's state directory, or any non-empty directory this installer did not make.
guard_install_dir() {
  case "$HOME_DIR" in ""|"/"|"$HOME"|"$HOME/") die "refusing to use '$HOME_DIR' as the install directory" ;; esac
  if [ -n "${ECONOSIM_HOME:-}" ] && [ "$(realpath -m "$HOME_DIR")" = "$(realpath -m "$ECONOSIM_HOME")" ]; then
    die "$HOME_DIR is ECONOSIM_HOME, the application's state directory (your results). Set ECONOSIM_INSTALL_DIR to install somewhere else"
  fi
  if [ -e "$HOME_DIR" ] && [ -n "$(ls -A "$HOME_DIR" 2>/dev/null)" ] && ! is_ours; then
    die "$HOME_DIR exists, is not empty and was not made by this installer; nothing was changed"
  fi
}

if [ "${1:-}" = "--uninstall" ]; then
  if [ ! -e "$HOME_DIR" ]; then say "Nothing installed in $HOME_DIR."; exit 0; fi
  guard_install_dir
  is_ours || die "$HOME_DIR was not made by this installer; nothing was removed"
  if [ -x "$HOME_DIR/venv/bin/econosim" ]; then "$HOME_DIR/venv/bin/econosim" desktop --uninstall-launcher || true; fi
  rm -f "$BIN_DIR/econosim"
  rm -rf "$HOME_DIR"
  say "Removed $HOME_DIR and $BIN_DIR/econosim (your results in the state directory are kept)."
  exit 0
fi

[ "$(uname -s)" = "Linux" ] || die "this installer is for Linux; see the README for other systems"
command -v python3 >/dev/null || die "python3 is required (3.11 or newer)"
python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)' || die "python 3.11 or newer is required"
python3 -c 'import venv, ensurepip' 2>/dev/null || die "python3-venv is missing (Debian/Ubuntu: sudo apt install python3-venv)"
command -v curl >/dev/null || die "curl is required"
command -v sha256sum >/dev/null || die "sha256sum is required"

# Pin every dependency to (at most) the version uv.lock records (what the test suite ran against), so the numbers
# match the project's; a plain `pip install` would resolve newer releases and `econosim doctor` says so.
write_constraints() {   # write_constraints UV_LOCK OUT
  python3 - "$1" "$2" <<'PY'
import sys, tomllib
versions = {}
for package in tomllib.load(open(sys.argv[1], "rb")).get("package", []):
    source = package.get("source", {})
    if "editable" in source or "virtual" in source:
        continue
    versions.setdefault(package["name"], set()).add(package["version"].split("+")[0])
with open(sys.argv[2], "w") as out:
    for name, found in sorted(versions.items()):
        if len(found) == 1:
            out.write(f"{name}=={next(iter(found))}\n")
        else:  # one version per Python fork: cap at the newest, pip then takes the newest it supports
            def key(v):
                return [int(x) if x.isdigit() else 0 for x in v.replace("-", ".").split(".")]
            out.write(f"{name}<={max(found, key=key)}\n")
PY
}

if [ -n "${ECONOSIM_BASE_URL:-}" ]; then
  BASE="$ECONOSIM_BASE_URL"   # a directory (file://...) holding SHA256SUMS and the archive; for testing
elif [ "$VERSION" = "latest" ]; then
  BASE="https://github.com/$REPO/releases/latest/download"
else
  BASE="https://github.com/$REPO/releases/download/v${VERSION#v}"
fi

fetch_archive() {   # fetch_archive DIR: SHA256SUMS and the source archive from $BASE into DIR, checked; sets ARCHIVE
  say "Fetching the checksum list"
  curl -fsSL -o "$1/SHA256SUMS" "$BASE/SHA256SUMS" || die "could not download $BASE/SHA256SUMS"
  ARCHIVE="$(awk '{print $2}' "$1/SHA256SUMS" | tr -d '*' | grep -E '^econosim-source-.*\.tar\.gz$' | head -n1)"
  [ -n "$ARCHIVE" ] || die "the release lists no source archive"
  say "Downloading $ARCHIVE"
  curl -fsSL -o "$1/$ARCHIVE" "$BASE/$ARCHIVE" || die "could not download the source archive"
  (cd "$1" && grep -F " $ARCHIVE" SHA256SUMS | sed 's/ \*/  /' | sha256sum -c --quiet -) || die "the archive does not match SHA256SUMS; nothing was installed"
  say "Checksum OK"
}

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

if [ "${1:-}" = "--make-offline-bundle" ]; then
  # Needs network. Everything an offline install needs, in one directory: the checked source archive, a
  # wheelhouse (every dependency as a wheel, plus the build tools the editable install needs), and a
  # SHA256SUMS over all of it. Wheels are specific to this Python minor version and CPU architecture.
  OUT="${2:-}"; [ -n "$OUT" ] || die "usage: install-linux.sh --make-offline-bundle DIR"
  mkdir -p "$OUT/wheelhouse"
  [ -z "$(ls -A "$OUT/wheelhouse")" ] || die "$OUT/wheelhouse is not empty; use a new directory"
  fetch_archive "$WORK"
  mkdir "$WORK/src"; tar -xzf "$WORK/$ARCHIVE" -C "$WORK/src" --strip-components=1
  [ -f "$WORK/src/pyproject.toml" ] || die "the archive is not the project source"
  write_constraints "$WORK/src/uv.lock" "$WORK/constraints.txt"
  python3 -m venv "$WORK/venv"
  BUILD_REQUIRES="$(python3 -c 'import sys, tomllib; print(" ".join(tomllib.load(open(sys.argv[1], "rb"))["build-system"]["requires"]))' "$WORK/src/pyproject.toml")"
  say "Downloading every wheel (PyTorch CPU build included; about 400 MB)"
  # --only-binary: a dependency that only ships source would need a compiler on the offline machine, so fail HERE
  "$WORK/venv/bin/python" -m pip download --quiet --only-binary=:all: --dest "$OUT/wheelhouse" \
    --extra-index-url "$TORCH_INDEX" -c "$WORK/constraints.txt" "$WORK/src[desktop,quantum]"
  # shellcheck disable=SC2086
  "$WORK/venv/bin/python" -m pip download --quiet --only-binary=:all: --dest "$OUT/wheelhouse" $BUILD_REQUIRES
  cp "$WORK/$ARCHIVE" "$OUT/$ARCHIVE"
  printf 'system=%s\nmachine=%s\npython=%s\narchive=%s\n' "$(uname -s)" "$(uname -m)" \
    "$(python3 -c 'import sys; print("%d.%d" % sys.version_info[:2])')" "$ARCHIVE" > "$OUT/OFFLINE-BUNDLE"
  (cd "$OUT" && sha256sum -- "$ARCHIVE" wheelhouse/* > SHA256SUMS)
  say "Bundle written to $OUT ($(du -sh "$OUT" | cut -f1)). On the offline machine: ECONOSIM_OFFLINE_DIR=$OUT bash install-linux.sh"
  exit 0
fi

OFFLINE_DIR="${ECONOSIM_OFFLINE_DIR:-}"
if [ -n "$OFFLINE_DIR" ]; then
  [ -f "$OFFLINE_DIR/OFFLINE-BUNDLE" ] && [ -d "$OFFLINE_DIR/wheelhouse" ] || die "$OFFLINE_DIR is not an offline bundle (make one with --make-offline-bundle)"
  OFFLINE_DIR="$(cd "$OFFLINE_DIR" && pwd)"
  bundle_field() { sed -n "s/^$1=//p" "$OFFLINE_DIR/OFFLINE-BUNDLE"; }
  have_python="$(python3 -c 'import sys; print("%d.%d" % sys.version_info[:2])')"
  [ "$(bundle_field python)" = "$have_python" ] || die "the bundle holds wheels for Python $(bundle_field python), this is Python $have_python; make a bundle on a machine with the same Python"
  [ "$(bundle_field machine)" = "$(uname -m)" ] || die "the bundle is for $(bundle_field machine), this machine is $(uname -m)"
  BASE="file://$OFFLINE_DIR"   # curl copies from the directory; no network
fi

guard_install_dir   # before anything is downloaded: a refusal costs nothing

fetch_archive "$WORK"
if [ -n "$OFFLINE_DIR" ]; then   # the bundle's SHA256SUMS also covers every wheel: a corrupted copy stops here
  (cd "$OFFLINE_DIR" && sha256sum -c --quiet SHA256SUMS) || die "the offline bundle does not match its SHA256SUMS; nothing was installed"
  say "Offline bundle checksums OK"
fi

say "Unpacking into $HOME_DIR/src"
rm -rf "$HOME_DIR/src" "$HOME_DIR/venv"
mkdir -p "$HOME_DIR/src" "$BIN_DIR"
printf 'econosim installer\nversion=%s\n' "$ARCHIVE" > "$MARKER"
tar -xzf "$WORK/$ARCHIVE" -C "$HOME_DIR/src" --strip-components=1
[ -f "$HOME_DIR/src/pyproject.toml" ] || die "the archive is not the project source"

say "Creating a private environment in $HOME_DIR/venv"
python3 -m venv "$HOME_DIR/venv"
write_constraints "$HOME_DIR/src/uv.lock" "$WORK/constraints.txt"
if [ -n "$OFFLINE_DIR" ]; then
  say "Installing from the offline bundle (no network: pip runs with --no-index)"
  "$HOME_DIR/venv/bin/python" -m pip install --quiet --no-index --find-links "$OFFLINE_DIR/wheelhouse" -c "$WORK/constraints.txt" -e "$HOME_DIR/src[desktop,quantum]"
else
  "$HOME_DIR/venv/bin/python" -m pip install --quiet --upgrade pip
  say "Installing (this downloads PyTorch, CPU build, and takes a few minutes; about 1.7 GB on disk)"
  "$HOME_DIR/venv/bin/python" -m pip install --quiet --extra-index-url "$TORCH_INDEX" -c "$WORK/constraints.txt" -e "$HOME_DIR/src[desktop,quantum]"
fi

ln -sf "$HOME_DIR/venv/bin/econosim" "$BIN_DIR/econosim"
ICON_FLAG="--desktop-icon"
[ "${ECONOSIM_NO_DESKTOP_ICON:-}" = "1" ] && ICON_FLAG=""   # menu entry only
# shellcheck disable=SC2086
"$HOME_DIR/venv/bin/econosim" desktop --install-launcher $ICON_FLAG   # also warns if Qt needs libxcb-cursor0

case ":$PATH:" in *":$BIN_DIR:"*) ;; *) say "Add $BIN_DIR to your PATH to run \`econosim desktop\` from a terminal." ;; esac
say "Done. Open ECONOSIM from your application menu, or run: econosim desktop"
