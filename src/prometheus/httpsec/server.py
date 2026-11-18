"""The one hardened uvicorn configuration every process in this project
ships with. A function rather than three copies of a keyword list, so the
gateway, dashboard and job API cannot drift apart -- and so real-socket
tests run the SAME settings production does instead of a lookalike."""

from __future__ import annotations

from pathlib import Path
from typing import Any


def uvicorn_options(
    *,
    host: str,
    port: int,
    tls_cert: Path | None,
    tls_key: Path | None,
    max_connections: int,
) -> dict[str, Any]:
    return {
        "host": host,
        "port": port,
        "workers": 1,
        "loop": "asyncio",
        "http": "h11",
        "ws": "none",
        "interface": "asgi3",
        "lifespan": "on",
        "proxy_headers": False,
        "access_log": False,
        # Each app writes its own structured log, and uvicorn's `server: uvicorn`
        # banner is implementation detail a client has no use for.
        "server_header": False,
        "limit_concurrency": max_connections,
        "backlog": 64,
        "timeout_keep_alive": 5,
        "timeout_graceful_shutdown": 20,
        "h11_max_incomplete_event_size": 16384,
        "ssl_certfile": str(tls_cert) if tls_cert else None,
        "ssl_keyfile": str(tls_key) if tls_key else None,
    }
