"""Public release guard: the final gate before anything leaves the machine.

Order of checks: secret scan -> leak guard -> scrape-resilience scan
(including git history) -> explicit user approval.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from . import private_leak_guard as plg
from . import scrape_resilience_scan as srs

PUBLIC_RELEASE_PASS = "PUBLIC_RELEASE_PASS"
BLOCKED_BY_PRIVATE_LEAK_RISK = "BLOCKED_BY_PRIVATE_LEAK_RISK"
BLOCKED_BY_SCRAPE_RESILIENCE_FAILURE = "BLOCKED_BY_SCRAPE_RESILIENCE_FAILURE"
BLOCKED_BY_SECRET_SCAN = "BLOCKED_BY_SECRET_SCAN"
BLOCKED_BY_GIT_HISTORY_RISK = "BLOCKED_BY_GIT_HISTORY_RISK"
BLOCKED_BY_MISSING_USER_APPROVAL = "BLOCKED_BY_MISSING_USER_APPROVAL"

# Marketplace statuses
SUBMITTED_CONFIRMED = "SUBMITTED_CONFIRMED"
MARKETPLACE_READY_BUT_NOT_SUBMITTED = "MARKETPLACE_READY_BUT_NOT_SUBMITTED"
BLOCKED_BY_MARKETPLACE_API_UNAVAILABLE = "BLOCKED_BY_MARKETPLACE_API_UNAVAILABLE"
BLOCKED_BY_SECURITY_REVIEW = "BLOCKED_BY_SECURITY_REVIEW"
BLOCKED_BY_TEST_FAILURE = "BLOCKED_BY_TEST_FAILURE"
BLOCKED_BY_EXTERNAL_VALIDATION_FAILURE = "BLOCKED_BY_EXTERNAL_VALIDATION_FAILURE"
BLOCKED_BY_MISSING_REVIEWER = "BLOCKED_BY_MISSING_REVIEWER"

SECRET_PATTERNS = [
    ("AWS access key", re.compile(r"AKIA[0-9A-Z]{16}")),
    ("API key literal", re.compile(r"\b(?:api[_-]?key|secret|token|password)\s*[=:]\s*['\"][^'\"]{8,}['\"]", re.IGNORECASE)),
    ("private key block", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    ("model provider key", re.compile(r"\bsk-[A-Za-z0-9_-]{20,}")),
]


@dataclass
class ReleaseReport:
    status: str
    secret_findings: list[str] = field(default_factory=list)
    leak_report: object = None
    scrape_report: object = None
    notes: list[str] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return self.status == PUBLIC_RELEASE_PASS


def scan_secrets(root: str | Path) -> list[str]:
    root = Path(root)
    findings = []
    rules = plg.load_ignore_rules(root)
    for path in sorted(root.rglob("*")):
        rel = path.relative_to(root)
        if any(p in plg.SCAN_EXCLUDE_DIRS for p in rel.parts):
            continue
        if rel.name in plg.SCAN_EXCLUDE_FILES:
            continue
        if plg.is_ignored(rel, rules):
            continue
        if not (path.is_file() and path.suffix in plg.TEXT_SUFFIXES):
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        for name, pat in SECRET_PATTERNS:
            if pat.search(text):
                findings.append(f"{rel}: {name}")
    return findings


def run_release_check(root: str | Path = ".",
                      user_approved: bool = False,
                      blocklist: plg.Blocklist | None = None) -> ReleaseReport:
    root = Path(root)
    blocklist = blocklist or plg.load_blocklist(root)
    notes = []
    if (root / "private").exists():
        notes.append("private/ directory present locally; it is excluded "
                     "from scans and must stay gitignored")

    secrets = scan_secrets(root)
    if secrets:
        return ReleaseReport(status=BLOCKED_BY_SECRET_SCAN,
                             secret_findings=secrets, notes=notes)

    leak = plg.check(root, blocklist=blocklist)
    if leak.status != plg.STATUS_PASS:
        return ReleaseReport(status=BLOCKED_BY_PRIVATE_LEAK_RISK,
                             leak_report=leak, notes=notes)

    scrape = srs.run_scan(root, blocklist=blocklist)
    if scrape.status == srs.STATUS_GIT_BLOCKED:
        return ReleaseReport(status=BLOCKED_BY_GIT_HISTORY_RISK,
                             scrape_report=scrape, notes=notes)
    if scrape.status != srs.STATUS_PASS:
        return ReleaseReport(status=BLOCKED_BY_SCRAPE_RESILIENCE_FAILURE,
                             scrape_report=scrape, notes=notes)

    if not user_approved:
        return ReleaseReport(status=BLOCKED_BY_MISSING_USER_APPROVAL,
                             leak_report=leak, scrape_report=scrape, notes=notes)

    return ReleaseReport(status=PUBLIC_RELEASE_PASS, leak_report=leak,
                         scrape_report=scrape, notes=notes)


REQUIRED_SUBMISSION_EVIDENCE = (
    "submission_id",
    "marketplace_confirmation",
    "package_hash",
    "validation_report_pass",
    "release_guard_pass",
    "scrape_scan_pass",
    "user_approval_trace",
)


def marketplace_status(evidence: dict) -> str:
    """Never claim submission without actual evidence."""
    if not evidence.get("tests_passed", False):
        return BLOCKED_BY_TEST_FAILURE
    if not evidence.get("release_guard_pass", False):
        return BLOCKED_BY_PRIVATE_LEAK_RISK
    if not evidence.get("user_approval_trace"):
        return BLOCKED_BY_MISSING_USER_APPROVAL
    if not evidence.get("validation_report_pass", False):
        return BLOCKED_BY_EXTERNAL_VALIDATION_FAILURE
    if evidence.get("marketplace_api_available") is False:
        return BLOCKED_BY_MARKETPLACE_API_UNAVAILABLE
    if all(evidence.get(k) for k in REQUIRED_SUBMISSION_EVIDENCE):
        return SUBMITTED_CONFIRMED
    return MARKETPLACE_READY_BUT_NOT_SUBMITTED
