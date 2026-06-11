"""Reduction audit: did context reduction keep enough information?

The audit re-derives a compact state from the relevant raw context and
checks that the routing decision made from the compact state agrees with
the decision made from the re-derived state. Disagreement means the
reduction lost decision-relevant information.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from .context_reducer import reduce_context
from .state import TaskState


@dataclass
class AuditResult:
    passed: bool
    compact_decision: object
    raw_decision: object
    missing_fields: list[str] = field(default_factory=list)
    guidance: list[str] = field(default_factory=list)

    @property
    def status(self) -> str:
        return "PASS" if self.passed else "FAIL"


def _required_fields_missing(state: TaskState) -> list[str]:
    missing = []
    if state.task_type == "bugfix" and not state.current_error:
        missing.append("current_error")
    if state.needs_code_edit and not state.relevant_files:
        missing.append("relevant_files")
    if not state.compact_summary:
        missing.append("compact_summary")
    return missing


def audit_reduction(
    raw_context_ref: str,
    task_state: TaskState,
    decision_fn: Callable[[TaskState], object],
) -> AuditResult:
    """Compare routing decision using compact state against decision using
    relevant raw context. PASS if the compact state preserves enough
    information for the next action."""
    compact_decision = decision_fn(task_state)

    rebuilt = reduce_context(
        raw_context_ref,
        task_state.user_goal,
        task_id=task_state.task_id + "-audit",
        token_budget=task_state.token_budget,
    )
    raw_decision = decision_fn(rebuilt)

    missing = _required_fields_missing(task_state)
    passed = compact_decision == raw_decision and not missing

    guidance = []
    if not passed:
        guidance.append("do not call an expensive model yet")
        guidance.extend(f"gather targeted context for: {m}" for m in missing)
        if compact_decision != raw_decision:
            guidance.append("rerun reduction: compact and raw decisions disagree")

    return AuditResult(
        passed=passed,
        compact_decision=compact_decision,
        raw_decision=raw_decision,
        missing_fields=missing,
        guidance=guidance,
    )
