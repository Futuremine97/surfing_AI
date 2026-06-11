import pytest

from harness.multi_agent import build_orchestration_plan, runtime_catalog


def test_catalog_lists_all_supported_runtimes():
    assert [item["key"] for item in runtime_catalog()] == [
        "antigravity",
        "codex",
        "claude",
    ]


def test_plan_runs_parent_and_subagents_across_all_runtimes():
    plan = build_orchestration_plan("ship the feature", "tests must pass")

    assert plan["mode"] == "parallel"
    assert plan["provider_count"] == 3
    assert plan["agent_count"] == 3
    assert plan["subagent_count"] == 9
    assert len(plan["lanes"]) == 3
    assert all(len(lane["subagents"]) == 3 for lane in plan["lanes"])
    assert {agent["role"] for agent in plan["lanes"][0]["subagents"]} == {
        "explorer",
        "builder",
        "verifier",
    }


def test_plan_can_target_a_runtime_subset():
    plan = build_orchestration_plan("review the patch", providers=["codex"])
    assert plan["provider_count"] == 1
    assert plan["lanes"][0]["runtime"] == "codex"


def test_plan_rejects_unknown_runtime():
    with pytest.raises(ValueError, match="unsupported provider"):
        build_orchestration_plan("do work", providers=["unknown"])
