from harness.coupled_approval_guard import (
    BLOCKED_BY_INTENT_MISMATCH, BLOCKED_BY_MISSING_ROLLBACK,
    BLOCKED_BY_MISSING_USER_APPROVAL, BLOCKED_BY_VERIFIER,
    BLOCKED_BY_WORST_CASE, STATUS_APPROVED,
    CoupledApprovalState, evaluate)


def full_state(**kw):
    base = dict(
        human_intent="yes, approve the delete of the old build folder",
        ai_proposal="delete the old build folder",
        verifier_approved=True,
        rollback_ref="checkpoint-001",
    )
    base.update(kw)
    return CoupledApprovalState(**base)


PAYLOAD = {"target": "build/", "rollback_ref": "checkpoint-001"}


def test_low_risk_action_passes_through():
    d = evaluate("read_file", {}, CoupledApprovalState())
    assert d.approved


def test_all_signals_present_approves():
    d = evaluate("delete", PAYLOAD, full_state())
    assert d.approved and d.status == STATUS_APPROVED


def test_missing_human_intent_blocks():
    d = evaluate("delete", PAYLOAD, full_state(human_intent=None))
    assert not d.approved and d.status == BLOCKED_BY_MISSING_USER_APPROVAL


def test_intent_mismatch_blocks():
    d = evaluate("delete", PAYLOAD,
                 full_state(human_intent="no, stop, do not remove anything"))
    assert not d.approved and d.status == BLOCKED_BY_INTENT_MISMATCH


def test_verifier_rejection_blocks():
    d = evaluate("delete", PAYLOAD, full_state(verifier_approved=False))
    assert not d.approved and d.status == BLOCKED_BY_VERIFIER


def test_missing_rollback_blocks():
    d = evaluate("delete", {"target": "build/"},
                 full_state(rollback_ref=None))
    assert not d.approved and d.status == BLOCKED_BY_MISSING_ROLLBACK


def test_worst_case_blocks_unguarded_publication():
    state = full_state(
        human_intent="yes approve publish the package",
        ai_proposal="publish the package",
    )
    d = evaluate("publish", {"release_guard_passed": False}, state)
    assert not d.approved and d.status == BLOCKED_BY_WORST_CASE


def test_worst_case_blocks_secret_exposure():
    state = full_state(
        human_intent="yes approve publish the package",
        ai_proposal="publish the package",
    )
    # synthetic credential-shaped string (matches the simulator's
    # detector but not a real provider format)
    payload = {"release_guard_passed": True,
               "content": "password: synthetic-test-value-123"}
    d = evaluate("publish", payload, state)
    assert not d.approved and d.status == BLOCKED_BY_WORST_CASE
