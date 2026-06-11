import json

from harness.connections import scan_connections
from harness.web_app import WebAppService


def fake_home(tmp_path):
    home = tmp_path / "home"
    (home / ".claude" / "skills" / "my-skill").mkdir(parents=True)
    (home / ".claude" / "skills" / "my-skill" / "SKILL.md").write_text(
        "---\nname: my-skill\ndescription: synthetic demo skill\n---\n")
    (home / ".claude.json").write_text(json.dumps({
        "mcpServers": {"demo-mcp": {"command": "demo-server --stdio"}}}))
    (home / ".codex").mkdir()
    (home / ".codex" / "config.toml").write_text(
        '[mcp_servers.codex-demo]\ncommand = "demo"\n')
    (home / ".gemini").mkdir()
    (home / ".gemini" / "settings.json").write_text(json.dumps({
        "mcpServers": {"gemini-demo": {"url": "http://localhost:1234"}}}))
    return home


def test_scan_finds_mcp_servers_across_runtimes(tmp_path):
    report = scan_connections(home=fake_home(tmp_path),
                              project_root=tmp_path / "proj")
    names = {(c.runtime, c.name) for c in report.mcp_servers}
    assert ("claude", "demo-mcp") in names
    assert ("codex", "codex-demo") in names
    assert ("antigravity", "gemini-demo") in names


def test_scan_finds_skills_with_metadata(tmp_path):
    report = scan_connections(home=fake_home(tmp_path),
                              project_root=tmp_path / "proj")
    skills = {c.name: c for c in report.skills}
    assert "my-skill" in skills
    assert "synthetic demo skill" in skills["my-skill"].detail
    assert skills["my-skill"].path  # clickable target exists


def test_every_item_has_source_path_for_reveal(tmp_path):
    report = scan_connections(home=fake_home(tmp_path),
                              project_root=tmp_path / "proj")
    for item in report.mcp_servers + report.skills:
        assert item.path, f"{item.name} missing source path"
    assert report.paths()


def test_scan_finds_installed_claude_plugins(tmp_path):
    home = fake_home(tmp_path)
    (home / ".claude").mkdir(exist_ok=True)
    (home / ".claude" / "settings.json").write_text(json.dumps({
        "enabledPlugins": {
            "verification-gated-harness@futuremine97-tools": True,
            "old-plugin@some-marketplace": False,
        }}))
    cache = home / ".claude" / "plugins" / "cache" / "futuremine97-tools"
    cache.mkdir(parents=True)
    report = scan_connections(home=home, project_root=tmp_path / "proj")
    plugins = {c.name: c for c in report.plugins}
    assert "verification-gated-harness" in plugins
    assert plugins["verification-gated-harness"].found
    assert "futuremine97-tools" in plugins["verification-gated-harness"].detail
    assert plugins["verification-gated-harness"].path  # clickable
    assert not plugins["old-plugin"].found  # disabled shown dimmed


def test_open_path_rejects_unlisted_paths(tmp_path):
    service = WebAppService(project_root=tmp_path)
    secret = tmp_path / "unrelated.txt"
    secret.write_text("x")
    try:
        service.open_path({"path": str(secret)})
        assert False, "expected rejection"
    except ValueError as exc:
        assert "not in the latest connections scan" in str(exc)
