"""Scrape-resilience scan.

Assume any public repository is immediately copied and analyzed.
This scan checks that nothing in the tree — contents, filenames,
example data, or git history — reveals restricted internal material.
"""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from .private_leak_guard import (Blocklist, Finding, is_ignored,
                                 load_blocklist, load_ignore_rules,
                                 scan_tree, scan_text,
                                 SCAN_EXCLUDE_DIRS, TEXT_SUFFIXES)

STATUS_PASS = "PASS"
STATUS_BLOCKED = "BLOCKED_BY_SCRAPE_RESILIENCE_FAILURE"
STATUS_GIT_BLOCKED = "BLOCKED_BY_GIT_HISTORY_RISK"

# Heuristics for data that looks real rather than synthetic.
REAL_EMAIL_RE = re.compile(
    r"\b[\w.+-]+@(?!example\.(?:com|org|net))[\w-]+\.[a-z]{2,}\b", re.IGNORECASE)
BEARER_RE = re.compile(r"Authorization:\s*Bearer\s+\S+", re.IGNORECASE)
IP_RE = re.compile(r"\b(?!(?:127|0|10|192)\.)\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b")


@dataclass
class ScrapeScanReport:
    status: str
    content_findings: list[Finding] = field(default_factory=list)
    realism_findings: list[str] = field(default_factory=list)
    git_findings: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


def scan_realism(root: Path) -> list[str]:
    """Flag example data that does not look synthetic."""
    findings = []
    rules = load_ignore_rules(root)
    for path in sorted(root.rglob("*")):
        rel = path.relative_to(root)
        if any(p in SCAN_EXCLUDE_DIRS for p in rel.parts):
            continue
        if is_ignored(rel, rules):
            continue
        if not (path.is_file() and path.suffix in TEXT_SUFFIXES):
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        for name, pat in (("non-synthetic email", REAL_EMAIL_RE),
                          ("bearer token", BEARER_RE),
                          ("public IP address", IP_RE)):
            m = pat.search(text)
            if m:
                findings.append(f"{rel}: {name}: {m.group(0)[:60]}")
    return findings


def scan_git_history(root: Path, blocklist: Blocklist) -> tuple[list[str], list[str]]:
    """Scan commit messages and historical file lists for restricted terms."""
    notes: list[str] = []
    if not (root / ".git").is_dir():
        return [], ["no git history present; history scan skipped"]
    findings: list[str] = []
    try:
        log = subprocess.run(
            ["git", "log", "--all", "--pretty=%H %s %b", "--name-only"],
            cwd=str(root), capture_output=True, text=True, timeout=60,
        ).stdout
    except (OSError, subprocess.TimeoutExpired) as exc:
        return [], [f"git history scan unavailable: {exc}"]
    hits = scan_text(log, blocklist.terms + blocklist.filename_patterns)
    findings.extend(f"git history line {line}: '{term}'" for term, line in hits)
    return findings, notes


def run_scan(root: str | Path = ".",
             blocklist: Blocklist | None = None) -> ScrapeScanReport:
    root = Path(root)
    blocklist = blocklist or load_blocklist(root)

    content = scan_tree(root, blocklist)
    realism = scan_realism(root)
    git_findings, notes = scan_git_history(root, blocklist)

    if git_findings:
        status = STATUS_GIT_BLOCKED
    elif content or realism:
        status = STATUS_BLOCKED
    else:
        status = STATUS_PASS

    return ScrapeScanReport(status=status, content_findings=content,
                            realism_findings=realism,
                            git_findings=git_findings, notes=notes)
