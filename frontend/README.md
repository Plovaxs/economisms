# ECONOSIM frontend

A single React app over every ECONOSIM/PROMETHEUS-X dashboard view and
every trained/benchmarked subsystem ("engine"), talking to the existing
Python backend over two real, already-authenticated APIs -- not a new
backend, not a mock.

## Stack

Vite + React + TypeScript + Tailwind CSS + Framer Motion + Recharts.
`npm run build`'s output (`dist/`) is served for real by
`prometheus.webgateway` (see "Running the built artifact with Docker"
below) -- still a local research/demo tool, not a deployed service: no
TLS termination, no multi-tenant routing, nothing beyond what
Docker's own port-publishing already isolates.

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

## Running the built artifact with Docker

An alternative to the four-process local workflow above, for trying the
demo with nothing installed locally but Docker -- complementary, not a
replacement: this still does not develop the frontend (no hot reload),
`npm run dev` above remains the way to do that.

```bash
cd ..  # repository root
docker compose up --build
```

Then open `http://localhost:8080` and paste in the token printed by
`docker compose exec webgateway cat /data/token`. See the repository
root's `Dockerfile`/`docker-compose.yml` for exactly what each of the
five containers (one-shot credential provisioning, job worker, job
API, dashboard, and `prometheus.webgateway` -- the one that actually
serves this built frontend and reverse-proxies the other two APIs,
replaying this same `vite.config.ts` proxy's own rewrites) runs.

The built app is served under a strict Content-Security-Policy
(`default-src 'none'; script-src 'self'; style-src 'self'; font-src 'self';
connect-src 'self'; ...`, defined as `SPA_CSP` in
`src/prometheus/webgateway/headers.py`) with no third-party origin -- which is
why the fonts are bundled from `@fontsource/*` rather than loaded from Google
Fonts. Anything that needs an inline script/style or an external origin (a CDN
stylesheet, an analytics snippet) must be added to that policy deliberately,
not worked around.

## Node version

CI, the npm audit and the container build use Node 24 LTS. Node 20 reached end-of-life
in April 2026 and receives no security fixes; the toolchain (Vite 6, Vitest 4)
still runs on it, but do not rely on that for anything you deploy.

## Scripts

- `npm run dev` -- Vite dev server with the API proxy.
- `npm run build` -- typecheck + production build (`dist/`, served for
  real by `prometheus.webgateway` -- see above).
- `npm run lint` -- ESLint.
- `npm run typecheck` -- `tsc --noEmit`.
- `npm run test` -- Vitest + React Testing Library.


## Hosting the static build on Vercel (a demo of the interface only)

`vercel.json` makes Vercel build and serve `frontend/` as a single-page app. **What this gives you is the
interface, not the product:** the app calls `/api/jobs/*` and `/api/dashboard/*`, and those are served by the
Python gateway (`prometheus.webgateway`), which does not run on Vercel. Without a backend the pages load and
every data request fails. To make it work, run the gateway somewhere you control and add a rewrite from
`/api/:path*` to it in `vercel.json`. Nothing about the research API's authentication changes.

```bash
cd frontend && npx vercel login && npx vercel          # preview deployment
```

Vercel's AI Gateway keys (`vck_...`) are for model calls and are not a deployment credential; this project makes
no model calls. Never commit a key; give Vercel secrets through its dashboard or `vercel env`.
