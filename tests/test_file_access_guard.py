import pytest

from harness.file_access_guard import (FileAccessGuard, load_private_config,
                                       PrivateModeConfig)

DENIED_DEFAULTS = [
    "private/notes.md",
    "secrets/key.txt",
    "credentials/aws.json",
    ".env",
    "deploy/prod.env",
    "certs/server.pem",
    "id_rsa.key",
    "model/weights.npy",
    "cache/data.pkl",
    "app.sqlite",
]


@pytest.mark.parametrize("path", DENIED_DEFAULTS)
def test_default_denies(tmp_path, path):
    guard = FileAccessGuard(tmp_path)
    decision = guard.check(path)
    assert not decision.allowed
    assert decision.reason


@pytest.mark.parametrize("path", ["README.md", "harness/router.py",
                                  "docs/TERMINAL_PRIVATE_MODE.md"])
def test_default_allows_normal_files(tmp_path, path):
    guard = FileAccessGuard(tmp_path)
    assert guard.check(path).allowed


def test_path_outside_root_denied(tmp_path):
    guard = FileAccessGuard(tmp_path / "project")
    decision = guard.check(str(tmp_path / "elsewhere" / "x.txt"))
    assert not decision.allowed
    assert "outside" in decision.reason


def test_guard_is_independent_of_gitignore(tmp_path):
    # gitignore is NOT a security boundary: an ignored file is still
    # denied, and an un-ignored private file is denied too.
    (tmp_path / ".gitignore").write_text("only_this.txt\n",
                                         encoding="utf-8")
    guard = FileAccessGuard(tmp_path)
    assert not guard.check("private/plan.md").allowed
    assert not guard.check(".env").allowed
    # and a gitignored but harmless file stays readable
    assert guard.check("only_this.txt").allowed


def test_config_defaults_when_file_missing(tmp_path):
    config = load_private_config(tmp_path)
    assert config.external_backends_default is False
    assert config.mcp_default is False
    assert "private/" in config.deny_paths
    assert config.source == "defaults"


def test_config_file_overrides(tmp_path):
    (tmp_path / ".surfing_ai_private.yaml").write_text(
        "private_mode:\n"
        "  external_backends_default: false\n"
        "  deny_paths:\n"
        "    - vault/\n"
        "  deny_globs:\n"
        "    - '*.hidden'\n",
        encoding="utf-8")
    config = load_private_config(tmp_path)
    assert config.deny_paths == ["vault/"]
    assert config.deny_globs == ["*.hidden"]
    assert config.source.endswith(".surfing_ai_private.yaml")

    guard = FileAccessGuard(tmp_path, config=config)
    assert not guard.check("vault/x.txt").allowed
    assert not guard.check("notes/a.hidden").allowed
    assert guard.check("README.md").allowed


def test_defaults_object_is_not_shared():
    a, b = PrivateModeConfig(), PrivateModeConfig()
    a.deny_paths.append("extra/")
    assert "extra/" not in b.deny_paths
