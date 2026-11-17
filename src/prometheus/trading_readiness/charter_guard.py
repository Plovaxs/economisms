"""EXT-01: "propose separate legally reviewed product scope for
execution" / "no change to default research API without new charter."
Two enforced properties, not just a docstring claim: (a) this package
is never reachable from the default research API's own import graph,
confirmed by walking it directly rather than trusting that no one
happens to import it today, and (b) the gate's own live-trading
exclusion clause has not silently drifted.
"""

from __future__ import annotations

import ast
from pathlib import Path

from prometheus.evidence.repository_status import current_repository_gate_report

DEFAULT_API_PACKAGES = ("service", "dashboard", "jobs", "orchestration")
REQUIRED_EXCLUSION_SUBSTRINGS = ("live trading", "order routing", "brokerage")


def find_trading_readiness_importers(src_root: Path) -> tuple[Path, ...]:
    """Every `.py` file under `src_root` that imports
    `prometheus.trading_readiness`, directly or via `from ... import`
    (including a relative import). Walks the AST rather than grepping
    text, so a comment or docstring mentioning the package name is
    never mistaken for a real import."""
    hits: list[Path] = []
    for path in sorted(src_root.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import) and any(
                "trading_readiness" in alias.name.split(".") for alias in node.names
            ):
                hits.append(path)
                break
            if isinstance(node, ast.ImportFrom) and "trading_readiness" in (
                node.module or ""
            ).split("."):
                hits.append(path)
                break
    return tuple(hits)


def default_research_api_is_isolated(prometheus_src_root: Path) -> bool:
    """True iff none of the default research API packages
    (service/dashboard/jobs/orchestration) import this package,
    anywhere -- "no change to default research API without new
    charter" made checkable, not just asserted."""
    return all(
        not find_trading_readiness_importers(prometheus_src_root / package)
        for package in DEFAULT_API_PACKAGES
    )


def live_trading_exclusion_is_still_declared() -> bool:
    """True iff `current_repository_gate_report().scope_prohibited`
    still names live trading, order routing and brokerage connections
    as excluded -- so that clause silently drifting would be a loud,
    reviewed diff, not a quiet one."""
    prohibited_text = " ".join(current_repository_gate_report().scope_prohibited).lower()
    return all(substring in prohibited_text for substring in REQUIRED_EXCLUSION_SUBSTRINGS)
