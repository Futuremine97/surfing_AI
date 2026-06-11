import os

import pytest

from harness.chat_agent import ChatAgent, ChatError


def offline_agent(tmp_path):
    os.environ.pop("ANTHROPIC_API_KEY", None)
    return ChatAgent(project_root=tmp_path)


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
    out = agent.chat([{"role": "user",
                       "content": "ValueError: synthetic failure in app.py"}])
    assert out["mode"] == "offline"
    assert "ValueError" in out["reply"]
    assert out["analysis"]["route"]


def test_command_in_message_is_risk_scanned(tmp_path):
    agent = offline_agent(tmp_path)
    out = agent.chat([{"role": "user", "content": "$ rm -rf / please check"}])
    assert out["analysis"]["command_scan"]["blocked"]
    assert "BLOCKED" in out["reply"]


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
