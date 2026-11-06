"""Extract the complete blueprint checklist and link unreviewed repository notes.

Generated note links are traceability hints, not proof of implementation or
acceptance. The parser preserves source rows/pages and rejects missing,
duplicate or malformed requirements rather than silently shrinking scope.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
from collections import Counter
from pathlib import Path
from typing import Any

_ID = re.compile(r"^\s*([A-Z]{3,4}-\d{2})\s{2,}")


def parse_blueprint_checklists(text: str, *, expected_count: int = 374) -> list[dict[str, Any]]:
    items = []
    seen: set[str] = set()
    for number, page in enumerate(text.split("\f"), 1):
        lines = page.splitlines()
        header = next(
            (
                line
                for line in lines
                if "Required capability or control" in line and "Acceptance evidence" in line
            ),
            None,
        )
        if header is None:
            continue
        requirement_column, acceptance_column = header.index("Required"), header.index("Acceptance")
        for index, line in enumerate(lines):
            match = _ID.match(line)
            if match is None:
                continue
            identifier = match[1]
            if identifier in seen:
                raise ValueError(f"duplicate blueprint requirement: {identifier}")
            rows = [line]
            for continuation in lines[index + 1 :]:
                if (
                    _ID.match(continuation)
                    or re.match(r"^\d{2} [A-Z]{3} \d{4} \|", continuation)
                    or continuation.startswith("PROJECT PROMETHEUS")
                ):
                    break
                if continuation.strip():
                    rows.append(continuation)
            requirement = " ".join(
                row[requirement_column:acceptance_column].strip()
                for row in rows
                if row[requirement_column:acceptance_column].strip()
            )
            acceptance = " ".join(
                row[acceptance_column:].strip() for row in rows if row[acceptance_column:].strip()
            )
            if (
                not requirement
                or not acceptance
                or not any("[ ] NOT VERIFIED" in row for row in rows)
            ):
                raise ValueError(f"incomplete or unexpected blueprint checklist row: {identifier}")
            seen.add(identifier)
            items.append(
                {
                    "id": identifier,
                    "category": identifier.split("-")[0],
                    "requirement": requirement,
                    "acceptance_criterion": acceptance,
                    "source_pdf_page": number,
                    "source_rows": rows,
                    "track": "separately_gated_live_extension"
                    if identifier.startswith("EXT-")
                    else "research_enterprise",
                    "acceptance_status": "NOT VERIFIED",
                    "owner": None,
                    "independent_reviewer": None,
                }
            )
    if len(items) != expected_count:
        raise ValueError(
            f"expected {expected_count} checklist requirements, extracted {len(items)}"
        )
    return items


def link_repository_notes(items: list[dict[str, Any]], checklist: str) -> list[dict[str, Any]]:
    known = {item["id"] for item in items}
    notes: dict[str, list[dict[str, Any]]] = {identifier: [] for identifier in known}
    for number, line in enumerate(checklist.splitlines(), 1):
        if not line.startswith("|"):
            continue
        columns = line.split("|")
        if len(columns) < 5:
            continue
        identifiers = set(re.findall(r"\b[A-Z]{3,4}-\d{2}\b", columns[1])) & known
        for identifier in identifiers:
            notes[identifier].append(
                {
                    "checklist_line": number,
                    "id_column": columns[1].strip(),
                    "requirement_note": columns[2].strip(),
                    "evidence_note": "|".join(columns[3:-1]).strip(),
                }
            )
    return [
        dict(
            item,
            repository_notes=notes[item["id"]],
            implementation_evidence_status="repository_notes_present"
            if notes[item["id"]]
            else "not_evidenced",
        )
        for item in items
    ]


def build_requirement_register(pdf_path: Path, checklist_path: Path) -> dict[str, Any]:
    completed = subprocess.run(
        ["pdftotext", "-layout", str(pdf_path), "-"],
        check=True,
        capture_output=True,
        text=True,
        timeout=60,
    )
    items = link_repository_notes(
        parse_blueprint_checklists(completed.stdout), checklist_path.read_text()
    )
    categories = Counter(item["category"] for item in items)
    if len(categories) != 29 or categories["EXT"] != 12:
        raise ValueError(
            "blueprint category/track cardinality differs from the 374-item specification"
        )
    linked = sum(bool(item["repository_notes"]) for item in items)
    return {
        "schema_version": 1,
        "blueprint_sha256": hashlib.sha256(pdf_path.read_bytes()).hexdigest(),
        "extracted_text_sha256": hashlib.sha256(completed.stdout.encode()).hexdigest(),
        "checklist_notes_sha256": hashlib.sha256(checklist_path.read_bytes()).hexdigest(),
        "summary": {
            "requirements": len(items),
            "categories": len(categories),
            "research_enterprise": len(items) - categories["EXT"],
            "separately_gated_live_extension": categories["EXT"],
            "with_repository_notes": linked,
            "without_repository_notes": len(items) - linked,
            "independently_verified": 0,
        },
        "category_counts": dict(sorted(categories.items())),
        "status_meaning": (
            "Repository notes are unreviewed links, not proof of implementation or acceptance."
        ),
        "items": items,
    }


def main(argv: list[str] | None = None) -> int:
    from prometheus.evidence.export import export_evidence_bundle

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pdf", required=True, type=Path)
    parser.add_argument("--checklist", type=Path, default=Path("CHECKLIST_STATUS.md"))
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        register = build_requirement_register(args.pdf, args.checklist)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        export_evidence_bundle(register, args.output)
    except (ValueError, OSError, subprocess.SubprocessError) as exc:
        parser.error(str(exc))
    print(json.dumps(register["summary"], indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
