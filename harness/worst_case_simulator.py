"""Worst-case simulator: before a high-risk action runs, enumerate the
worst plausible outcomes and flag catastrophic, non-recoverable ones."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .safety_barrier import scan_command

SECRET_RE = re.compile(
    r"(AKIA[0-9A-Z]{16}|sk-[A-Za-z0-9]{20,}|BEGIN [A-Z ]*PRIVATE KEY|"
    r"(?:api[_-]?key|token|password)\s*[=:]\s*\S{8,})",
    re.IGNORECASE,
)


@dataclass
class WorstCaseReport:
    action_type: str
    catastrophic: bool
    scenarios: list[str] = field(default_factory=list)


def simulate(action_type: str, payload: dict) -> WorstCaseReport:
    scenarios: list[str] = []
    catastrophic = False

    rollback = payload.get("rollback_ref")

    if action_type in ("delete", "destructive_shell") and not rollback:
        scenarios.append("data loss with no checkpoint to restore from")
        catastrophic = True

    if action_type == "destructive_shell":
        cmd = payload.get("command", "")
        scan = scan_command(cmd)
        if scan.blocked:
            scenarios.append(f"command matches blocked pattern: {scan.reasons}")
            catastrophic = True

    if action_type in ("visibility_change", "publish", "marketplace_submit"):
        if payload.get("leak_risk", "none") == "high":
            scenarios.append("publication of restricted internal material; "
                             "public content cannot be reliably retracted")
            catastrophic = True
        if not payload.get("release_guard_passed", False):
            scenarios.append("publishing without a release-guard pass")
            catastrophic = True

    text = str(payload.get("content", "")) + str(payload.get("command", ""))
    if SECRET_RE.search(text):
        scenarios.append("secret material would leave the local machine")
        catastrophic = True

    if not scenarios:
        scenarios.append("worst case appears recoverable via rollback")

    return WorstCaseReport(action_type=action_type,
                           catastrophic=catastrophic, scenarios=scenarios)
