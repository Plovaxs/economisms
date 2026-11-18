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

from prometheus.httpsec.server import uvicorn_options
from prometheus.webgateway.app import GatewayConfig, WebGatewayService

_DEFAULT_DIST = Path(__file__).resolve().parents[3] / "frontend" / "dist"
_DEFAULTS = GatewayConfig()


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
    serve.add_argument(
        "--max-connections",
        type=int,
        default=128,
        help="concurrent connections accepted before new ones get 503",
    )
    serve.add_argument(
        "--max-request-body-bytes", type=int, default=_DEFAULTS.max_request_body_bytes
    )
    serve.add_argument("--max-response-bytes", type=int, default=_DEFAULTS.max_response_bytes)
    serve.add_argument(
        "--upstream-timeout",
        type=float,
        default=_DEFAULTS.upstream_timeout_seconds,
        help="seconds to wait for a backend before answering 502",
    )
    serve.add_argument("--max-upstream-inflight", type=int, default=_DEFAULTS.max_upstream_inflight)
    serve.add_argument(
        "--rate-limit-per-second",
        type=float,
        default=_DEFAULTS.rate_limit_per_second,
        help="sustained requests/second allowed per client address; 0 disables limiting",
    )
    serve.add_argument("--rate-limit-burst", type=int, default=_DEFAULTS.rate_limit_burst)
    serve.add_argument(
        "--trusted-proxy-hops",
        type=int,
        default=0,
        help=(
            "number of trusted reverse proxies in front of this gateway; the client "
            "address is then read from that many entries from the right of "
            "X-Forwarded-For. 0 (the default) ignores X-Forwarded-For entirely"
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
        if args.max_connections < 1:
            raise ValueError("--max-connections must be positive")
        config = GatewayConfig(
            max_request_body_bytes=args.max_request_body_bytes,
            max_response_bytes=args.max_response_bytes,
            upstream_timeout_seconds=args.upstream_timeout,
            max_upstream_inflight=args.max_upstream_inflight,
            rate_limit_per_second=args.rate_limit_per_second,
            rate_limit_burst=args.rate_limit_burst,
            trusted_proxy_hops=args.trusted_proxy_hops,
        )
        app = WebGatewayService(args.dist, args.jobs_url, args.dashboard_url, config=config)
        import uvicorn

        logging.basicConfig(level=logging.INFO, format="%(message)s")
        scheme = "https" if args.tls_cert else "http"
        print(f"serving on {scheme}://{args.host}:{args.port}")
        print(f"  static root:   {args.dist}")
        print(f"  jobs API:      {args.jobs_url} (proxied at /api/jobs)")
        print(f"  dashboard:     {args.dashboard_url} (proxied at /api/dashboard)")
        uvicorn.run(
            app,
            **uvicorn_options(
                host=args.host,
                port=args.port,
                tls_cert=args.tls_cert,
                tls_key=args.tls_key,
                max_connections=args.max_connections,
            ),
        )
    except (ValueError, OSError) as exc:
        parser.error(str(exc))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
