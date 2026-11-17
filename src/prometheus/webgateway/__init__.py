"""A local static-file + reverse-proxy gateway over the two existing
research backends (`service.application.ResearchService`,
`dashboard.app.DashboardService`), so the built frontend
(`frontend/dist/`, produced by `npm run build`) can actually be served
and clicked through end to end -- `npm run build`'s output was
previously unused by anything in this repository.

This is NOT a production reverse proxy: no TLS termination beyond the
same `--tls-cert`/`--tls-key` flag every other local ASGI app in this
project already takes, no multi-tenant routing, no caching, no rate
limiting. It replays Vite's own dev-only proxy rewrites
(`/api/jobs/*` -> the jobs API with that prefix stripped, `/api/dashboard/*`
-> the dashboard app with that prefix rewritten to `/dashboard`) so the
SAME already-built frontend assets work unmodified against a real,
non-dev-server origin. The static shell itself is unauthenticated,
exactly as true today of Vite's dev server on `:5173`; the client's
`Authorization` header is forwarded to the upstream unchanged, so data
calls are gated exactly as they already are.
"""
