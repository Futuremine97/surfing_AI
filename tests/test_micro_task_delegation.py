import pytest

from harness.micro_task_gate import (MicroTaskPolicyError, guard_payload,
                                     is_micro_task)
from harness.small_agent import SmallAgent, SmallAgentViolation
from harness.router import choose_route
from harness.state import TaskState

agent = SmallAgent()


def micro_state(**kw):
    defaults = dict(task_id="t1", user_goal="extract the first error",
                    task_type="micro")
    defaults.update(kw)
    return TaskState(**defaults)


def test_micro_task_routes_to_small_agent_only():
    assert choose_route(micro_state()) == ["small_agent"]


def test_side_effecting_task_is_not_micro():
    assert not is_micro_task(micro_state(needs_shell=True))
    assert not is_micro_task(micro_state(needs_code_edit=True))
    assert not is_micro_task(micro_state(risk_level="high",
                                         needs_human_approval=True))


def test_extract_first_error_line():
    out = agent.run("extract_first_error_line",
                    "ok line\nValueError: synthetic failure\nmore")
    assert out["ok"] and "ValueError" in out["result"]


def test_validate_json():
    assert agent.run("validate_json", '{"a": 1}')["result"]["valid"]
    assert not agent.run("validate_json", "{broken")["result"]["valid"]


def test_rank_relevant_files():
    out = agent.run("rank_relevant_files",
                    {"files": ["docs/notes.md", "app/login.py"],
                     "goal": "fix login bug"})
    assert out["result"][0] == "app/login.py"


def test_compress_test_output():
    text = "test_a PASSED\ntest_b FAILED\n=== 1 failed, 1 passed in 0.1s ==="
    res = agent.run("compress_test_output", text)["result"]
    assert res["failed"] and "failed" in res["summary"]


def test_unknown_capability_rejected():
    with pytest.raises(SmallAgentViolation):
        agent.run("write_file", "anything")


def test_gate_blocks_side_effect_payloads():
    with pytest.raises(MicroTaskPolicyError):
        guard_payload({"shell": "ls"}, blocklist=[])
    with pytest.raises(MicroTaskPolicyError):
        guard_payload({"write_file": "x.txt"}, blocklist=[])


def test_gate_blocks_restricted_terms_unless_private_mode():
    bl = ["internal-codename-orion"]
    with pytest.raises(MicroTaskPolicyError):
        guard_payload("notes about internal-codename-orion", blocklist=bl)
    # explicitly allowed in private mode
    guard_payload("notes about internal-codename-orion",
                  private_mode=True, blocklist=bl)
