"""`econosim`: one top-level command dispatching to each subsystem's own CLI.

Every subsystem under `prometheus/` already has its own real
`python -m prometheus.<name>` entry point with its own `argparse` parser
(see each module's `__main__.py`). This is a thin dispatcher over those
same `main(argv) -> int` functions -- nothing is reimplemented or
reparsed -- so an installed checkout exposes one discoverable command
(`econosim <subsystem> ...`) instead of five module paths a user has to
already know by name.

Each subsystem's `main` is imported lazily, inside its own wrapper below,
rather than at the top of this module: `recovery.__main__` pulls in the
`recovery` extra's `cryptography`, and `service.__main__` pulls in the
`service` extra's `jsonschema`, at *their own* module level. Importing
either eagerly here would mean `import prometheus.cli` itself -- and so
every use of the installed `econosim` command, including `--help` --
failed on a base install that never opted into those extras.
"""

from __future__ import annotations

import sys
from collections.abc import Callable
from importlib.metadata import PackageNotFoundError, version


def _dashboard_main(argv: list[str] | None) -> int:
    from prometheus.dashboard.__main__ import main

    return main(argv)


def _jobs_main(argv: list[str] | None) -> int:
    from prometheus.jobs.__main__ import main

    return main(argv)


def _recovery_main(argv: list[str] | None) -> int:
    from prometheus.recovery.__main__ import main

    return main(argv)


def _service_main(argv: list[str] | None) -> int:
    from prometheus.service.__main__ import main

    return main(argv)


def _webgateway_main(argv: list[str] | None) -> int:
    from prometheus.webgateway.__main__ import main

    return main(argv)


_Main = Callable[[list[str] | None], int]

_SUBCOMMANDS: dict[str, tuple[str, _Main]] = {
    "dashboard": (
        "Run the research dashboard as a real, standalone ASGI process.",
        _dashboard_main,
    ),
    "jobs": (
        "Trusted-operator CLI for durable local research jobs.",
        _jobs_main,
    ),
    "recovery": (
        "Local encrypted snapshots: keygen, create, verify, restore. Needs the 'recovery' extra.",
        _recovery_main,
    ),
    "service": (
        "Run the research API with private credentials and workers. Needs the 'service' extra.",
        _service_main,
    ),
    "webgateway": (
        "Serve the built frontend plus a reverse proxy to the backends.",
        _webgateway_main,
    ),
}


def _version() -> str:
    try:
        return version("prometheus-econ")
    except PackageNotFoundError:
        return "unknown (not installed as a package)"


def _print_help() -> None:
    print("usage: econosim <subsystem> [args...]")
    print("       econosim --version")
    print()
    print("subsystems:")
    width = max(len(name) for name in _SUBCOMMANDS)
    for name, (summary, _) in sorted(_SUBCOMMANDS.items()):
        print(f"  {name:<{width}}  {summary}")
    print()
    print("Each subsystem has its own --help, e.g. `econosim dashboard --help`.")


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else list(argv)
    if not args:
        _print_help()
        return 1
    if args[0] in ("-h", "--help"):
        _print_help()
        return 0
    if args[0] in ("-V", "--version"):
        print(f"econosim {_version()}")
        return 0

    name, rest = args[0], args[1:]
    entry = _SUBCOMMANDS.get(name)
    if entry is None:
        print(f"econosim: unknown subsystem {name!r}", file=sys.stderr)
        _print_help()
        return 1
    _, run = entry
    return run(rest)


if __name__ == "__main__":
    raise SystemExit(main())
