"""Verifier gate: checks an executor's outcome against the compact task
state before the result is accepted."""

from __future__ import annotations

from dataclasses import dataclass, field

from .state import TaskState


@dataclass
class VerifierJudgment:
    approved: bool
    reasons: list[str] = field(default_factory=list)
    needs_human: bool = False


class VerifierGate:
    """Deterministic verification of task outcomes.

    `outcome` keys:
      tests_passed: bool | None — result of the test runner, if any
      criteria_met: list[str]   — success criteria the executor claims met
      evidence: list[str]       — supporting evidence strings
      side_effects: list[str]   — declared side effects
    """

    def verify(self, state: TaskState, outcome: dict) -> VerifierJudgment:
        reasons: list[str] = []
        approved = True

        tests = outcome.get("tests_passed")
        if state.needs_code_edit and tests is not True:
            approved = False
            reasons.append("code edit without passing tests")

        claimed = set(outcome.get("criteria_met", []))
        missing = [c for c in state.success_criteria if c not in claimed]
        if missing:
            approved = False
            reasons.append(f"unmet success criteria: {missing}")

        if outcome.get("side_effects") and state.risk_level == "low":
            approved = False
            reasons.append("undeclared risk: side effects on a low-risk task")

        needs_human = state.risk_level == "high" or state.needs_human_approval
        if needs_human:
            reasons.append("high-risk task: human approval still required "
                           "after verification")

        if approved and not reasons:
            reasons.append("all checks passed")

        return VerifierJudgment(approved=approved, reasons=reasons,
                                needs_human=needs_human)
