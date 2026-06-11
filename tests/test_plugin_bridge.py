import json

from harness.plugin_bridge import apply_plan, build_plan, is_claude_plugin


def fake_plugin(tmp_path):
    plugin = tmp_path / "plugins" / "demo-plugin"
    (plugin / ".claude-plugin").mkdir(parents=True)
    (plugin / ".claude-plugin" / "plugin.json").write_text(
        json.dumps({"name": "demo-plugin"}))
    skill = plugin / "skills" / "route-helper"
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text(
        "---\nname: route-helper\ndescription: synthetic skill\n---\n"
        "# Route helper\nDo the routing.\n")
    (plugin / "commands").mkdir()
    (plugin / "commands" / "verify.md").write_text("Run the verifier.\n")
    (plugin / "agents").mkdir()
    (plugin / "agents" / "builder.md").write_text(
        "---\nname: builder\n---\nBuild things carefully.\n")
    (plugin / ".mcp.json").write_text(json.dumps({
        "mcpServers": {"demo server": {"command": "demo-mcp",
                                       "args": ["--stdio"]}}}))
    return plugin


def test_is_claude_plugin(tmp_path):
    plugin = fake_plugin(tmp_path)
    assert is_claude_plugin(plugin)
    assert not is_claude_plugin(tmp_path)


def test_plan_lists_all_convertibles(tmp_path):
    plan = build_plan(fake_plugin(tmp_path), home=tmp_path / "home")
    kinds = sorted(a.kind for a in plan.actions)
    assert kinds == ["mcp", "prompt", "prompt", "prompt"]
    targets = " ".join(a.target for a in plan.actions)
    assert "demo-plugin-route-helper.md" in targets
    assert "demo-plugin-verify.md" in targets
    assert "demo-plugin-agent-builder.md" in targets
    assert "[mcp_servers.demo-server]" in targets
    assert not plan.applied


def test_apply_writes_prompts_and_mcp_with_backup(tmp_path):
    home = tmp_path / "home"
    config = home / ".codex" / "config.toml"
    config.parent.mkdir(parents=True)
    config.write_text("# existing codex config\n")

    plan = apply_plan(build_plan(fake_plugin(tmp_path), home=home), home=home)
    assert plan.applied
    assert all(a.status == "written" for a in plan.actions)

    prompt = home / ".codex" / "prompts" / "demo-plugin-route-helper.md"
    text = prompt.read_text()
    assert "Do the routing." in text
    assert "---" not in text.split("\n\n")[0]  # frontmatter stripped
    assert "converted from Claude Code plugin" in text

    config_text = config.read_text()
    assert "[mcp_servers.demo-server]" in config_text
    assert 'command = "demo-mcp"' in config_text
    assert list(config.parent.glob("config.toml.bak-*"))  # backup made
    assert any("backed up" in n for n in plan.notes)


def test_second_run_is_idempotent(tmp_path):
    home = tmp_path / "home"
    plugin = fake_plugin(tmp_path)
    apply_plan(build_plan(plugin, home=home), home=home)
    second = build_plan(plugin, home=home)
    assert all(a.status == "skipped_exists" for a in second.actions)
    before = (home / ".codex" / "config.toml").read_text()
    apply_plan(second, home=home)
    assert (home / ".codex" / "config.toml").read_text() == before
