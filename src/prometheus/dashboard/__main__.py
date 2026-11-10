"""Run the research dashboard as a real, standalone ASGI process.

Mirrors `service.__main__`'s own `init-auth`/`serve` shape (the same
credential-provisioning function, reused, not duplicated) -- a second,
small CLI for a second, small ASGI app, the same separation
`dashboard.app`'s own module docstring explains.

`--demo` seeds one real portfolio (`alice`, via genuine
`econosim.agents.Household`/`Firm` postings, not placeholder numbers)
so `/dashboard`'s index page has something real to click through on a
machine with no other setup -- the actual Portfolio milestone this
command exists for: a professor, researcher, or technical recruiter
can run this one command and have a real, browsable demonstration.
"""

from __future__ import annotations

import argparse
import ipaddress
import logging
from pathlib import Path

from prometheus.core.ledger import Ledger
from prometheus.core.money import Money
from prometheus.dashboard.app import DashboardService
from prometheus.econosim.agents import Firm, Household
from prometheus.service.__main__ import provision_credentials
from prometheus.service.auth import CredentialStore


def _demo_portfolio() -> Ledger:
    ledger = Ledger()
    household = Household(ledger, "demo-household")
    firm = Firm(ledger, "demo-firm")
    household.receive_income(Money(50_000, "USD"), step=0, description="demo opening balance")
    household.consume(firm, Money(12_000, "USD"), step=1)
    household.consume(firm, Money(8_000, "USD"), step=2)
    return ledger


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="action", required=True)

    setup = commands.add_parser("init-auth")
    setup.add_argument("--credentials", type=Path, required=True)
    setup.add_argument("--token-file", type=Path, required=True)
    setup.add_argument("--owner", required=True)

    serve = commands.add_parser("serve")
    serve.add_argument("--credentials", type=Path, required=True)
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8766)
    serve.add_argument("--tls-cert", type=Path)
    serve.add_argument("--tls-key", type=Path)
    serve.add_argument(
        "--demo", action="store_true",
        help="seed a real demo portfolio ('alice') so there is something to browse immediately",
    )
    args = parser.parse_args(argv)

    try:
        if args.action == "init-auth":
            provision_credentials(
                args.credentials, args.token_file, owner=args.owner, read_only=True
            )
            print(f"credentials written to {args.credentials}, token to {args.token_file}")
        else:
            address = ipaddress.ip_address(args.host)
            if not 0 <= args.port <= 65535:
                raise ValueError("port must be in [0,65535]")
            if bool(args.tls_cert) != bool(args.tls_key):
                raise ValueError("TLS requires both certificate and key")
            if not address.is_loopback and args.tls_cert is None:
                raise ValueError("non-loopback binding requires TLS")
            credentials = CredentialStore(args.credentials)
            portfolios = {"alice": _demo_portfolio()} if args.demo else {}
            app = DashboardService(credentials, portfolios)
            import uvicorn

            logging.basicConfig(level=logging.INFO, format="%(message)s")
            print(f"serving on http://{args.host}:{args.port}/dashboard")
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
