"""Gitignored paths cannot be published by git, so publish-scanners skip
them — but tracked leaks must still block."""

from harness.private_leak_guard import (Blocklist, check, is_ignored,
                                        load_ignore_rules)
from harness.public_release_guard import run_release_check
from pathlib import Path

BL = Blocklist(terms=["internal-codename-orion"])


def setup_repo(tmp_path):
    (tmp_path / ".gitignore").write_text(
        "research_dir/\n*.weights\nnotes.local\n")
    (tmp_path / "README.md").write_text("clean synthetic project")
    private_dir = tmp_path / "research_dir"
    private_dir.mkdir()
    (private_dir / "model.py").write_text(
        "about internal-codename-orion experiments")
    return tmp_path


def test_ignore_rules_parsing(tmp_path):
    setup_repo(tmp_path)
    rules = load_ignore_rules(tmp_path)
    assert is_ignored(Path("research_dir/model.py"), rules)
    assert is_ignored(Path("deep/file.weights"), rules)
    assert is_ignored(Path("sub/notes.local"), rules)
    assert not is_ignored(Path("harness/router.py"), rules)


def test_gitignored_leak_does_not_block(tmp_path):
    setup_repo(tmp_path)
    assert check(tmp_path, blocklist=BL).status == "PASS"
    assert run_release_check(tmp_path, user_approved=True,
                             blocklist=BL).passed


def test_tracked_leak_still_blocks(tmp_path):
    setup_repo(tmp_path)
    (tmp_path / "docs.md").write_text("mentions internal-codename-orion")
    report = check(tmp_path, blocklist=BL)
    assert report.status == "BLOCKED_BY_PRIVATE_LEAK_RISK"
    assert report.findings[0].location == "docs.md"
