"""End-to-end invariant: a full redacted-external session transmits
zero file contents (files_sent_external == 0) and never leaks secret
values into prompts, previews, or the summary."""

from harness.terminal_private_mode import PrivateTerminal

SECRET_BODY = "TOP-SECRET-DOCUMENT-BODY-9381"
SECRET_KEY = "sk-livekey1234567890"


def run_session(tmp_path, answer="y"):
    (tmp_path / "private").mkdir()
    (tmp_path / "private" / "doc.txt").write_text(SECRET_BODY,
                                                  encoding="utf-8")
    sent = []
    terminal = PrivateTerminal(
        root=tmp_path, mode="redacted-external",
        input_fn=lambda prompt="": answer,
        output_fn=lambda *a, **k: None,
        backend_caller=lambda backend, prompt: sent.append(
            (backend, prompt)) or "backend response")

    terminal.handle("ls")
    terminal.handle("cat private/doc.txt")          # blocked by guard
    terminal.handle(f":ask claude key is {SECRET_KEY} summarize repo")
    summary_path = terminal.close()
    return terminal, sent, summary_path


def test_files_sent_external_is_zero(tmp_path):
    terminal, sent, _ = run_session(tmp_path)
    assert terminal.audit.counters.external_backend_calls == 1
    assert terminal.audit.counters.files_sent_external == 0


def test_secrets_never_reach_backend_or_disk(tmp_path):
    terminal, sent, _ = run_session(tmp_path)
    assert len(sent) == 1
    backend, prompt = sent[0]
    assert SECRET_KEY not in prompt
    assert SECRET_BODY not in prompt
    assert "[REDACTED" in prompt

    previews = list(terminal.audit.previews_dir.glob("*.txt"))
    assert previews, "preview must be written before approval"
    for preview in previews:
        text = preview.read_text(encoding="utf-8")
        assert SECRET_KEY not in text
        assert SECRET_BODY not in text
        assert "files_sent: 0" in text


def test_summary_reports_pass(tmp_path):
    terminal, _, summary_path = run_session(tmp_path)
    summary = summary_path.read_text(encoding="utf-8")
    assert "SURFING_AI_TERMINAL_PRIVATE_PASS = true" in summary
    assert "files_sent_external = 0" in summary
    assert SECRET_KEY not in summary


def test_denied_session_sends_nothing(tmp_path):
    terminal, sent, summary_path = run_session(tmp_path, answer="n")
    assert sent == []
    assert terminal.audit.counters.external_backend_calls == 0
    summary = summary_path.read_text(encoding="utf-8")
    assert "SURFING_AI_TERMINAL_PRIVATE_PASS = true" in summary
