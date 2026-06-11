from harness.public_release_guard import (
    BLOCKED_BY_EXTERNAL_VALIDATION_FAILURE, BLOCKED_BY_MISSING_USER_APPROVAL,
    BLOCKED_BY_MARKETPLACE_API_UNAVAILABLE, BLOCKED_BY_PRIVATE_LEAK_RISK,
    BLOCKED_BY_TEST_FAILURE, MARKETPLACE_READY_BUT_NOT_SUBMITTED,
    SUBMITTED_CONFIRMED, marketplace_status, run_release_check)


def full_evidence(**kw):
    base = dict(
        tests_passed=True,
        release_guard_pass=True,
        scrape_scan_pass=True,
        validation_report_pass=True,
        user_approval_trace="trace-7731",
        marketplace_api_available=True,
        submission_id="sub-001",
        marketplace_confirmation="confirmation-receipt",
        package_hash="sha256:abc",
    )
    base.update(kw)
    return base


def test_submitted_confirmed_requires_full_evidence():
    assert marketplace_status(full_evidence()) == SUBMITTED_CONFIRMED


def test_no_submission_id_means_not_submitted():
    ev = full_evidence(submission_id=None, marketplace_confirmation=None)
    assert marketplace_status(ev) == MARKETPLACE_READY_BUT_NOT_SUBMITTED


def test_failing_tests_block():
    assert marketplace_status(full_evidence(tests_passed=False)) == \
        BLOCKED_BY_TEST_FAILURE


def test_leak_risk_blocks():
    assert marketplace_status(full_evidence(release_guard_pass=False)) == \
        BLOCKED_BY_PRIVATE_LEAK_RISK


def test_missing_approval_blocks():
    assert marketplace_status(full_evidence(user_approval_trace=None)) == \
        BLOCKED_BY_MISSING_USER_APPROVAL


def test_missing_external_validation_blocks():
    assert marketplace_status(full_evidence(validation_report_pass=False)) == \
        BLOCKED_BY_EXTERNAL_VALIDATION_FAILURE


def test_api_unavailable_blocks():
    ev = full_evidence(marketplace_api_available=False)
    assert marketplace_status(ev) == BLOCKED_BY_MARKETPLACE_API_UNAVAILABLE


def test_release_check_requires_user_approval(tmp_path):
    (tmp_path / "README.md").write_text("clean synthetic project")
    report = run_release_check(tmp_path, user_approved=False)
    assert report.status == BLOCKED_BY_MISSING_USER_APPROVAL
    assert run_release_check(tmp_path, user_approved=True).passed


def test_release_check_blocks_secrets(tmp_path):
    # assembled so this test source itself stays scan-clean
    secret_line = "token = " + '"' + "0123456789abcdef" + '"'
    (tmp_path / "config.py").write_text(secret_line)
    report = run_release_check(tmp_path, user_approved=True)
    assert report.status == "BLOCKED_BY_SECRET_SCAN"
