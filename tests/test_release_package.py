import io
import zipfile

from harness.release_package import build_release_bytes, read_version


def archive_names(root):
    data = build_release_bytes(root)
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        return archive.namelist()


def test_release_package_contains_runnable_app():
    names = archive_names(".")
    prefix = f"surfing-ai-{read_version('.')}/"
    assert prefix + "launch.command" in names
    assert prefix + "launch.bat" in names
    assert prefix + "scripts/run_web.py" in names
    assert prefix + "harness/web_app.py" in names
    assert prefix + "web/index.html" in names
    assert prefix + "AGENTS.md" in names
    assert prefix + ".codex/config.toml" in names
    assert prefix + ".agents/skills/surfing-team/SKILL.md" in names
    assert prefix + "agents/surfing-explorer.md" in names
    assert prefix + "integrations/antigravity/plugin.json" in names
    assert prefix + "LICENSE" in names


def test_release_package_excludes_private_material():
    names = archive_names(".")
    forbidden = (
        "/private/",
        ".private_release_blocklist",
        ".git/",
        ".DS_Store",
        "private_release_approval_trace",
    )
    assert not any(any(term in name for term in forbidden) for name in names)
