# Audit baseline (roadmap milestone M0)

The audit's first milestone is "pin the release and record the baseline": the commit, a source manifest, the
issue register and the score rubric. This is that record.

| | |
| --- | --- |
| The review | *ECONOSIM Full Technical Research Audit*, 24 November 2026, "documentation-based assessment" |
| What it reviewed | repository documentation and recent commit metadata, version 0.5.2 |
| The commit it names | `05905835dbb6729bb9f79c629027b8ba47176e44` (the desktop-icon commit, after release 0.5.2) |
| Source manifest of that commit | [`source_manifest_05905835.txt`](./source_manifest_05905835.txt): 877 files, each with the SHA-256 of its content at that commit |
| Issue register | [`REGISTER.md`](./REGISTER.md), generated from [`register.json`](./register.json) |
| Score rubric | the 20 weighted criteria in the register; `sum(weight x score) / sum(weight)` = 8.118, recomputed by a test |

## What the audit said about itself

It reviewed documentation, not code: **no fresh build, test run, benchmark, installation, source audit, security
assessment or peer review was done for it**, its numerical claims are the repository's own, and its weights, scores
and thresholds are the reviewer's judgments. Its own evidence scale places that kind of review at E1 (a documented
claim) with some E2 (an inspectable test) behind it, and it explicitly claims no E3 (independently executed on a
clean environment) and no E4 (replicated by an external reviewer).

## What the register adds, and what it does not

For each of its 58 items (work packages, risks, milestones) the register says what now exists in the repository,
with the files that are the evidence, and what is still missing. It **does not change a score**: the audit's own
reassessment rule re-scores "from actual evidence after each milestone", and no criterion moves toward 10 without
independent evidence, which nothing here is. The largest gap the audit named, independent validation (5.5 of 10),
is unchanged because it needs people outside the project: external replication, review, and users.

## Verifying the manifest

```
git cat-file -e 05905835dbb6729bb9f79c629027b8ba47176e44     # the commit must be in your clone
git ls-tree -r 05905835dbb6729bb9f79c629027b8ba47176e44 | wc -l
```

`tests/unit/test_audit_register.py` recomputes every entry from git when that commit is present.
