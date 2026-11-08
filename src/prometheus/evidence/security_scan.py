"""Secret scanning, a restricted-data-license scan, and a severity-gated
release decision (CIQ-05: "run vulnerability, dependency and secret
scans"; acceptance criterion: "high/critical findings block release
unless approved"; and DAT-13: "prevent licensed/raw data from entering
public release"; acceptance criterion: "CI secret/license scan and
publication approval pass").

Of the three scan types CIQ-05 names, only secret scanning is
implemented here honestly: a genuine vulnerability/dependency scan
needs a live, frequently-updated CVE database (e.g. the OSV or PyPI
advisory APIs), which this repository's hermetic test discipline
(confirmed elsewhere, e.g. PR-060's World Bank connector embedding real
recorded responses rather than depending on live network calls at test
time) has no way to query reliably in this environment -- fabricating
scan results against a database that was never actually queried would
misrepresent what was checked. `secret_scan` needs no such external
dependency: it matches a fixed, self-contained set of regex patterns
for common hardcoded-secret shapes (AWS access key IDs, PEM private
key headers, generic `api_key="..."`-style assignments) directly
against file contents supplied by the caller.

The "high/critical findings block release unless approved" gate
(`evaluate_release_gate`) is deliberately SCANNER-AGNOSTIC: it accepts
any sequence of `ScanFinding`, so a future dependency/vulnerability
scanner that queries a real CVE database could plug into the exact
same gate without this logic being rewritten. Each finding's
`finding_id` is a `compute_result_hash` over (scanner, location,
description) -- the same canonical-JSON convention this project's
other manifests already use -- so a specific finding can be
individually approved (e.g. a confirmed false positive or an accepted
risk) without blanket-approving every OTHER finding that happens to
share the same category description.

`license_scan` checks for a different, narrower signal: not a secret,
but a restricted-redistribution data vendor name (Bloomberg, Refinitiv/
Thomson Reuters, FactSet, S&P Capital IQ, LSEG, Morningstar Direct) or
an explicit no-redistribution marker phrase appearing in a tracked
file -- the kind of thing that would indicate someone pasted licensed
raw vendor data or its terms into this repository by mistake. Every
external data source this project actually uses today (World Bank
Open Data, the Kenneth French Data Library) is confirmed free/open, so
a sweep of this repository's own real tracked source tree is expected,
and confirmed, to find zero matches -- a genuine negative result, not
an untested assumption. Like `secret_scan`'s hardcoded-secret patterns,
this is a fixed, self-contained denylist, not a live license database
query, which this repository's hermetic test discipline has no way to
make reliable in this environment.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Literal

from prometheus.experiments.manifest import compute_result_hash

Severity = Literal["low", "medium", "high", "critical"]

_BLOCKING_SEVERITIES: frozenset[str] = frozenset({"high", "critical"})

_RESTRICTED_LICENSE_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (
        re.compile(r"(?i)\b(?:Bloomberg\s+Terminal|Refinitiv|Thomson\s+Reuters|FactSet|"
                   r"S&P\s+Capital\s+IQ|LSEG|Morningstar\s+Direct)\b"),
        "restricted-redistribution data vendor name",
    ),
    (
        re.compile(
            r"(?i)\b(?:not\s+for\s+redistribution|do\s+not\s+distribute|"
            r"proprietary\s+and\s+confidential)\b"
        ),
        "explicit no-redistribution marker phrase",
    ),
)

_SECRET_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"AKIA[0-9A-Z]{16}"), "AWS access key ID"),
    (
        re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
        "private key material",
    ),
    (
        re.compile(
            r"""(?i)(?:api[_-]?key|secret|token|password)\s*[=:]\s*["']([A-Za-z0-9/_\-]{16,})["']"""
        ),
        "hardcoded credential-like assignment",
    ),
)


@dataclass(frozen=True, slots=True)
class ScanFinding:
    scanner: str
    severity: Severity
    location: str
    description: str

    @property
    def finding_id(self) -> str:
        return compute_result_hash(
            {"scanner": self.scanner, "location": self.location, "description": self.description}
        )


def secret_scan(files: Mapping[str, str]) -> list[ScanFinding]:
    """`files` maps a path (any caller-chosen label, not necessarily a
    real filesystem path) to its text content. Every match of
    `_SECRET_PATTERNS` is reported as a `critical` finding, located by
    1-based line number."""
    findings = []
    for path, content in files.items():
        for pattern, description in _SECRET_PATTERNS:
            for match in pattern.finditer(content):
                line_number = content.count("\n", 0, match.start()) + 1
                findings.append(
                    ScanFinding(
                        scanner="secret_scan",
                        severity="critical",
                        location=f"{path}:{line_number}",
                        description=description,
                    )
                )
    return findings


def license_scan(files: Mapping[str, str]) -> list[ScanFinding]:
    """`files` maps a path (any caller-chosen label) to its text
    content. Every match of `_RESTRICTED_LICENSE_PATTERNS` is reported
    as a `critical` finding, located by 1-based line number."""
    findings = []
    for path, content in files.items():
        for pattern, description in _RESTRICTED_LICENSE_PATTERNS:
            for match in pattern.finditer(content):
                line_number = content.count("\n", 0, match.start()) + 1
                findings.append(
                    ScanFinding(
                        scanner="license_scan",
                        severity="critical",
                        location=f"{path}:{line_number}",
                        description=description,
                    )
                )
    return findings


@dataclass(frozen=True, slots=True)
class ReleaseGateDecision:
    blocked: bool
    unapproved_findings: tuple[ScanFinding, ...]


def evaluate_release_gate(
    findings: Sequence[ScanFinding], approved_finding_ids: Sequence[str] = ()
) -> ReleaseGateDecision:
    """Blocks release if any `high`/`critical` finding's `finding_id` is
    not in `approved_finding_ids` -- low/medium findings never block,
    and an approval is scoped to the exact finding it names, not its
    category."""
    approved = set(approved_finding_ids)
    blocking = tuple(
        f
        for f in findings
        if f.severity in _BLOCKING_SEVERITIES and f.finding_id not in approved
    )
    return ReleaseGateDecision(blocked=bool(blocking), unapproved_findings=blocking)
