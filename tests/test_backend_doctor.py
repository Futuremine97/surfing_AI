import json
import os

import pytest

from harness.backend_doctor import diagnose, launch_login


def isolated(tmp_path, monkeypatch_path):
    os.environ["PATH"] = str(monkeypatch_path)


def test_diagnose_reports_missing_clis(tmp_path):
    old_path = os.environ["PATH"]
    os.environ["PATH"] = str(tmp_path / "empty")
    try:
        statuses = {b["backend"]: b
                    for b in diagnose(home=tmp_path, project_root=tmp_path)}
    finally:
        os.environ["PATH"] = old_path
    assert not statuses["claude"]["installed"]
    assert statuses["claude"]["install_command"]
    assert statuses["codex"]["login_command"] == "codex login"


def test_diagnose_detects_auth_files_and_keys(tmp_path):
    home = tmp_path / "home"
    (home / ".claude").mkdir(parents=True)
    (home / ".claude" / ".credentials.json").write_text("{}")
    (home / ".gemini").mkdir()
    (home / ".gemini" / "oauth_creds.json").write_text("{}")
    project = tmp_path / "proj"
    project.mkdir()
    (project / ".env").write_text("OPENAI_API_KEY=synthetic-test\n")

    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    for name in ("claude", "codex", "gemini"):
        cli = fake_bin / name
        cli.write_text("#!/bin/sh\n"
                       "[ \"$1\" = '--version' ] && echo 'v1.0 test'\n"
                       "[ \"$1\" = 'login' ] && exit 0\n"
                       "exit 0\n")
        cli.chmod(0o755)

    old_path = os.environ["PATH"]
    os.environ["PATH"] = str(fake_bin)
    try:
        statuses = {b["backend"]: b
                    for b in diagnose(home=home, project_root=project)}
    finally:
        os.environ["PATH"] = old_path

    assert statuses["claude"]["authenticated"] is True
    assert statuses["gemini"]["authenticated"] is True
    assert statuses["codex"]["authenticated"] is True   # login status rc=0
    assert statuses["codex"]["key_present"]             # from .env
    assert "v1.0" in statuses["claude"]["version"]


def test_launch_login_rejects_unknown_backend():
    with pytest.raises(ValueError):
        launch_login("not-a-backend")
