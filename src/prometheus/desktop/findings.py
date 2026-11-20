"""The research findings, read from `docs/RESULTS_AND_LIMITATIONS.md` -- the one place they live.

The window does not keep its own copy of what the project found. A copy would drift from the
document the evidence discipline actually points at, and a window that says "Finding 13" while the
document says something else is worse than no window. So the findings page *parses* the document:
the gate decision, `## Finding N (PR-xxx): title` sections, and the closing list of known
limitations, each kept as the Markdown it was written in (Qt renders Markdown natively).

The document ships with a checkout, not with the installed package; when it is absent the page
says so rather than showing anything invented.

Headings inside fenced code blocks are not headings: a `## ` at the start of a line in a quoted
snippet must not start a new finding.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

DOCUMENT = Path(__file__).resolve().parents[3] / "docs" / "RESULTS_AND_LIMITATIONS.md"

_FINDING = re.compile(r"^## Finding (?P<number>\d+) \((?P<pr>[^)]*)\): (?P<title>.+?)\s*$")
_GATE = re.compile(r"^## The overall gate decision: (?P<decision>.+?)\s*$")
_LIMITS = re.compile(r"^## Known limitations\b.*$")
_FENCE = re.compile(r"^\s*(```|~~~)")


@dataclass(frozen=True, slots=True)
class Finding:
    number: int
    pr: str
    """As written: `PR-142`, or `PR-153, revised PR-177`."""
    title: str
    markdown: str

    @property
    def summary(self) -> str:
        """The first paragraph, as plain text on one line."""
        for paragraph in re.split(r"\n\s*\n", self.markdown.strip()):
            text = re.sub(r"\s+", " ", paragraph).strip()
            if text and not text.startswith(("|", "```", "#", "- ", "* ")):
                return re.sub(r"[*_`]", "", text)
        return ""


@dataclass(frozen=True, slots=True)
class FindingsDocument:
    available: bool
    gate_decision: str
    """The decision named in the document's own heading (`NO-GO`), `""` if absent."""
    gate_markdown: str
    findings: tuple[Finding, ...]
    limitations_markdown: str

    def get(self, number: int) -> Finding:
        for finding in self.findings:
            if finding.number == number:
                return finding
        raise KeyError(number)


_EMPTY = FindingsDocument(False, "", "", (), "")


def parse(text: str) -> FindingsDocument:
    """Split the document into its gate section, numbered findings and limitations."""
    sections: list[tuple[str, list[str]]] = []
    in_fence = False
    for line in text.splitlines():
        if _FENCE.match(line):
            in_fence = not in_fence
        if not in_fence and line.startswith("## "):
            sections.append((line, []))
        elif sections:
            sections[-1][1].append(line)
    gate_decision, gate_markdown, limitations = "", "", ""
    findings: list[Finding] = []
    for heading, body in sections:
        markdown = "\n".join(body).strip("\n")
        if found := _FINDING.match(heading):
            findings.append(
                Finding(int(found["number"]), found["pr"], found["title"], markdown.strip())
            )
        elif found := _GATE.match(heading):
            gate_decision, gate_markdown = found["decision"], markdown.strip()
        elif _LIMITS.match(heading):
            limitations = markdown.strip()
    return FindingsDocument(
        available=bool(findings or gate_markdown),
        gate_decision=gate_decision,
        gate_markdown=gate_markdown,
        findings=tuple(sorted(findings, key=lambda finding: finding.number)),
        limitations_markdown=limitations,
    )


def load(path: Path = DOCUMENT) -> FindingsDocument:
    try:
        return parse(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError):
        return _EMPTY
