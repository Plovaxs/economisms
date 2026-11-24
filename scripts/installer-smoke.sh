#!/usr/bin/env bash
# End-to-end test of scripts/install-linux.sh on THIS machine, in a scratch directory: it never touches
# your real home directory, menu or desktop. Used by .github/workflows/installer-smoke.yml on fresh
# runners, and runnable by hand:  bash scripts/installer-smoke.sh
#
# It builds the source archive from HEAD the way the release workflow does, then: installs, checks the
# files, runs `econosim desktop --check` and `econosim doctor`, installs AGAIN over the first install
# (an upgrade) and checks the user's results survive, optionally launches the window under Xvfb
# (SMOKE_X11=1), uninstalls and checks that only the installer's own files went.
#
# On a machine whose python3 is older than 3.11 it checks the installer REFUSES cleanly instead.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
WORK="${SMOKE_WORKDIR:-$(mktemp -d)}"
FAKE_HOME="$WORK/home"; REL="$WORK/rel"; APP="$WORK/app"; BIN="$WORK/bin"; STATE="$WORK/state"; XDG="$WORK/xdg"
mkdir -p "$REL" "$FAKE_HOME/Desktop"
mkdir -m 700 "$STATE"   # the application insists on a private state directory
step() { printf '\n=== %s\n' "$*"; }
fail() { printf 'SMOKE FAILED: %s\n' "$*" >&2; exit 1; }

VERSION="$(python3 -c 'import sys, tomllib; print(tomllib.load(open(sys.argv[1], "rb"))["project"]["version"])' "$ROOT/pyproject.toml" 2>/dev/null || true)"
if [ -z "$VERSION" ]; then
  VERSION="$(grep -m1 '^version' "$ROOT/pyproject.toml" | cut -d'"' -f2)"   # python < 3.11 has no tomllib
fi
git -C "$ROOT" archive --format=tar.gz --prefix="econosim-$VERSION/" -o "$REL/econosim-source-$VERSION.tar.gz" HEAD
(cd "$REL" && sha256sum "econosim-source-$VERSION.tar.gz" > SHA256SUMS)

installer() {
  HOME="$FAKE_HOME" XDG_DESKTOP_DIR="$FAKE_HOME/Desktop" XDG_DATA_HOME="$XDG" ECONOSIM_BASE_URL="file://$REL" \
    ECONOSIM_INSTALL_DIR="$APP" ECONOSIM_BIN="$BIN" ECONOSIM_HOME="$STATE" bash "$ROOT/scripts/install-linux.sh" "$@"
}
app() { HOME="$FAKE_HOME" XDG_DATA_HOME="$XDG" ECONOSIM_HOME="$STATE" "$@"; }

step "environment"
uname -srm; (. /etc/os-release 2>/dev/null && echo "$PRETTY_NAME") || true
python3 --version || true

if ! python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)' 2>/dev/null; then
  step "python3 is older than 3.11: the installer must refuse, cleanly, before downloading anything"
  if out="$(installer 2>&1)"; then fail "the installer accepted a python older than 3.11"; fi
  echo "$out" | grep -q "python 3.11 or newer is required" || fail "the refusal did not say why: $out"
  [ ! -e "$APP" ] || fail "a refused install left files behind"
  echo "refused cleanly: $out"
  exit 0
fi

step "install"
installer
for f in "$BIN/econosim" "$XDG/applications/econosim.desktop" "$XDG/icons/hicolor/scalable/apps/econosim.svg" \
         "$FAKE_HOME/Desktop/ECONOSIM.desktop" "$APP/.econosim-install"; do
  [ -e "$f" ] || fail "missing after install: $f"
done
[ -x "$FAKE_HOME/Desktop/ECONOSIM.desktop" ] || fail "the desktop icon is not executable"
command -v desktop-file-validate >/dev/null && desktop-file-validate "$XDG/applications/econosim.desktop"

step "econosim desktop --check (offscreen)"
app env QT_QPA_PLATFORM=offscreen "$BIN/econosim" desktop --check

step "econosim doctor"
app "$BIN/econosim" doctor

step "the user's results, then an upgrade over the existing install"
echo "my results" > "$STATE/keep.txt"
installer
[ "$(cat "$STATE/keep.txt")" = "my results" ] || fail "the upgrade touched the state directory"
app env QT_QPA_PLATFORM=offscreen "$BIN/econosim" desktop --check

if [ "${SMOKE_X11:-0}" = "1" ]; then
  step "launch the window on a virtual X11 display (Xvfb); it must still be running after 20 s"
  set +e
  app timeout 20 xvfb-run -a "$BIN/econosim" desktop
  code=$?
  set -e
  [ "$code" = "124" ] || fail "the window exited early (status $code) instead of running until stopped"
  [ ! -e "$STATE/startup-error.txt" ] || fail "startup-error.txt: $(cat "$STATE/startup-error.txt")"
  echo "the window ran for 20 s on X11 with no startup error"
fi

step "uninstall"
installer --uninstall
for f in "$APP" "$BIN/econosim" "$XDG/applications/econosim.desktop" "$XDG/icons/hicolor/scalable/apps/econosim.svg" \
         "$FAKE_HOME/Desktop/ECONOSIM.desktop"; do
  [ ! -e "$f" ] || fail "still there after uninstall: $f"
done
[ "$(cat "$STATE/keep.txt")" = "my results" ] || fail "the uninstall touched the state directory"
[ -z "$(ls -A "$FAKE_HOME/Desktop")" ] || fail "the uninstall left something on the desktop"

step "installer smoke test passed on $(. /etc/os-release 2>/dev/null && echo "$PRETTY_NAME" || uname -s)"
