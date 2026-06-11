"""Safety barrier: destructive shell patterns are never executable.

Every shell command must pass a risk scan, run inside a constrained
working directory, carry a timeout, and leave a trace record.
"""

from __future__ import annotations

import re
import shlex
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from .trace import TraceStore


class BarrierViolation(RuntimeError):
    pass


BLOCKED_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("rm -rf on root or home", re.compile(r"rm\s+(-\w*\s+)*-\w*[rf]\w*\s+(/|~)(\s|$)")),
    ("rm -rf /", re.compile(r"rm\s+-rf\s+/")),
    ("git reset --hard", re.compile(r"git\s+reset\s+--hard")),
    ("git clean -fdx", re.compile(r"git\s+clean\s+-fdx")),
    ("sudo", re.compile(r"(^|\s)sudo(\s|$)")),
    ("recursive chmod", re.compile(r"chmod\s+(-\w*\s+)*-R\b")),
    ("curl piped to shell", re.compile(r"curl[^|;&]*\|\s*(sh|bash|zsh)\b")),
    ("wget piped to shell", re.compile(r"wget[^|;&]*\|\s*(sh|bash|zsh)\b")),
    ("raw disk write", re.compile(r"\bdd\s+if=")),
]

WARN_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("file deletion", re.compile(r"\brm\b")),
    ("git push --force", re.compile(r"git\s+push\s+.*--force")),
    ("pipe to interpreter", re.compile(r"\|\s*(python3?|node)\b")),
]


@dataclass
class CommandScan:
    command: str
    blocked: bool
    reasons: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def risk_score(self) -> float:
        if self.blocked:
            return 1.0
        return min(0.9, 0.3 * len(self.warnings))


def scan_command(command: str) -> CommandScan:
    reasons = [name for name, pat in BLOCKED_PATTERNS if pat.search(command)]
    warnings = [name for name, pat in WARN_PATTERNS if pat.search(command)]
    return CommandScan(command=command, blocked=bool(reasons),
                       reasons=reasons, warnings=warnings)


def run_safe(
    command: str,
    cwd: str | Path,
    allowed_root: str | Path | None = None,
    timeout: int = 60,
    trace: TraceStore | None = None,
    task_id: str = "adhoc",
) -> subprocess.CompletedProcess:
    """Run a shell command with risk scan, cwd constraint, timeout, trace."""
    scan = scan_command(command)
    if trace:
        trace.record(task_id, "command_risk_scan",
                     command=command, blocked=scan.blocked,
                     reasons=scan.reasons, warnings=scan.warnings)
    if scan.blocked:
        raise BarrierViolation(f"blocked command ({', '.join(scan.reasons)}): {command}")

    cwd = Path(cwd).resolve()
    root = Path(allowed_root).resolve() if allowed_root else cwd
    if not cwd.is_relative_to(root):
        raise BarrierViolation(f"cwd {cwd} escapes allowed root {root}")
    if not cwd.is_dir():
        raise BarrierViolation(f"cwd does not exist: {cwd}")

    argv = shlex.split(command)
    proc = subprocess.run(
        argv, cwd=str(cwd), timeout=timeout,
        capture_output=True, text=True,
    )
    if trace:
        trace.record(task_id, "shell_tool", command=command,
                     returncode=proc.returncode)
    return proc
