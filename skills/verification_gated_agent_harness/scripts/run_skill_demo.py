#!/usr/bin/env python3
"""End-to-end synthetic demo of the verification-gated harness."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from harness.context_reducer import reduce_context
from harness.coupled_approval_guard import CoupledApprovalState, evaluate
from harness.micro_task_gate import guard_payload
from harness.reduction_audit import audit_reduction
from harness.router import choose_route
from harness.small_agent import SmallAgent
from harness.trace import TraceStore
from harness.validator import VerifierGate

SYNTHETIC_LOG = """\
$ pytest tests/
tests/test_widget.py FAILED
E   ValueError: synthetic widget size must be positive
see src/widget.py
"""


def main() -> int:
    trace = TraceStore()

    # 1. Reduce + audit
    state = reduce_context(SYNTHETIC_LOG, "fix the failing widget test")
    audit = audit_reduction(SYNTHETIC_LOG, state, choose_route)
    trace.record(state.task_id, "reduction_audit", status=audit.status)
    print("compact state:", state.compact_summary)
    print("audit:", audit.status)

    # 2. Route
    route = choose_route(state)
    print("route:", " -> ".join(route))

    # 3. Micro delegation
    guard_payload(SYNTHETIC_LOG, blocklist=[])
    micro = SmallAgent().run("extract_first_error_line", SYNTHETIC_LOG)
    print("small agent:", micro["result"])

    # 4. Verify a (synthetic) outcome
    judgment = VerifierGate().verify(state, {"tests_passed": True,
                                             "criteria_met": []})
    print("verifier:", "approved" if judgment.approved else "rejected",
          "-", "; ".join(judgment.reasons))

    # 5. High-risk action requires the full coupled approval state
    approval = CoupledApprovalState(
        human_intent="yes, approve the delete of stale build artifacts",
        ai_proposal="delete stale build artifacts",
        verifier_approved=True,
        rollback_ref="checkpoint-demo-1",
    )
    decision = evaluate("delete", {"target": "build/"}, approval)
    print("high-risk gate:", decision.status)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
