# NIST SSDF (SP 800-218) gap assessment

CMP-02: map software controls to NIST SSDF secure SDLC practices;
acceptance — "gap assessment and prioritized remediation recorded."

**Technical self-assessment, not a certification or audit.** Maps this
repository's real build/test/release practices against the Secure
Software Development Framework's four practice groups (Prepare the
Organization, Protect the Software, Produce Well-Secured Software,
Respond to Vulnerabilities), with gaps named plainly and a rough
remediation priority — not a claim of SSDF conformance.

## PO — Prepare the Organization

| Practice (representative) | Control | Gap / remediation |
|---|---|---|
| PO.1 Define security requirements | `docs/THREAT_MODEL.md`, `CONTRIBUTING.md` § Code style | — |
| PO.3 Implement supporting toolchains | `.github/workflows/ci.yml` (lint, type check, test, reproducible build) | — |
| PO.5 Implement and maintain secure environments | `tools/reproducible_build.py`, hash-pinned bootstrap install | — |

## PS — Protect the Software

| Practice (representative) | Control | Gap / remediation |
|---|---|---|
| PS.1 Protect code from unauthorized access/tampering | Git + GitHub hosting; **no branch protection confirmed configured** (SEC-02 open) | **Gap — Priority: medium.** Remediation: enable required-review branch protection on `main` via repository settings; outside this repository's own source tree to prove. |
| PS.2 Provide a mechanism for verifying software release integrity | `tools/reproducible_build.py` (double independent-snapshot rebuild), `docs/release/dependency-sbom.cdx.json` | — |
| PS.3 Archive and protect each software release | Git tags/commits are the release record; **no cryptographic release signing** (SEC-09 open) | **Gap — Priority: low** (research software, not distributed as signed binaries today). Remediation: adopt `cosign`/Sigstore if/when real distribution begins. |

## PW — Produce Well-Secured Software

| Practice (representative) | Control | Gap / remediation |
|---|---|---|
| PW.4 Reuse existing, well-secured software when feasible | `CONTRIBUTING.md` § Code style ("prefer composing an existing module"); `docs/LICENSE_INVENTORY.md` | — |
| PW.5 Configure the compilation/build process to improve security | `mypy --strict`, `ruff check`, hash-pinned deps | — |
| PW.7 Review human-readable code for security weaknesses | `evidence.security_scan` (`secret_scan`/`license_scan`/`pii_scan`), manual review (single-maintainer, no second-party review — gap) | **Gap — Priority: medium.** Automated scans exist; human second-party review does not (same root cause as SEC-02/GOV-03). |
| PW.8 Test executable code to identify vulnerabilities | `pytest` (2,500+ tests), `tests/property/` (Hypothesis) | — |

## RV — Respond to Vulnerabilities

| Practice (representative) | Control | Gap / remediation |
|---|---|---|
| RV.1 Identify and confirm vulnerabilities | `SECURITY.md` (GitHub private vulnerability reporting) | — |
| RV.2 Assess, prioritize, and remediate vulnerabilities | `SECURITY.md` § Response owner and patch cadence | — |
| RV.3 Analyze vulnerabilities for root cause | No formal live-CVE/dependency-scanning pipeline | **Gap — Priority: medium.** Remediation: wire a real dependency-advisory scanner (e.g. `pip-audit`/OSV) into CI once this environment can reliably reach that service — disclosed elsewhere (`evidence.security_scan`'s own docstring) as not currently queryable from this hermetic test environment. |

## Summary

Strongest coverage: PO (toolchain/build), PW.4/5/8 (reuse, build
config, testing). Weakest: anything requiring a second human
(PS.1/PW.7) or a live external service (RV.3) — both honestly open,
for the same single-maintainer, hermetic-environment reasons named
throughout `CHECKLIST_STATUS.md`.
