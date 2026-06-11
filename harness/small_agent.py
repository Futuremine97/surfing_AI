"""Small-agent layer: cheap deterministic handlers for micro tasks.

Small agents cannot write files, run shell commands, or access the
network. They only transform text into structured output.
"""

from __future__ import annotations

import json
import re

from .context_reducer import ERROR_LINE_RE, classify_task_type
from .safety_barrier import scan_command


class SmallAgentViolation(RuntimeError):
    pass


CAPABILITIES = (
    "extract_first_error_line",
    "summarize_log",
    "rank_relevant_files",
    "validate_json",
    "validate_yaml",
    "check_command_risk",
    "summarize_diff",
    "classify_task_type",
    "compress_test_output",
)


def extract_first_error_line(text: str) -> str | None:
    for line in text.splitlines():
        if ERROR_LINE_RE.search(line):
            return line.strip()
    return None


def summarize_log(text: str, max_lines: int = 5) -> dict:
    lines = text.splitlines()
    errors = [ln.strip() for ln in lines if ERROR_LINE_RE.search(ln)]
    return {
        "total_lines": len(lines),
        "error_count": len(errors),
        "first_errors": errors[:max_lines],
        "tail": [ln.strip() for ln in lines[-2:]],
    }


def rank_relevant_files(files: list[str], goal: str) -> list[str]:
    goal_tokens = set(re.findall(r"\w+", goal.lower()))

    def score(path: str) -> int:
        return len(goal_tokens & set(re.findall(r"\w+", path.lower())))

    return sorted(files, key=lambda f: (-score(f), f))


def validate_json(text: str) -> dict:
    try:
        json.loads(text)
        return {"valid": True, "error": None}
    except json.JSONDecodeError as exc:
        return {"valid": False, "error": str(exc)}


def validate_yaml(text: str) -> dict:
    try:
        import yaml  # type: ignore
        try:
            yaml.safe_load(text)
            return {"valid": True, "error": None}
        except yaml.YAMLError as exc:
            return {"valid": False, "error": str(exc)}
    except ImportError:
        # Naive structural check when no parser is installed.
        for i, ln in enumerate(text.splitlines(), 1):
            if ln.strip() and "\t" in ln[: len(ln) - len(ln.lstrip())]:
                return {"valid": False, "error": f"tab indentation at line {i}"}
        return {"valid": True, "error": None, "note": "structural check only"}


def check_command_risk(command: str) -> dict:
    scan = scan_command(command)
    return {"blocked": scan.blocked, "reasons": scan.reasons,
            "warnings": scan.warnings, "risk_score": scan.risk_score}


def summarize_diff(diff_text: str) -> dict:
    files = re.findall(r"^\+\+\+ b/(.+)$", diff_text, re.MULTILINE)
    added = sum(1 for ln in diff_text.splitlines()
                if ln.startswith("+") and not ln.startswith("+++"))
    removed = sum(1 for ln in diff_text.splitlines()
                  if ln.startswith("-") and not ln.startswith("---"))
    return {"files_changed": files, "lines_added": added, "lines_removed": removed}


def compress_test_output(text: str) -> dict:
    lines = text.splitlines()
    failed = [ln.strip() for ln in lines if "FAILED" in ln or "ERROR" in ln]
    summary = next(
        (ln.strip() for ln in reversed(lines)
         if re.search(r"\d+ (passed|failed|error)", ln)), None)
    return {"failed": failed[:20], "summary": summary}


_HANDLERS = {
    "extract_first_error_line": extract_first_error_line,
    "summarize_log": summarize_log,
    "rank_relevant_files": lambda p: rank_relevant_files(p["files"], p["goal"]),
    "validate_json": validate_json,
    "validate_yaml": validate_yaml,
    "check_command_risk": check_command_risk,
    "summarize_diff": summarize_diff,
    "classify_task_type": classify_task_type,
    "compress_test_output": compress_test_output,
}


class SmallAgent:
    """Dispatches micro tasks to deterministic handlers.

    Structurally incapable of file writes, shell execution, or network IO.
    """

    name = "small_agent"

    def run(self, capability: str, payload) -> dict:
        if capability not in CAPABILITIES:
            raise SmallAgentViolation(f"unknown capability: {capability}")
        result = _HANDLERS[capability](payload)
        return {"ok": True, "agent": self.name,
                "capability": capability, "result": result}
