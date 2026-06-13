"""Rule-based router: picks the cheapest pipeline that still preserves
correctness and safety for the given compact task state.

Security gauge integration
--------------------------
``choose_route`` accepts an optional ``gauge`` argument (a
``SecurityGauge`` instance). When supplied, the resulting route is
filtered through ``gauge.filter_routes()`` so that only routes
permitted at the current security level are returned.  If the resulting
route is empty after filtering, a safe fallback ``["command_risk_scan"]``
is used (level 0 minimum).
"""

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


def choose_route(task: TaskState, gauge=None) -> list[str]:
    """Return the ordered pipeline for *task*.

    Parameters
    ----------
    task:
        Compact task state produced by ``context_reducer``.
    gauge:
        Optional :class:`~harness.security_gauge.SecurityGauge`.  When
        provided the raw route is filtered to only include steps that
        the current security level permits.
    """
    if task.public_release_requested:
        raw = ["public_release_guard", "scrape_resilience_scan", "human_approval"]
    elif task.risk_level == "high" or task.needs_human_approval:
        raw = ["context_reducer", "planner", "verifier", "human_approval"]
    elif task.needs_code_edit:
        raw = ["context_reducer", "coding_agent", "test_runner", "verifier"]
    elif task.needs_shell:
        raw = ["context_reducer", "command_risk_scan", "shell_tool", "verifier"]
    elif is_micro_task(task):
        raw = ["small_agent"]
    else:
        raw = ["context_reducer", "planner", "verifier"]

    if gauge is None:
        return raw

    filtered = gauge.filter_routes(raw)
    return filtered if filtered else ["command_risk_scan"]


def model_for_gauge(gauge=None) -> str | None:
    """Return the most capable model permitted by the current gauge level.

    Returns ``None`` when no external model is allowed (level 0/1 without
    any ``allowed_models`` entries).  Callers may then fall back to local
    processing only.
    """
    if gauge is None:
        return None
    listing = gauge.listing()
    models = listing.get("allowed_models", [])
    if not models:
        return None
    # prefer the last entry (most capable in each level's list)
    return models[-1]
