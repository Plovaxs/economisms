# ECONOSIM frontend

A single React app over every ECONOSIM/PROMETHEUS-X dashboard view and
every trained/benchmarked subsystem ("engine"), talking to the existing
Python backend over two real, already-authenticated APIs -- not a new
backend, not a mock.

## Stack

Vite + React + TypeScript + Tailwind CSS + Framer Motion + Recharts.
No production static-file serving is set up on purpose: this is a
local research/demo tool, not a deployed service.

## Running it locally

### One command (recommended)

From the repository root (`/home/plovax/research/ECONS`):

```bash
./run_dev.sh
```

This starts all four processes -- job worker, job API (:8765),
dashboard (:8766), frontend (:5173) -- in the background, provisions a
bearer token on first run, installs frontend dependencies on first
run, and prints the token plus the URL to open. Logs for each process
go to `/tmp/econosim-web/logs/*.log`. **Ctrl+C stops everything.**

Open the printed `http://localhost:5173` URL and paste in the printed
token.

### Manual (four terminals)

Useful if you want to see each process's own output live, or restart
one without the others. All four share one credentials file and one
`--root` job-storage directory:

```bash
source .venv/bin/activate
mkdir -p /tmp/econosim-web

# One-time: provision a bearer token (same CredentialStore both
# backends already share -- not a new auth system).
python -m prometheus.service init-auth \
  --credentials /tmp/econosim-web/auth.json \
  --token-file /tmp/econosim-web/token --owner alice

# 1. The job WORKER -- without this running, submitted jobs sit in
#    "queued" forever. Shares --root with the service below.
python -m prometheus.jobs --root /tmp/econosim-web work

# 2. The async job API (Q-MACRO/RECESSIONNET/INFLATIONCAST/neural-SDE/
#    PDE solvers/multi-agent RL/RL-hedging all run here as real jobs,
#    backed by the real SQLite job queue in prometheus.jobs.store).
python -m prometheus.service serve \
  --root /tmp/econosim-web --credentials /tmp/econosim-web/auth.json --port 8765

# 3. The existing HTML dashboard, now also serving ?format=json for
#    the lighter, already-fast views (economy, pricing, hedging,
#    portfolio risk, experiments, audit trail, validation issues,
#    model usage, owner-scoped portfolios).
python -m prometheus.dashboard serve \
  --credentials /tmp/econosim-web/auth.json --port 8766 --demo

# 4. This frontend. Vite proxies /api/jobs -> :8765 and
#    /api/dashboard -> :8766 (see vite.config.ts).
cd frontend
npm install
npm run dev
```

Open the printed `http://localhost:5173` URL and paste in the token
from `/tmp/econosim-web/token`.

## Scripts

- `npm run dev` -- Vite dev server with the API proxy.
- `npm run build` -- typecheck + production build (`dist/`, unused
  today -- see above).
- `npm run lint` -- ESLint.
- `npm run typecheck` -- `tsc --noEmit`.
- `npm run test` -- Vitest + React Testing Library.
