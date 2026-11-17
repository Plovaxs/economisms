"""Run the web gateway as a real, standalone ASGI process.

Mirrors `dashboard.__main__`/`service.__main__`'s own `serve` shape --
a third small CLI for a third small ASGI app, same uvicorn hardening,
same loopback/TLS validation.
"""

from __future__ import annotations

import argparse
import ipaddress
import logging
from pathlib import Path

from prometheus.webgateway.app import WebGatewayService

_DEFAULT_DIST = Path(__file__).resolve().parents[3] / "frontend" / "dist"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="action", required=True)

    serve = commands.add_parser("serve")
    serve.add_argument("--dist", type=Path, default=_DEFAULT_DIST)
    serve.add_argument("--jobs-url", default="http://127.0.0.1:8765")
    serve.add_argument("--dashboard-url", default="http://127.0.0.1:8766")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8080)
    serve.add_argument("--tls-cert", type=Path)
    serve.add_argument("--tls-key", type=Path)
    serve.add_argument(
        "--allow-non-loopback-without-tls",
        action="store_true",
        help=(
            "bind a non-loopback host without TLS -- only when this process's own "
            "context already provides an equivalent trust boundary (e.g. Docker's "
            "own port-publishing isolation, where nothing outside the host can "
            "reach this unless the operator maps the port further). Never pass "
            "this to expose a real network interface directly; the default "
            "(loopback, or TLS for anything else) matches every other local ASGI "
            "app in this project and is unchanged unless this is explicitly set."
        ),
    )
    args = parser.parse_args(argv)

    try:
        address = ipaddress.ip_address(args.host)
        if not 0 <= args.port <= 65535:
            raise ValueError("port must be in [0,65535]")
        if bool(args.tls_cert) != bool(args.tls_key):
            raise ValueError("TLS requires both certificate and key")
        if (
            not address.is_loopback
            and args.tls_cert is None
            and not args.allow_non_loopback_without_tls
        ):
            raise ValueError(
                "non-loopback binding requires TLS, or --allow-non-loopback-without-tls "
                "if this process's own context already provides an equivalent trust "
                "boundary"
            )
        if not args.dist.is_dir():
            raise ValueError(
                f"{args.dist} is not a directory -- has the frontend actually "
                f"been built ('npm run build' in frontend/)?"
            )
        app = WebGatewayService(args.dist, args.jobs_url, args.dashboard_url)
        import uvicorn

        logging.basicConfig(level=logging.INFO, format="%(message)s")
        print(f"serving on http://{args.host}:{args.port}")
        print(f"  static root:   {args.dist}")
        print(f"  jobs API:      {args.jobs_url} (proxied at /api/jobs)")
        print(f"  dashboard:     {args.dashboard_url} (proxied at /api/dashboard)")
        uvicorn.run(
            app,
            host=args.host,
            port=args.port,
            workers=1,
            loop="asyncio",
            http="h11",
            ws="none",
            interface="asgi3",
            lifespan="on",
            proxy_headers=False,
            access_log=False,
            limit_concurrency=32,
            backlog=64,
            timeout_keep_alive=5,
            timeout_graceful_shutdown=20,
            h11_max_incomplete_event_size=16384,
            ssl_certfile=str(args.tls_cert) if args.tls_cert else None,
            ssl_keyfile=str(args.tls_key) if args.tls_key else None,
        )
    except (ValueError, OSError) as exc:
        parser.error(str(exc))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
