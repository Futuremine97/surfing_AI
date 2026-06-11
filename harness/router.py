"""Rule-based router: picks the cheapest pipeline that still preserves
correctness and safety for the given compact task state."""

from __future__ import annotations

from .micro_task_gate import is_micro_task
from .state import TaskState

ROUTES = {
    "small_agent",
    "context_reducer",
    "planner",
    "coding_agent",
    "test_runner",
    "verifier",
    "human_approval",
    "command_risk_scan",
    "shell_tool",
    "public_release_guard",
    "scrape_resilience_scan",
}


def choose_route(task: TaskState) -> list[str]:
    if task.public_release_requested:
        return ["public_release_guard", "scrape_resilience_scan", "human_approval"]

    if task.risk_level == "high" or task.needs_human_approval:
        return ["context_reducer", "planner", "verifier", "human_approval"]

    if task.needs_code_edit:
        return ["context_reducer", "coding_agent", "test_runner", "verifier"]

    if task.needs_shell:
        return ["context_reducer", "command_risk_scan", "shell_tool", "verifier"]

    if is_micro_task(task):
        return ["small_agent"]

    return ["context_reducer", "planner", "verifier"]
