"""Private leak guard: scans text, files, and filenames for restricted
internal terms before anything is published.

The real blocklist lives in `.private_release_blocklist.yaml` (gitignored).
A synthetic example lives in `config/example_release_blocklist.yaml`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

REAL_BLOCKLIST = ".private_release_blocklist.yaml"
EXAMPLE_BLOCKLIST = "config/example_release_blocklist.yaml"

SCAN_EXCLUDE_DIRS = {".git", "__pycache__", ".pytest_cache", "private",
                     ".venv", "venv", "node_modules"}
SCAN_EXCLUDE_FILES = {REAL_BLOCKLIST}

TEXT_SUFFIXES = {".py", ".md", ".txt", ".yaml", ".yml", ".json", ".toml",
                 ".cfg", ".ini", ".sh", ".js", ".ts"}

STATUS_PASS = "PASS"
STATUS_BLOCKED = "BLOCKED_BY_PRIVATE_LEAK_RISK"


@dataclass
class Blocklist:
    terms: list[str] = field(default_factory=list)
    filename_patterns: list[str] = field(default_factory=list)
    source: str = "builtin-empty"


@dataclass
class Finding:
    location: str
    term: str
    line: int | None = None
    kind: str = "content"  # content | filename


@dataclass
class LeakReport:
    status: str
    findings: list[Finding] = field(default_factory=list)
    blocklist_source: str = ""


def _parse_simple_yaml_lists(text: str) -> dict[str, list[str]]:
    """Minimal parser for `key:` followed by `- item` lines (no deps)."""
    data: dict[str, list[str]] = {}
    current: str | None = None
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].rstrip()
        if not line.strip():
            continue
        if not line.startswith((" ", "\t", "-")) and line.endswith(":"):
            current = line[:-1].strip()
            data[current] = []
        elif line.lstrip().startswith("- ") and current:
            data[current].append(line.lstrip()[2:].strip().strip("'\""))
    return data


def load_blocklist(root: str | Path = ".") -> Blocklist:
    """Load the real blocklist if present, else the example, else empty."""
    root = Path(root)
    for candidate, label in ((root / REAL_BLOCKLIST, "real"),
                             (root / EXAMPLE_BLOCKLIST, "example")):
        if candidate.is_file():
            data = _parse_simple_yaml_lists(candidate.read_text(encoding="utf-8"))
            return Blocklist(terms=data.get("terms", []),
                             filename_patterns=data.get("filename_patterns", []),
                             source=f"{label}:{candidate}")
    return Blocklist()


def scan_text(text: str, terms: list[str]) -> list[tuple[str, int]]:
    """Case-insensitive scan; returns (term, line_number) pairs."""
    found = []
    lowered = [(i, ln.lower()) for i, ln in enumerate(text.splitlines(), 1)]
    for term in terms:
        t = term.lower()
        for i, ln in lowered:
            if t in ln:
                found.append((term, i))
                break
    return found


def scan_tree(root: str | Path, blocklist: Blocklist) -> list[Finding]:
    root = Path(root)
    findings: list[Finding] = []
    for path in sorted(root.rglob("*")):
        rel = path.relative_to(root)
        if any(part in SCAN_EXCLUDE_DIRS for part in rel.parts):
            continue
        if rel.name in SCAN_EXCLUDE_FILES:
            continue
        name_l = rel.name.lower()
        for pat in blocklist.filename_patterns:
            if pat.lower() in name_l:
                findings.append(Finding(location=str(rel), term=pat,
                                        kind="filename"))
        if path.is_file() and path.suffix in TEXT_SUFFIXES:
            try:
                text = path.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            for term, line in scan_text(text, blocklist.terms):
                findings.append(Finding(location=str(rel), term=term, line=line))
    return findings


def check(root: str | Path = ".", blocklist: Blocklist | None = None) -> LeakReport:
    blocklist = blocklist or load_blocklist(root)
    findings = scan_tree(root, blocklist)
    return LeakReport(
        status=STATUS_BLOCKED if findings else STATUS_PASS,
        findings=findings,
        blocklist_source=blocklist.source,
    )
