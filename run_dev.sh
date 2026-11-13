#!/usr/bin/env bash
# Starts every process the ECONOSIM web app needs -- job worker, job API,
# dashboard, frontend -- with one command. Ctrl+C stops all of them.
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")"

ROOT_DIR="${ECONOSIM_WEB_ROOT:-/tmp/econosim-web}"
LOG_DIR="$ROOT_DIR/logs"
mkdir -p "$LOG_DIR"

if ! command -v node >/dev/null 2>&1 && [ -x "$HOME/.local/node/bin/node" ]; then
  export PATH="$HOME/.local/node/bin:$PATH"
fi
if ! command -v node >/dev/null 2>&1; then
  echo "error: node not found. Install it or add it to PATH, then re-run." >&2
  exit 1
fi

source .venv/bin/activate

if [ ! -f "$ROOT_DIR/auth.json" ]; then
  echo "Provisioning a bearer token (one-time)..."
  python -m prometheus.service init-auth \
    --credentials "$ROOT_DIR/auth.json" \
    --token-file "$ROOT_DIR/token" --owner alice
fi

if [ ! -d frontend/node_modules ]; then
  echo "Installing frontend dependencies (one-time)..."
  (cd frontend && npm install) >"$LOG_DIR/npm-install.log" 2>&1
fi

PIDS=()
cleanup() {
  echo ""
  echo "Stopping all processes..."
  for pid in "${PIDS[@]}"; do
    kill "$pid" >/dev/null 2>&1 || true
  done
  wait >/dev/null 2>&1 || true
}
trap cleanup EXIT INT TERM

echo "Starting job worker..."
python -m prometheus.jobs --root "$ROOT_DIR" work >"$LOG_DIR/worker.log" 2>&1 &
PIDS+=("$!")

echo "Starting job API on :8765..."
python -m prometheus.service serve \
  --root "$ROOT_DIR" --credentials "$ROOT_DIR/auth.json" --port 8765 \
  >"$LOG_DIR/jobs-api.log" 2>&1 &
PIDS+=("$!")

echo "Starting dashboard on :8766..."
python -m prometheus.dashboard serve \
  --credentials "$ROOT_DIR/auth.json" --port 8766 --demo \
  >"$LOG_DIR/dashboard.log" 2>&1 &
PIDS+=("$!")

echo "Starting frontend on :5173..."
(cd frontend && npm run dev) >"$LOG_DIR/frontend.log" 2>&1 &
PIDS+=("$!")

sleep 2

cat <<EOF

============================================================
 ECONOSIM is up.

   Frontend:   http://localhost:5173
   Job API:    http://127.0.0.1:8765
   Dashboard:  http://127.0.0.1:8766

   Bearer token (paste into the frontend's unlock screen):
   $(cat "$ROOT_DIR/token")

   Logs: $LOG_DIR/*.log
   Press Ctrl+C to stop everything.
============================================================

EOF

wait
