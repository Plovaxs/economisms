"""`econosim modelzoo`: look at the model registry and its graph from the command line."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence

from prometheus.modelzoo import graph
from prometheus.modelzoo.registry import ENTRIES


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="econosim modelzoo", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("coverage", help="what became of each requested model")
    sub.add_parser("validate", help="check the registry against the code and the records")
    sub.add_parser("verdicts", help="every recorded hypothesis and its verdict")
    p_graph = sub.add_parser("graph", help="print the graph")
    p_graph.add_argument("--format", choices=("json", "mermaid"), default="json")
    p_near = sub.add_parser("neighbours", help="every edge touching one model")
    p_near.add_argument("model")
    p_list = sub.add_parser("list", help="list models, optionally by status")
    p_list.add_argument("--status", choices=("implemented", "existing", "not_built"))
    args = parser.parse_args(sys.argv[1:] if argv is None else list(argv))

    if args.command == "coverage":
        print(json.dumps(graph.coverage(), indent=2, sort_keys=True))
    elif args.command == "validate":
        problems = graph.validate()
        for line in problems:
            print(line)
        print(
            "registry consistent with the repository"
            if not problems
            else f"{len(problems)} problem(s)"
        )
        return 1 if problems else 0
    elif args.command == "verdicts":
        for label, verdict in sorted(graph.recorded_verdicts().items()):
            print(f"{label:7s} {verdict}")
    elif args.command == "graph":
        if args.format == "json":
            print(json.dumps(graph.build_graph().to_json(), indent=2))
        else:
            print(graph.to_mermaid())
    elif args.command == "neighbours":
        edges = graph.build_graph().neighbours(args.model)
        if not edges:
            print(f"no edges for {args.model!r}", file=sys.stderr)
            return 2
        for edge in edges:
            print(f"{edge['source']} --{edge['kind']}--> {edge['target']}")
    else:
        for e in ENTRIES:
            if e.role == "model" and (args.status is None or e.status == args.status):
                print(f"{e.id:24s} {e.status:12s} {e.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
