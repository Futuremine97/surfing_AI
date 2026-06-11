"""Expert fusion: combine recommendations from multiple agents.

Verifier weight grows with risk. High-risk tasks require verifier or
human sign-off regardless of agent confidence.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field

BASE_WEIGHTS = {
    "small_agent": 0.5,
    "planner": 1.0,
    "coding_agent": 1.0,
    "verifier": 1.5,
    "human": 3.0,
}

RISK_VERIFIER_BONUS = {"low": 0.0, "medium": 1.0, "high": 2.5}


@dataclass
class ExpertOpinion:
    source: str
    recommendation: str
    confidence: float = 1.0  # 0..1
    approves: bool = True


@dataclass
class FusionResult:
    decision: str | None
    scores: dict = field(default_factory=dict)
    approved: bool = False
    requires_approval: bool = False
    rationale: str = ""


def fuse(opinions: list[ExpertOpinion], risk_level: str = "low") -> FusionResult:
    if not opinions:
        return FusionResult(decision=None, rationale="no opinions provided")

    scores: dict[str, float] = defaultdict(float)
    for op in opinions:
        weight = BASE_WEIGHTS.get(op.source, 1.0)
        if op.source == "verifier":
            weight += RISK_VERIFIER_BONUS.get(risk_level, 0.0)
        scores[op.recommendation] += weight * max(0.0, min(1.0, op.confidence))

    decision = max(scores, key=scores.get)

    gate_sources = {"verifier", "human"}
    gate_ok = any(
        op.source in gate_sources and op.approves and op.recommendation == decision
        for op in opinions
    )

    if risk_level == "high":
        approved = gate_ok
        requires_approval = not gate_ok
        rationale = (
            "high risk: verifier/human sign-off present"
            if gate_ok else
            "high risk: blocked until verifier or human approves"
        )
    else:
        approved = True
        requires_approval = False
        rationale = f"weighted fusion selected '{decision}'"

    return FusionResult(
        decision=decision, scores=dict(scores), approved=approved,
        requires_approval=requires_approval, rationale=rationale,
    )
