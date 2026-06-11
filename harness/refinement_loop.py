"""Refinement loop: alternate between proposing a plan/route and
collecting evidence, updating the compact state each round."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from .context_reducer import reduce_context
from .hidden_state_refiner import should_invoke, analyze
from .router import choose_route
from .state import TaskState

EvidenceCollector = Callable[[TaskState], list[str]]


@dataclass
class LoopResult:
    state: TaskState
    route: list[str]
    iterations: int
    converged: bool
    escalated: bool
    history: list[dict] = field(default_factory=list)
    hypotheses: list = field(default_factory=list)


class RefinementLoop:
    def __init__(self, evidence_collector: EvidenceCollector,
                 max_iterations: int = 3):
        self.collect = evidence_collector
        self.max_iterations = max_iterations

    def run(self, raw_context: str, user_goal: str) -> LoopResult:
        state = reduce_context(raw_context, user_goal)
        history: list[dict] = []
        failures: list[str] = []
        route: list[str] = []
        converged = False

        for i in range(1, self.max_iterations + 1):
            route = choose_route(state)
            evidence = self.collect(state)
            contradictions = [e for e in evidence
                              if e.upper().startswith(("ERROR", "FAIL", "CONTRADICT"))]
            history.append({"iteration": i, "route": route,
                            "evidence": evidence,
                            "contradictions": contradictions})
            if not contradictions:
                converged = True
                break
            failures.extend(contradictions)
            state.known_facts.extend(contradictions)
            state.current_error = contradictions[0]
            if state.task_type not in ("bugfix", "release"):
                state.task_type = "bugfix"
                state.needs_code_edit = True

        escalated = not converged
        hypotheses = []
        if should_invoke(failures):
            hypotheses = analyze(failures, state)
        if escalated and "human_approval" not in route:
            route = route + ["human_approval"]

        return LoopResult(state=state, route=route, iterations=len(history),
                          converged=converged, escalated=escalated,
                          history=history, hypotheses=hypotheses)
