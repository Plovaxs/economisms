import pathlib

from prometheus.evidence.security_scan import (
    ReleaseGateDecision,
    ScanFinding,
    evaluate_release_gate,
    license_scan,
    pii_scan,
    secret_scan,
)


def test_secret_scan_finds_nothing_in_clean_files() -> None:
    assert secret_scan({"a.py": "print('hello world')\n"}) == []


def test_secret_scan_detects_an_aws_access_key() -> None:
    findings = secret_scan({"config.py": 'AWS_KEY = "AKIAFAKEFAKEFAKE0000"\n'})
    assert len(findings) == 1
    assert findings[0].description == "AWS access key ID"
    assert findings[0].severity == "critical"
    assert findings[0].location == "config.py:1"


def test_secret_scan_detects_a_private_key_header() -> None:
    content = "-----BEGIN RSA PRIVATE KEY-----\nMIIB...\n-----END RSA PRIVATE KEY-----\n"
    findings = secret_scan({"key.pem": content})
    assert len(findings) == 1
    assert findings[0].description == "private key material"


def test_secret_scan_detects_a_generic_credential_assignment() -> None:
    findings = secret_scan({"settings.py": 'api_key = "FAKE-CREDENTIAL-NOT-A-REAL-SECRET-0000"\n'})
    assert len(findings) == 1
    assert findings[0].description == "hardcoded credential-like assignment"


def test_secret_scan_reports_the_correct_line_number_past_the_first_line() -> None:
    content = "line one\nline two\nAWS_KEY = \"AKIAFAKEFAKEFAKE0000\"\n"
    findings = secret_scan({"f.py": content})
    assert findings[0].location == "f.py:3"


def test_secret_scan_does_not_false_positive_on_mentioning_a_key_by_name() -> None:
    """The discriminating half: merely mentioning "AWS_KEY" in prose,
    with no actual key-shaped value, must not be flagged."""
    findings = secret_scan({"notes.txt": "AWS_KEY wasn't a real one, just a mention\n"})
    assert findings == []


def test_secret_scan_checks_every_file_in_the_mapping_independently() -> None:
    files = {
        "clean.py": "print(1)\n",
        "dirty.py": 'AWS_KEY = "AKIAFAKEFAKEFAKE0000"\n',
    }
    findings = secret_scan(files)
    assert len(findings) == 1
    assert findings[0].location.startswith("dirty.py:")


def test_this_repositorys_own_real_source_tree_has_no_secret_findings() -> None:
    """A genuine self-check, not a synthetic example: scanning this
    repository's actual src/ tree today finds nothing -- confirming the
    scanner's own false-positive rate is low enough to be usable against
    real code, not merely against curated synthetic fixtures."""
    src_root = pathlib.Path(__file__).resolve().parents[2] / "src"
    files = {str(path): path.read_text() for path in src_root.rglob("*.py")}
    assert len(files) > 100  # sanity: the real tree was actually read, not an empty directory
    assert secret_scan(files) == []


def test_license_scan_finds_nothing_in_clean_files() -> None:
    assert license_scan({"notes.md": "World Bank Open Data is CC-BY-4.0.\n"}) == []


def test_license_scan_detects_a_restricted_vendor_name() -> None:
    findings = license_scan({"notes.md": "Pulled a snapshot from the Bloomberg Terminal feed.\n"})
    assert len(findings) == 1
    assert findings[0].description == "restricted-redistribution data vendor name"
    assert findings[0].severity == "critical"
    assert findings[0].location == "notes.md:1"


def test_license_scan_detects_a_no_redistribution_phrase() -> None:
    findings = license_scan({"data.txt": "Internal use only -- not for redistribution.\n"})
    assert len(findings) == 1
    assert findings[0].description == "explicit no-redistribution marker phrase"


def test_license_scan_reports_the_correct_line_number_past_the_first_line() -> None:
    content = "line one\nline two\nSourced via Refinitiv feed.\n"
    findings = license_scan({"f.md": content})
    assert findings[0].location == "f.md:3"


def test_license_scan_checks_every_file_in_the_mapping_independently() -> None:
    files = {
        "clean.md": "World Bank Open Data, CC-BY-4.0.\n",
        "dirty.md": "Sourced from FactSet.\n",
    }
    findings = license_scan(files)
    assert len(findings) == 1
    assert findings[0].location.startswith("dirty.md:")


def test_this_repositorys_own_real_source_tree_has_no_restricted_license_findings() -> None:
    """A genuine self-check against this repository's actual src/ tree,
    confirming DAT-13's acceptance criterion holds today: every external
    data source this project actually uses (World Bank Open Data,
    Kenneth French Data Library) is free/open, so a sweep finds zero
    restricted-vendor or no-redistribution markers anywhere. Excludes
    `evidence/security_scan.py` itself, whose own pattern definitions
    must literally name the vendors they detect -- the same reason a
    linter excludes its own rule-definition file from its own linting."""
    src_root = pathlib.Path(__file__).resolve().parents[2] / "src"
    files = {
        str(path): path.read_text()
        for path in src_root.rglob("*.py")
        if path.name != "security_scan.py"
    }
    assert len(files) > 100  # sanity: the real tree was actually read, not an empty directory
    assert license_scan(files) == []


def test_a_license_scan_finding_blocks_the_release_gate_the_same_way_a_secret_does() -> None:
    """Confirms the two scanners compose through the SAME gate, closing
    DAT-13's "CI secret/license scan ... pass" loop end to end."""
    finding = license_scan({"notes.md": "Sourced via Bloomberg Terminal.\n"})[0]
    decision = evaluate_release_gate([finding])
    assert decision.blocked is True
    assert decision.unapproved_findings == (finding,)


def test_finding_id_is_deterministic_for_identical_findings() -> None:
    f1 = ScanFinding("secret_scan", "critical", "a.py:1", "AWS access key ID")
    f2 = ScanFinding("secret_scan", "critical", "a.py:1", "AWS access key ID")
    assert f1.finding_id == f2.finding_id


def test_finding_id_differs_for_a_different_location() -> None:
    f1 = ScanFinding("secret_scan", "critical", "a.py:1", "AWS access key ID")
    f2 = ScanFinding("secret_scan", "critical", "a.py:2", "AWS access key ID")
    assert f1.finding_id != f2.finding_id


def test_release_gate_blocks_on_an_unapproved_critical_finding() -> None:
    finding = ScanFinding("secret_scan", "critical", "a.py:1", "AWS access key ID")
    decision = evaluate_release_gate([finding])
    assert decision.blocked is True
    assert decision.unapproved_findings == (finding,)


def test_release_gate_never_blocks_on_low_or_medium_findings() -> None:
    findings = [
        ScanFinding("dep_scan", "low", "pkg-a", "outdated minor version"),
        ScanFinding("dep_scan", "medium", "pkg-b", "deprecated API usage"),
    ]
    decision = evaluate_release_gate(findings)
    assert decision.blocked is False
    assert decision.unapproved_findings == ()


def test_release_gate_unblocks_when_the_exact_finding_is_approved() -> None:
    """The acceptance criterion's own "unless approved" half: approving
    a finding's exact id must lift the block for that finding."""
    finding = ScanFinding("secret_scan", "critical", "a.py:1", "AWS access key ID")
    decision = evaluate_release_gate([finding], approved_finding_ids=[finding.finding_id])
    assert decision.blocked is False
    assert decision.unapproved_findings == ()


def test_release_gate_approval_is_scoped_to_the_exact_finding_not_its_category() -> None:
    """The discriminating half: approving ONE finding must not
    blanket-approve a DIFFERENT finding that happens to share the same
    scanner/severity/description category."""
    approved_finding = ScanFinding("secret_scan", "critical", "a.py:1", "AWS access key ID")
    other_finding = ScanFinding("secret_scan", "critical", "b.py:5", "AWS access key ID")
    decision = evaluate_release_gate(
        [approved_finding, other_finding], approved_finding_ids=[approved_finding.finding_id]
    )
    assert decision.blocked is True
    assert decision.unapproved_findings == (other_finding,)


def test_release_gate_decision_type_is_constructible_directly() -> None:
    decision = ReleaseGateDecision(blocked=False, unapproved_findings=())
    assert decision.blocked is False


def test_pii_scan_finds_nothing_in_clean_files() -> None:
    assert pii_scan({"a.csv": "date,value\n202005,9.88\n"}) == []


def test_pii_scan_detects_an_ssn_shaped_value() -> None:
    findings = pii_scan({"leak.txt": "ssn: 123-45-6789\n"})
    assert len(findings) == 1
    assert findings[0].description == "US Social Security Number-shaped value"
    assert findings[0].severity == "high"


def test_pii_scan_detects_an_email_address() -> None:
    findings = pii_scan({"leak.txt": "contact: someone@example.com\n"})
    assert len(findings) == 1
    assert findings[0].description == "email address"


def test_pii_scan_detects_a_us_phone_number() -> None:
    findings = pii_scan({"leak.txt": "call (555) 123-4567\n"})
    assert len(findings) == 1
    assert findings[0].description == "US phone number-shaped value"


def test_pii_scan_detects_a_credit_card_shaped_digit_run() -> None:
    findings = pii_scan({"leak.txt": "card number 4111111111111111 on file\n"})
    assert len(findings) == 1
    assert findings[0].description == "credit-card-number-shaped digit sequence"


def test_pii_scan_does_not_false_positive_on_a_long_real_decimal_value() -> None:
    """The discriminating case this project's own real macro data
    actually produces: a YoY growth-rate value like 1146.4183381088824
    (real -- see neural_sde.ood) has 13+ consecutive digits on one side
    of its decimal point, which a naive digit-run pattern would
    misflag as a credit-card number. The decimal-point exclusion in
    `_PII_PATTERNS` must not fire here."""
    assert pii_scan({"data.csv": "KAGGLE_CLAIMS_YOY,1146.4183381088824\n"}) == []


def test_pii_scan_reports_the_correct_line_number_past_the_first_line() -> None:
    findings = pii_scan({"a.txt": "line one\nline two\nssn: 123-45-6789\n"})
    assert findings[0].location == "a.txt:3"


def test_a_pii_scan_finding_blocks_the_release_gate_the_same_way_a_secret_does() -> None:
    """`evaluate_release_gate` is scanner-agnostic by design -- confirms
    a `pii_scan` finding plugs into the exact same gate with no change
    needed there."""
    finding = pii_scan({"leak.txt": "ssn: 123-45-6789\n"})[0]
    decision = evaluate_release_gate([finding])
    assert decision.blocked is True
    assert decision.unapproved_findings == (finding,)


def test_this_repositorys_own_real_committed_datasets_have_no_pii_findings() -> None:
    """A genuine self-check against the real, committed research
    datasets this repository actually ships (PRV-03's own acceptance
    wording: "tests confirm default datasets avoid real PII") -- not a
    synthetic example."""
    repo_root = pathlib.Path(__file__).resolve().parents[2]
    paths = list((repo_root / "data_cache").glob("*")) + list(
        (repo_root / "tests" / "fixtures").glob("*")
    )
    files = {str(p): p.read_text() for p in paths if p.is_file()}
    assert len(files) >= 4  # sanity: the real committed datasets were actually read
    assert pii_scan(files) == []
