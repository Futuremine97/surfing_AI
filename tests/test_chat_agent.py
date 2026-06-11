import contextlib
import os

import pytest

from harness.chat_agent import ChatAgent, ChatError


def offline_agent(tmp_path):
    os.environ.pop("ANTHROPIC_API_KEY", None)
    return ChatAgent(project_root=tmp_path)


@contextlib.contextmanager
def isolated_path(path_value):
    """Control which executables are visible so backend auto-detection
    (e.g. a real claude CLI on this machine) cannot leak into tests."""
    old = os.environ["PATH"]
    os.environ["PATH"] = str(path_value)
    try:
        yield
    finally:
        os.environ["PATH"] = old


def test_rejects_empty_and_malformed_messages(tmp_path):
    agent = offline_agent(tmp_path)
    with pytest.raises(ChatError):
        agent.chat([])
    with pytest.raises(ChatError):
        agent.chat([{"role": "system", "content": "x"}])
    with pytest.raises(ChatError):
        agent.chat([{"role": "assistant", "content": "ends with assistant"}])


def test_offline_mode_answers_locally(tmp_path):
    agent = offline_agent(tmp_path)
    with isolated_path(tmp_path / "empty"):
        out = agent.chat([{"role": "user",
                           "content": "ValueError: synthetic failure in app.py"}])
    assert out["mode"] == "offline"
    assert "ValueError" in out["reply"]
    assert out["analysis"]["route"]


def test_command_in_message_is_risk_scanned(tmp_path):
    agent = offline_agent(tmp_path)
    with isolated_path(tmp_path / "empty"):
        out = agent.chat([{"role": "user",
                           "content": "$ rm -rf / please check"}])
    assert out["analysis"]["command_scan"]["blocked"]
    assert "BLOCKED" in out["reply"]


def test_claude_cli_auto_detected(tmp_path):
    agent = offline_agent(tmp_path)
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    fake_cli = fake_bin / "claude"
    fake_cli.write_text(
        "#!/bin/sh\necho '{\"result\": \"hello from fake cli\"}'\n")
    fake_cli.chmod(0o755)
    with isolated_path(fake_bin):
        out = agent.chat([{"role": "user", "content": "hello there"}])
    assert out["mode"] == "claude_subscription"
    assert out["reply"] == "hello from fake cli"
    assert out["model"] == "claude-code-cli"


def test_no_backend_falls_back_offline(tmp_path):
    agent = offline_agent(tmp_path)
    with isolated_path(tmp_path / "empty"):
        out = agent.chat([{"role": "user", "content": "hello"}])
    assert out["mode"] == "offline"


def test_restricted_terms_never_sent_externally(tmp_path):
    (tmp_path / ".private_release_blocklist.yaml").write_text(
        "terms:\n  - internal-codename-orion\n")
    agent = offline_agent(tmp_path)
    # even with a key set, the privacy gate must answer locally
    os.environ["ANTHROPIC_API_KEY"] = "test-placeholder"
    try:
        out = agent.chat([{"role": "user",
                           "content": "tell me about internal-codename-orion"}])
    finally:
        os.environ.pop("ANTHROPIC_API_KEY", None)
    assert out["mode"] == "privacy_blocked"
    assert out["model"] is None
