import json

from harness.capability_registry import (CapabilityRegistry,
                                         MCP_DEFAULT_TOKENS, STATE_FILE)


def make_project(tmp_path):
    (tmp_path / "skills" / "alpha").mkdir(parents=True)
    (tmp_path / "skills" / "alpha" / "SKILL.md").write_text(
        "x" * 400, encoding="utf-8")
    (tmp_path / "integrations" / "beta").mkdir(parents=True)
    (tmp_path / "integrations" / "beta" / "plugin.md").write_text(
        "y" * 800, encoding="utf-8")
    (tmp_path / ".mcp.json").write_text(json.dumps(
        {"mcpServers": {"files": {}, "web": {}}}), encoding="utf-8")
    return CapabilityRegistry(tmp_path)


def test_discovery_kinds_and_defaults(tmp_path):
    registry = make_project(tmp_path)
    caps = {c.id: c for c in registry.discover()}
    assert caps["skill:skills/alpha"].enabled is True
    assert caps["skill:skills/alpha"].est_tokens == 100   # 400 chars / 4
    assert caps["plugin:integrations/beta"].enabled is True
    assert caps["plugin:integrations/beta"].est_tokens == 200
    # MCP servers default OFF (private-mode posture)
    assert caps["mcp:files"].enabled is False
    assert caps["mcp:web"].est_tokens == MCP_DEFAULT_TOKENS


def test_toggle_persists(tmp_path):
    registry = make_project(tmp_path)
    result = registry.set_enabled("mcp:files", True)
    assert result == {"id": "mcp:files", "enabled": True}
    registry.set_enabled("skill:skills/alpha", False)

    reopened = CapabilityRegistry(tmp_path)
    caps = {c.id: c for c in reopened.discover()}
    assert caps["mcp:files"].enabled is True
    assert caps["skill:skills/alpha"].enabled is False
    assert (tmp_path / STATE_FILE).is_file()


def test_unknown_capability_rejected(tmp_path):
    registry = make_project(tmp_path)
    assert "error" in registry.set_enabled("skill:nope", True)


def test_summary_token_math_is_consistent(tmp_path):
    registry = make_project(tmp_path)
    s = registry.summary()
    # defaults: skill(100) + plugin(200) enabled; 2 mcp (600 each) off
    assert s["baseline_tokens_per_request"] == 100 + 200 + 1200
    assert s["enabled_tokens_per_request"] == 300
    assert s["saved_tokens_per_request"] == 1200
    assert s["saved_tokens_per_100_requests"] == 120000
    assert s["saved_percent"] == 80.0
    assert "zero model tokens" in s["computation"]

    registry.set_enabled("skill:skills/alpha", False)
    s2 = registry.summary()
    assert s2["saved_tokens_per_request"] == 1300


def test_empty_project_summary(tmp_path):
    registry = CapabilityRegistry(tmp_path)
    s = registry.summary()
    assert s["capabilities"] == 0
    assert s["saved_percent"] == 0.0
