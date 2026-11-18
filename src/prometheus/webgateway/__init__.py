"""A static-file + reverse-proxy gateway over the two existing research
backends (`service.application.ResearchService`,
`dashboard.app.DashboardService`), so the built frontend
(`frontend/dist/`, produced by `npm run build`) can actually be served
and clicked through end to end.

It replays Vite's own dev-only proxy rewrites (`/api/jobs/*` -> the jobs
API with that prefix stripped, `/api/dashboard/*` -> the dashboard app
with that prefix rewritten to `/dashboard`) so the SAME already-built
frontend assets work unmodified against a real, non-dev-server origin.
The static shell itself is unauthenticated, exactly as true today of
Vite's dev server on `:5173`; the client's `Authorization` header is
forwarded to the upstream unchanged, so data calls are gated exactly as
they already are.

As the one origin a browser talks to, it is also the edge of the
deployment, and carries the edge controls: strict request-target
validation and routing (`routing`), per-client rate limiting
(`ratelimit`), bounded bodies and bounded upstream concurrency, security
and cache headers on every response (`headers`), a hardened HTTP
transport that never follows redirects or honours proxy environment
variables (`proxy`), and a generic-500 catch-all. TLS is the same
`--tls-cert`/`--tls-key` every other ASGI app in this project takes;
this is still a single-host gateway, not a multi-tenant or
horizontally-scaled one (the rate limiter, like the backends' own
limits, is process-local).
"""
