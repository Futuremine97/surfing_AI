"""Coupled approval guard for high-risk actions.

A high-risk action proceeds only when four signals agree:
human intent matches the AI proposal, the verifier approves, a rollback
checkpoint exists, and the worst-case simulator finds nothing catastrophic.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .worst_case_simulator import simulate

HIGH_RISK_ACTIONS = {
    "delete",
    "destructive_shell",
    "visibility_change",
    "publish",
    "marketplace_submit",
    "secret_access",
}

STATUS_APPROVED = "APPROVED"
BLOCKED_BY_MISSING_USER_APPROVAL = "BLOCKED_BY_MISSING_USER_APPROVAL"
BLOCKED_BY_INTENT_MISMATCH = "BLOCKED_BY_INTENT_MISMATCH"
BLOCKED_BY_VERIFIER = "BLOCKED_BY_VERIFIER"
BLOCKED_BY_MISSING_ROLLBACK = "BLOCKED_BY_MISSING_ROLLBACK"
BLOCKED_BY_WORST_CASE = "BLOCKED_BY_WORST_CASE"


@dataclass
class CoupledApprovalState:
    """The coupled approval state: human intent, AI proposal, verifier
    judgment, and rollback/checkpoint reference."""

    human_intent: str | None = None
    ai_proposal: str = ""
    verifier_approved: bool = False
    rollback_ref: str | None = None


@dataclass
class GuardDecision:
    approved: bool
    status: str
    reasons: list[str] = field(default_factory=list)
    worst_case: object = None


def _tokens(text: str) -> set[str]:
    return set(re.findall(r"\w+", text.lower()))


def intent_matches(human_intent: str | None, ai_proposal: str,
                   action_type: str) -> bool:
    if not human_intent:
        return False
    h = _tokens(human_intent)
    if "deny" in h or "reject" in h or "stop" in h:
        return False
    action_words = _tokens(action_type.replace("_", " "))
    proposal_overlap = len(h & _tokens(ai_proposal)) >= 1
    action_overlap = len(h & action_words) >= 1
    explicit = "approve" in h or "yes" in h or "proceed" in h
    return (explicit and (proposal_overlap or action_overlap)) or (
        proposal_overlap and action_overlap
    )


def evaluate(action_type: str, payload: dict,
             state: CoupledApprovalState) -> GuardDecision:
    """Evaluate a proposed action against the coupled approval state."""
    if action_type not in HIGH_RISK_ACTIONS:
        return GuardDecision(approved=True, status=STATUS_APPROVED,
                             reasons=["not a high-risk action"])

    reasons: list[str] = []
    status = STATUS_APPROVED

    if state.human_intent is None:
        status = BLOCKED_BY_MISSING_USER_APPROVAL
        reasons.append("no recorded human intent for this action")
    elif not intent_matches(state.human_intent, state.ai_proposal, action_type):
        status = BLOCKED_BY_INTENT_MISMATCH
        reasons.append("human intent does not match the AI proposal")
    elif not state.verifier_approved:
        status = BLOCKED_BY_VERIFIER
        reasons.append("verifier has not approved this action")
    elif not state.rollback_ref:
        status = BLOCKED_BY_MISSING_ROLLBACK
        reasons.append("no rollback/checkpoint reference exists")

    payload = dict(payload)
    payload.setdefault("rollback_ref", state.rollback_ref)
    report = simulate(action_type, payload)
    if status == STATUS_APPROVED and report.catastrophic:
        status = BLOCKED_BY_WORST_CASE
        reasons.extend(report.scenarios)

    return GuardDecision(approved=status == STATUS_APPROVED,
                         status=status, reasons=reasons, worst_case=report)
