"""Context reduction: raw context -> compact task state.

Deterministic, rule-based first pass. The goal is to preserve exactly the
information needed for the next routing decision, so expensive models never
see raw logs when the compact state is enough.
"""

from __future__ import annotations

import re

from .budget import estimate_tokens
from .state import TaskState

ERROR_LINE_RE = re.compile(
    r"(Traceback|[A-Za-z]+Error\b|ERROR|error:|FAILED|FAIL\b|exception|panic:)",
    re.IGNORECASE,
)
FILE_RE = re.compile(
    r"[\w./-]+\.(?:py|js|ts|tsx|json|ya?ml|md|toml|txt|sh|cfg|ini)\b"
)
COMMAND_RE = re.compile(
    r"^\s*(?:\$\s+)?((?:pytest|python3?|pip3?|git|npm|npx|node|make|bash|sh)\b[^\n]*)",
    re.MULTILINE,
)

RELEASE_WORDS = ("publish", "release to", "marketplace", "make public", "공개")
HIGH_RISK_WORDS = (
    "delete", "remove all", "force", "prod", "production",
    "secret", "credential", "drop table", "wipe",
)
EDIT_WORDS = ("fix", "implement", "refactor", "edit", "add feature", "patch", "수정", "구현")
SHELL_WORDS = ("run", "install", "execute", "build", "실행", "설치")
MICRO_WORDS = ("extract", "summarize", "classify", "validate", "rank", "compress")


def classify_task_type(user_goal: str, has_error: bool = False) -> str:
    goal = user_goal.lower()
    if any(w in goal for w in RELEASE_WORDS):
        return "release"
    if has_error or "bug" in goal or "fail" in goal:
        return "bugfix"
    if any(w in goal for w in EDIT_WORDS):
        return "code_edit"
    if any(w in goal for w in MICRO_WORDS):
        return "micro"
    if any(w in goal for w in SHELL_WORDS):
        return "shell"
    if goal.rstrip().endswith("?") or goal.startswith(("what", "why", "how")):
        return "question"
    return "general"


def assess_risk(user_goal: str, raw_context: str, needs_shell: bool) -> str:
    text = (user_goal + "\n" + raw_context).lower()
    if any(w in text for w in HIGH_RISK_WORDS):
        return "high"
    if needs_shell:
        return "medium"
    return "low"


def reduce_context(
    raw_context: str,
    user_goal: str,
    task_id: str | None = None,
    token_budget: int = 8000,
) -> TaskState:
    """Reduce raw context into a compact task state for routing."""
    error_lines = [
        ln.strip() for ln in raw_context.splitlines() if ERROR_LINE_RE.search(ln)
    ]
    current_error = error_lines[0] if error_lines else None

    files = list(dict.fromkeys(FILE_RE.findall(raw_context)))[:10]
    commands = list(dict.fromkeys(COMMAND_RE.findall(raw_context)))[:10]

    task_type = classify_task_type(user_goal, has_error=current_error is not None)
    needs_code_edit = task_type in ("bugfix", "code_edit")
    needs_shell = task_type == "shell" or bool(
        any(w in user_goal.lower() for w in SHELL_WORDS)
    )
    risk_level = assess_risk(user_goal, raw_context, needs_shell)
    release = any(w in user_goal.lower() for w in RELEASE_WORDS)

    unknowns: list[str] = []
    if task_type == "bugfix" and current_error is None:
        unknowns.append("error message not found in context")
    if needs_code_edit and not files:
        unknowns.append("no relevant files identified")

    summary = user_goal.strip()
    if current_error:
        summary += f" | first error: {current_error[:160]}"

    state = TaskState(
        task_id=task_id or "t-" + str(abs(hash((user_goal, raw_context))) % 10**8),
        user_goal=user_goal,
        task_type=task_type,
        compact_summary=summary[:400],
        current_error=current_error,
        relevant_files=files,
        relevant_commands=commands,
        known_facts=[f"raw context ~{estimate_tokens(raw_context)} tokens"],
        unknowns=unknowns,
        risk_level=risk_level,
        needs_code_edit=needs_code_edit,
        needs_shell=needs_shell,
        needs_human_approval=risk_level == "high" or release,
        token_budget=token_budget,
        public_release_requested=release,
        private_research_leak_risk="low" if release else "none",
    )
    return state
