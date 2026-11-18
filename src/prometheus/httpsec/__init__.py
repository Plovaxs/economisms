"""HTTP hardening primitives shared by this project's ASGI apps
(`webgateway`, `dashboard`, `service`).

Each of those is its own small, hand-rolled ASGI service; what they share
is the set of controls that should not be re-derived three times:
response security headers (`headers`), a bounded per-client token-bucket
limiter (`ratelimit`), a bounded in-flight executor that keeps blocking
work off the event loop (`concurrency`), and the one hardened uvicorn
configuration every process ships with (`server`).
"""
