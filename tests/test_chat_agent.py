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


def make_arg_echo_cli(tmp_path):
    """Fake claude CLI that returns its own argv as the reply."""
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir(exist_ok=True)
    fake_cli = fake_bin / "claude"
    # pure sh so it runs under an isolated PATH (no python3 lookup);
    # our argv contains no JSON-breaking characters
    fake_cli.write_text(
        "#!/bin/sh\n"
        "printf '{\"result\": \"%s\"}\\n' \"$*\"\n")
    fake_cli.chmod(0o755)
    return fake_bin


def test_agent_mode_grants_read_tools_only(tmp_path):
    agent = offline_agent(tmp_path)
    fake_bin = make_arg_echo_cli(tmp_path)
    with isolated_path(fake_bin):
        out = agent.chat([{"role": "user", "content": "read my files"}],
                         agent_mode=True)
    assert out["mode"] == "claude_agent"
    assert "--allowedTools" in out["reply"]
    assert "WebFetch" in out["reply"]
    assert "Bash" not in out["reply"]          # shell never granted
    assert "Edit" not in out["reply"]          # edits off by default
    assert "acceptEdits" not in out["reply"]


def test_agent_mode_with_edits_opt_in(tmp_path):
    agent = offline_agent(tmp_path)
    fake_bin = make_arg_echo_cli(tmp_path)
    with isolated_path(fake_bin):
        out = agent.chat([{"role": "user", "content": "fix my file"}],
                         agent_mode=True, allow_edits=True)
    assert "Edit" in out["reply"] and "acceptEdits" in out["reply"]
    assert "Bash" not in out["reply"]


def test_text_mode_grants_no_tools(tmp_path):
    agent = offline_agent(tmp_path)
    fake_bin = make_arg_echo_cli(tmp_path)
    with isolated_path(fake_bin):
        out = agent.chat([{"role": "user", "content": "hello"}])
    assert "--allowedTools" not in out["reply"]


def test_work_dir_must_exist_and_be_absolute(tmp_path):
    agent = offline_agent(tmp_path)
    with pytest.raises(ChatError):
        agent.chat([{"role": "user", "content": "x"}],
                   agent_mode=True, work_dirs=["relative/path"])
    with pytest.raises(ChatError):
        agent.chat([{"role": "user", "content": "x"}],
                   agent_mode=True, work_dirs=[str(tmp_path / "nope")])


def make_named_cli(fake_bin, name, reply_text):
    cli = fake_bin / name
    if name == "claude":
        cli.write_text("#!/bin/sh\n"
                       f"printf '{{\"result\": \"{reply_text}\"}}\\n'\n")
    elif name == "codex":
        # codex adapter reads the --output-last-message file
        cli.write_text(
            "#!/bin/sh\n"
            "out=''\nprev=''\n"
            "for a in \"$@\"; do\n"
            "  [ \"$prev\" = '--output-last-message' ] && out=\"$a\"\n"
            "  prev=\"$a\"\ndone\n"
            f"[ -n \"$out\" ] && printf '{reply_text}' > \"$out\"\n"
            f"printf '{reply_text}\\n'\n")
    else:
        cli.write_text(f"#!/bin/sh\nprintf '{reply_text}\\n'\n")
    cli.chmod(0o755)


def test_codex_backend_explicit(tmp_path):
    agent = offline_agent(tmp_path)
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    make_named_cli(fake_bin, "codex", "hello from codex")
    with isolated_path(fake_bin):
        out = agent.chat([{"role": "user", "content": "hi"}],
                         backend="codex")
    assert out["mode"] == "codex_subscription"
    assert out["reply"] == "hello from codex"


def test_gemini_backend_explicit(tmp_path):
    agent = offline_agent(tmp_path)
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    make_named_cli(fake_bin, "gemini", "hello from gemini")
    with isolated_path(fake_bin):
        out = agent.chat([{"role": "user", "content": "hi"}],
                         backend="gemini")
    assert out["mode"] == "gemini_subscription"
    assert out["model"] == "gemini-cli"


def test_auto_falls_through_to_next_subscription(tmp_path):
    # only gemini installed -> auto should land on gemini
    agent = offline_agent(tmp_path)
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    make_named_cli(fake_bin, "gemini", "auto picked gemini")
    with isolated_path(fake_bin):
        out = agent.chat([{"role": "user", "content": "hi"}])
    assert out["mode"] == "gemini_subscription"


def test_unknown_backend_rejected(tmp_path):
    agent = offline_agent(tmp_path)
    with pytest.raises(ChatError):
        agent.chat([{"role": "user", "content": "hi"}], backend="gpt99")


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
