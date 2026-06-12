"""Audit logging for terminal private sessions.

Every session creates reports/surfing_ai_terminal_<timestamp>/ with
machine-readable logs and a human summary. Nothing here ever records
secret values — callers must pass already-safe strings.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Counters:
    external_backend_calls: int = 0
    mcp_calls: int = 0
    blocked_commands: int = 0
    files_sent_external: int = 0


class AuditSession:
    def __init__(self, project_root: str | Path = ".", mode: str = "private",
                 tag: str = ""):
        self.root = Path(project_root)
        stamp = time.strftime("%Y%m%d_%H%M%S")
        name = f"surfing_ai_terminal_{stamp}" + (f"_{tag}" if tag else "")
        self.dir = self.root / "reports" / name
        self.previews_dir = self.dir / "external_prompt_previews"
        self.previews_dir.mkdir(parents=True, exist_ok=True)
        self.mode = mode
        self.counters = Counters()
        self.started = time.time()
        self._write_json("session.json", {
            "mode": mode, "started": self.started, "root": str(self.root)})

    # ---- helpers ---------------------------------------------------------

    def _append(self, name: str, line: str) -> None:
        with (self.dir / name).open("a", encoding="utf-8") as fh:
            fh.write(line.rstrip("\n") + "\n")

    def _append_jsonl(self, name: str, record: dict) -> None:
        record = {"ts": time.time(), **record}
        self._append(name, json.dumps(record, ensure_ascii=False,
                                      default=str))

    def _write_json(self, name: str, data) -> None:
        (self.dir / name).write_text(
            json.dumps(data, indent=2, ensure_ascii=False, default=str),
            encoding="utf-8")

    # ---- recording -------------------------------------------------------

    def log_command(self, command: str, returncode: int | None = None) -> None:
        self._append("commands.log",
                     f"[{time.strftime('%H:%M:%S')}] rc={returncode} "
                     f"$ {command}")

    def log_blocked(self, command: str, reason: str) -> None:
        self.counters.blocked_commands += 1
        self._append("blocked_commands.log",
                     f"[{time.strftime('%H:%M:%S')}] BLOCKED ({reason}) "
                     f"$ {command}")

    def log_tool_call(self, tool: str, detail: dict | None = None,
                      mcp: bool = False) -> None:
        if mcp:
            self.counters.mcp_calls += 1
        self._append_jsonl("tool_calls.jsonl",
                           {"tool": tool, "mcp": mcp, **(detail or {})})

    def log_external_call(self, backend: str, prompt_chars: int,
                          files_sent: int = 0) -> None:
        self.counters.external_backend_calls += 1
        self.counters.files_sent_external += files_sent
        self._append_jsonl("tool_calls.jsonl",
                           {"tool": f"backend:{backend}", "mcp": False,
                            "prompt_chars": prompt_chars,
                            "files_sent": files_sent})

    def log_approval(self, record: dict) -> None:
        self._append_jsonl("approvals.jsonl", record)

    def save_backend_health(self, data: dict) -> None:
        self._write_json("backend_health.json", data)

    def save_preview(self, label: str, text: str) -> Path:
        safe = "".join(c if c.isalnum() or c in "-_" else "-"
                       for c in label)[:60]
        path = self.previews_dir / f"{int(time.time())}_{safe}.txt"
        path.write_text(text, encoding="utf-8")
        return path

    @property
    def approvals_path(self) -> Path:
        return self.dir / "approvals.jsonl"

    # ---- summary ---------------------------------------------------------

    def finalize(self) -> Path:
        c = self.counters
        passed = c.files_sent_external == 0
        lines = [
            "# Surfing AI terminal private session summary", "",
            f"- mode: {self.mode}",
            f"- duration_seconds: {int(time.time() - self.started)}", "",
            f"SURFING_AI_TERMINAL_PRIVATE_PASS = "
            f"{'true' if passed else 'false'}",
            f"external_backend_calls = {c.external_backend_calls}",
            f"mcp_calls = {c.mcp_calls}",
            f"blocked_commands = {c.blocked_commands}",
            f"files_sent_external = {c.files_sent_external}",
        ]
        path = self.dir / "summary.md"
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return path


def latest_session_dir(project_root: str | Path = ".") -> Path | None:
    reports = Path(project_root) / "reports"
    if not reports.is_dir():
        return None
    sessions = sorted(reports.glob("surfing_ai_terminal_*"))
    return sessions[-1] if sessions else None
