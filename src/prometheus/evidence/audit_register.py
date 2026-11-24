"""The audit response register: every work package of a technical audit, its status and evidence.

A review (`ECONOSIM_Full_Technical_Research_Audit`, 24 November 2026, documentation-based) listed
work packages, a risk register, a roadmap and a 20-criterion weighted score. This module keeps the
repository's answer to it as DATA (`docs/audit/register.json`) rather than prose, so it can be
checked:

- the scorecard's weights sum to 100 and its weighted mean is recomputed (the audit's own figure,
  8.118);
- every item has a status from a fixed vocabulary and an evidence level from the audit's E0-E4
  scale;
- an item marked `done` or `partial` must cite evidence, and every cited path must exist;
- `docs/audit/REGISTER.md` is RENDERED from the data, and a test fails if it is stale.

What it deliberately does not do: change a score. The scores are the reviewer's judgments; the
audit's own rule is that a criterion moves toward 10 only with independent evidence (E3 or E4), and
nothing here is. The register records what exists and what is missing, not a higher grade.

    python -m prometheus.evidence.audit_register render     # rewrite docs/audit/REGISTER.md
    python -m prometheus.evidence.audit_register check      # validate, and fail if it is stale
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from collections.abc import Sequence
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
REGISTER_PATH = ROOT / "docs" / "audit" / "register.json"
RENDERED_PATH = ROOT / "docs" / "audit" / "REGISTER.md"
GROUP_TITLES = {
    "science": "Scientific redesign (SCI)",
    "math": "Mathematical verification (M)",
    "data": "Data and leakage (D)",
    "linux": "Linux release engineering (L)",
    "quality": "Quality, security and UX",
    "roadmap": "v1.0 roadmap milestones",
    "risk": "Risk register",
}
STATUS_ORDER = ("done", "partial", "needs_maintainer", "needs_external", "not_started")


class RegisterError(ValueError):
    """The register is malformed or contradicts the repository."""


def load(path: Path = REGISTER_PATH) -> dict[str, Any]:
    document: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return document


def weighted_score(document: dict[str, Any]) -> float:
    criteria = document["scorecard"]["criteria"]
    total = sum(c["weight"] for c in criteria)
    return float(sum(c["weight"] * c["score"] for c in criteria) / total)


def problems(
    document: dict[str, Any], root: Path = ROOT, ignore: frozenset[str] = frozenset()
) -> list[str]:
    found: list[str] = []
    criteria = document["scorecard"]["criteria"]
    if sum(c["weight"] for c in criteria) != 100:
        found.append("the scorecard weights do not sum to 100")
    for c in criteria:
        if not 0.0 <= c["score"] <= 10.0 or c["weight"] <= 0:
            found.append(f"criterion {c['id']}: weight must be positive and score in [0, 10]")
    ids = [item["id"] for item in document["items"]]
    for duplicate in sorted({i for i in ids if ids.count(i) > 1}):
        found.append(f"duplicate item id {duplicate}")
    for item in document["items"]:
        label = item["id"]
        if item["status"] not in document["statuses"]:
            found.append(f"{label}: unknown status {item['status']!r}")
        if item["evidence_level"] not in document["evidence_levels"]:
            found.append(f"{label}: unknown evidence level {item['evidence_level']!r}")
        if item["status"] in ("done", "partial") and not item["evidence"]:
            found.append(f"{label}: marked {item['status']} but cites no evidence")
        if item["status"] == "done" and item["evidence_level"] in ("E0", "E1"):
            found.append(f"{label}: marked done on E0/E1 evidence alone")
        if item["status"] == "done" and item["remaining"].lower().startswith("not "):
            found.append(f"{label}: marked done but says something is not done")
        if item["evidence_level"] in ("E3", "E4"):
            found.append(f"{label}: claims {item['evidence_level']}; nothing here is independent")
        for path in item["evidence"]:
            if path not in ignore and not (root / path).exists():
                found.append(f"{label}: cited evidence {path} does not exist")
    return found


def _cell(text: str) -> str:
    return text.replace("|", "\\|").replace("\n", " ")


def render(document: dict[str, Any]) -> str:
    audit = document["audit"]
    items = document["items"]
    counts = Counter(i["status"] for i in items)
    lines = [
        "# Audit response register",
        "",
        "*Generated from `register.json` by "
        "`python -m prometheus.evidence.audit_register render`; do not edit.*",
        "",
        f"The review: **{audit['title']}**, {audit['date']}, "
        f"of version {audit['reviewed_version']} "
        f"(commit `{audit['reviewed_commit']}`). It was {audit['nature']}.",
        "",
        "This register records, for each of the audit's work packages, what exists in the "
        "repository and what does",
        "not. **It does not change any score**: see the rule below. "
        "Evidence levels follow the audit's scale:",
        "",
    ]
    lines += [f"- **{k}**: {v}" for k, v in document["evidence_levels"].items()]
    lines += ["", "Statuses:", ""]
    lines += [f"- **{k}**: {v}" for k, v in document["statuses"].items()]
    summary = ", ".join(f"{counts[s]} {s.replace('_', ' ')}" for s in STATUS_ORDER if counts[s])
    lines += ["", f"**{len(items)} items: {summary}.** No item is above evidence level E2.", ""]
    for group, title in GROUP_TITLES.items():
        rows = [i for i in items if i["group"] == group]
        if not rows:
            continue
        lines += [
            f"## {title}",
            "",
            "| ID | Item | Status | Level | Evidence | What is missing | Who |",
            "| --- | --- | --- | --- | --- | --- | --- |",
        ]
        for i in rows:
            evidence = "<br>".join(f"`{p}`" for p in i["evidence"]) or "none"
            lines.append(
                f"| {i['id']} | {_cell(i['title'])} | {i['status'].replace('_', ' ')} | "
                f"{i['evidence_level']} | "
                f"{evidence} | {_cell(i['remaining'])} | {i['who']} |"
            )
        lines.append("")
    score = document["scorecard"]
    lines += [
        "## Scorecard (the reviewer's baseline)",
        "",
        f"Formula: `{score['formula']}` = **{weighted_score(document):.3f}**, "
        f"recomputed from the table. {score['rescore_rule']}",
        "",
        "| Criterion | Weight | Score | What prevents 10 |",
        "| --- | --- | --- | --- |",
    ]
    lines += [
        f"| {c['criterion']} | {c['weight']}% | {c['score']} | {_cell(c['what_prevents_10'])} |"
        for c in score["criteria"]
    ]
    return "\n".join(lines) + "\n"


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("command", choices=("render", "check"))
    args = parser.parse_args(argv)
    document = load()
    # `render` writes the very file the register cites, so it cannot require it to exist yet
    found = problems(
        document,
        ignore=frozenset({"docs/audit/REGISTER.md"}) if args.command == "render" else frozenset(),
    )
    if found:
        print("register problems:", *found, sep="\n  ", file=sys.stderr)
        return 1
    text = render(document)
    if args.command == "render":
        RENDERED_PATH.write_text(text, encoding="utf-8")
        print("wrote", RENDERED_PATH)
        return 0
    if not RENDERED_PATH.exists() or RENDERED_PATH.read_text(encoding="utf-8") != text:
        print("REGISTER.md is stale: run `render`", file=sys.stderr)
        return 1
    print(
        f"the register is valid and rendered ({len(document['items'])} items, "
        f"score {weighted_score(document):.3f})"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
