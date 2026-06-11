from harness.router import choose_route
from harness.state import TaskState


def make(**kw):
    base = dict(task_id="t", user_goal="g")
    base.update(kw)
    return TaskState(**base)


def test_release_route_takes_priority():
    t = make(public_release_requested=True, risk_level="high",
             needs_code_edit=True, needs_human_approval=True)
    assert choose_route(t) == ["public_release_guard",
                               "scrape_resilience_scan", "human_approval"]


def test_high_risk_route():
    t = make(risk_level="high", needs_human_approval=True)
    assert choose_route(t) == ["context_reducer", "planner",
                               "verifier", "human_approval"]


def test_needs_human_approval_alone_triggers_approval_route():
    t = make(needs_human_approval=True)
    assert "human_approval" in choose_route(t)


def test_code_edit_route():
    t = make(needs_code_edit=True)
    assert choose_route(t) == ["context_reducer", "coding_agent",
                               "test_runner", "verifier"]


def test_shell_route_includes_risk_scan_before_shell():
    t = make(needs_shell=True)
    route = choose_route(t)
    assert route.index("command_risk_scan") < route.index("shell_tool")
    assert route[-1] == "verifier"


def test_micro_route():
    t = make(task_type="micro")
    assert choose_route(t) == ["small_agent"]


def test_default_route_has_verifier():
    t = make(task_type="general")
    assert choose_route(t)[-1] == "verifier"
