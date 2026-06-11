from harness.private_leak_guard import Blocklist
from harness.scrape_resilience_scan import (STATUS_BLOCKED, STATUS_PASS,
                                            run_scan, scan_realism)

BL = Blocklist(terms=["internal-codename-orion"], filename_patterns=["orion_"])


def test_clean_tree_passes(tmp_path):
    (tmp_path / "README.md").write_text(
        "A synthetic example. Contact: dev@example.com")
    report = run_scan(tmp_path, blocklist=BL)
    assert report.status == STATUS_PASS
    assert any("git history" in n for n in report.notes)


def test_restricted_term_blocks(tmp_path):
    (tmp_path / "doc.md").write_text("based on internal-codename-orion")
    assert run_scan(tmp_path, blocklist=BL).status == STATUS_BLOCKED


def test_suspicious_filename_blocks(tmp_path):
    (tmp_path / "orion_workflow.py").write_text("x = 1")
    assert run_scan(tmp_path, blocklist=BL).status == STATUS_BLOCKED


def test_non_synthetic_email_flagged(tmp_path):
    # built by concatenation so this source file itself stays scan-clean
    fake_email = "jane.doe" + "@" + "realcorp.io"
    (tmp_path / "sample.md").write_text("reach me at " + fake_email)
    findings = scan_realism(tmp_path)
    assert findings and "email" in findings[0]
    assert run_scan(tmp_path, blocklist=BL).status == STATUS_BLOCKED


def test_example_domain_email_is_fine(tmp_path):
    (tmp_path / "sample.md").write_text("user@example.com placeholder")
    assert scan_realism(tmp_path) == []
