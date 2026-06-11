from pathlib import Path

import pytest

from harness.web_app import WEB_ROOT, WebAppService


def test_analyze_returns_state_audit_route_and_trace(tmp_path):
    service = WebAppService(tmp_path)
    result = service.analyze({
        "goal": "fix the failing test",
        "context": "tests/test_widget.py FAILED\nValueError: bad widget",
    })
    assert result["task"]["task_type"] == "bugfix"
    assert result["route"][-1] == "verifier"
    assert result["audit"]["status"] == "PASS"
    assert len(result["trace"]) == 3


def test_analyze_requires_goal(tmp_path):
    with pytest.raises(ValueError):
        WebAppService(tmp_path).analyze({"goal": "", "context": "anything"})


def test_orchestrate_returns_parallel_runtime_lanes(tmp_path):
    result = WebAppService(tmp_path).orchestrate({
        "goal": "redesign the local app",
        "providers": ["antigravity", "codex", "claude"],
    })
    assert result["mode"] == "parallel"
    assert result["provider_count"] == 3
    assert result["subagent_count"] == 9


def test_command_scan_blocks_destructive_command(tmp_path):
    result = WebAppService(tmp_path).scan_command({"command": "git reset --hard"})
    assert result["blocked"] and result["risk_score"] == 1.0


def test_verifier_uses_analyzed_task(tmp_path):
    service = WebAppService(tmp_path)
    analysis = service.analyze({
        "goal": "fix app/widget.py failure",
        "context": "app/widget.py FAILED",
    })
    result = service.verify({
        "task": analysis["task"],
        "outcome": {"tests_passed": True, "criteria_met": []},
    })
    assert result["approved"]


def test_release_scan_is_bound_to_project_root(tmp_path):
    (tmp_path / "README.md").write_text("clean synthetic project")
    result = WebAppService(tmp_path).release_scan({"user_approved": False})
    assert result["status"] == "BLOCKED_BY_MISSING_USER_APPROVAL"


def test_web_assets_exist():
    for name in ("index.html", "app.html", "styles.css", "app.js"):
        assert (Path(WEB_ROOT) / name).is_file()
