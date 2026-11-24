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
# Research software: NO-GO for trading or advice.
set -euo pipefail

REPO="${ECONOSIM_REPO:-Plovaxs/economisms}"
VERSION="${ECONOSIM_VERSION:-latest}"
HOME_DIR="${ECONOSIM_HOME:-${XDG_DATA_HOME:-$HOME/.local/share}/econosim-app}"
BIN_DIR="${ECONOSIM_BIN:-$HOME/.local/bin}"
TORCH_INDEX="${ECONOSIM_TORCH_INDEX:-https://download.pytorch.org/whl/cpu}"

say() { printf '==> %s\n' "$*"; }
die() { printf 'error: %s\n' "$*" >&2; exit 1; }

if [ "${1:-}" = "--uninstall" ]; then
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

if [ -n "${ECONOSIM_BASE_URL:-}" ]; then
  BASE="$ECONOSIM_BASE_URL"   # a directory (file://...) holding SHA256SUMS and the archive; for testing
elif [ "$VERSION" = "latest" ]; then
  BASE="https://github.com/$REPO/releases/latest/download"
else
  BASE="https://github.com/$REPO/releases/download/v${VERSION#v}"
fi

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

say "Fetching the checksum list"
curl -fsSL -o "$WORK/SHA256SUMS" "$BASE/SHA256SUMS" || die "could not download $BASE/SHA256SUMS"
ARCHIVE="$(awk '{print $2}' "$WORK/SHA256SUMS" | tr -d '*' | grep -E '^econosim-source-.*\.tar\.gz$' | head -n1)"
[ -n "$ARCHIVE" ] || die "the release lists no source archive"

say "Downloading $ARCHIVE"
curl -fsSL -o "$WORK/$ARCHIVE" "$BASE/$ARCHIVE" || die "could not download the source archive"
(cd "$WORK" && grep -F " $ARCHIVE" SHA256SUMS | sed 's/ \*/  /' | sha256sum -c --quiet -) || die "the archive does not match SHA256SUMS; nothing was installed"
say "Checksum OK"

say "Unpacking into $HOME_DIR/src"
rm -rf "$HOME_DIR/src" "$HOME_DIR/venv"
mkdir -p "$HOME_DIR/src" "$BIN_DIR"
tar -xzf "$WORK/$ARCHIVE" -C "$HOME_DIR/src" --strip-components=1
[ -f "$HOME_DIR/src/pyproject.toml" ] || die "the archive is not the project source"

say "Creating a private environment in $HOME_DIR/venv"
python3 -m venv "$HOME_DIR/venv"
"$HOME_DIR/venv/bin/python" -m pip install --quiet --upgrade pip
# Pin every dependency to (at most) the version uv.lock records (what the test suite ran against), so the numbers
# match the project's; a plain `pip install` would resolve newer releases and `econosim doctor` says so.
python3 - "$HOME_DIR/src/uv.lock" "$WORK/constraints.txt" <<'PY'
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
say "Installing (this downloads PyTorch, CPU build, and takes a few minutes; about 1.7 GB on disk)"
"$HOME_DIR/venv/bin/python" -m pip install --quiet --extra-index-url "$TORCH_INDEX" -c "$WORK/constraints.txt" -e "$HOME_DIR/src[desktop,quantum]"

ln -sf "$HOME_DIR/venv/bin/econosim" "$BIN_DIR/econosim"
ICON_FLAG="--desktop-icon"
[ "${ECONOSIM_NO_DESKTOP_ICON:-}" = "1" ] && ICON_FLAG=""   # menu entry only
# shellcheck disable=SC2086
"$HOME_DIR/venv/bin/econosim" desktop --install-launcher $ICON_FLAG   # also warns if Qt needs libxcb-cursor0

case ":$PATH:" in *":$BIN_DIR:"*) ;; *) say "Add $BIN_DIR to your PATH to run \`econosim desktop\` from a terminal." ;; esac
say "Done. Open ECONOSIM from your application menu, or run: econosim desktop"
