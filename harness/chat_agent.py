"""Chat agent: lets a user talk to an AI model through the harness gates.

Every outgoing message passes the same checks as any other task:
context reduction + routing (so the UI can show how the harness would
handle the request), a command risk scan when the text looks like shell,
and an outbound privacy gate — text matching the restricted-term
blocklist never leaves the machine.

Backend auto-detection, in order:
  1. ANTHROPIC_API_KEY (environment or gitignored .env) -> Anthropic API
  2. Claude Code CLI on PATH -> uses your existing Claude subscription
     login (claude -p, headless mode)
  3. Deterministic offline assistant
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import urllib.error
import urllib.request
from pathlib import Path

from .context_reducer import reduce_context
from .private_leak_guard import load_blocklist, scan_text
from .router import choose_route
from .safety_barrier import scan_command
from .small_agent import SmallAgent

ROOT = Path(__file__).resolve().parent.parent

API_URL = "https://api.anthropic.com/v1/messages"
API_VERSION = "2023-06-01"
DEFAULT_MODEL = os.environ.get("SURFING_CHAT_MODEL", "claude-sonnet-4-6")
API_KEY_ENV = "ANTHROPIC_API_KEY"
CLI_TIMEOUT = 180
AGENT_TIMEOUT = 600
MAX_MESSAGES = 40

# Read-only + web tools are safe to grant headlessly. Bash is never
# granted from the chat surface — shell stays behind the safety barrier.
AGENT_TOOLS_READ = "Read,Glob,Grep,WebFetch,WebSearch,TodoWrite"
AGENT_TOOLS_EDIT = AGENT_TOOLS_READ + ",Edit,Write,MultiEdit,NotebookEdit"
MAX_CHARS_PER_MESSAGE = 20_000

SYSTEM_PROMPT = (
    "You are Surfing AI, a local developer assistant running behind a "
    "verification-gated agent harness. Be concise and practical. When the "
    "user asks for shell commands, prefer safe, non-destructive forms and "
    "mention rollback options for anything risky."
)


class ChatError(ValueError):
    pass


def _validate_messages(messages) -> list[dict]:
    if not isinstance(messages, list) or not messages:
        raise ChatError("messages must be a non-empty list")
    if len(messages) > MAX_MESSAGES:
        messages = messages[-MAX_MESSAGES:]
    clean = []
    for item in messages:
        if not isinstance(item, dict):
            raise ChatError("each message must be an object")
        role = item.get("role")
        content = str(item.get("content", "")).strip()
        if role not in ("user", "assistant"):
            raise ChatError("message role must be 'user' or 'assistant'")
        if not content:
            raise ChatError("message content must not be empty")
        clean.append({"role": role, "content": content[:MAX_CHARS_PER_MESSAGE]})
    if clean[-1]["role"] != "user":
        raise ChatError("last message must be from the user")
    return clean


class ChatAgent:
    def __init__(self, project_root: str | Path = ROOT,
                 model: str = DEFAULT_MODEL):
        self.project_root = Path(project_root)
        self.model = model
        self.small_agent = SmallAgent()

    def _api_key(self) -> str:
        """Environment variable first, then the gitignored .env file."""
        key = os.environ.get(API_KEY_ENV, "")
        if key:
            return key
        env_file = self.project_root / ".env"
        if env_file.is_file():
            for line in env_file.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line.startswith(API_KEY_ENV + "="):
                    return line.split("=", 1)[1].strip().strip("'\"")
        return ""

    # ---- harness gates -------------------------------------------------

    def _analyze(self, messages: list[dict]) -> dict:
        last = messages[-1]["content"]
        history = "\n".join(m["content"] for m in messages[:-1])
        state = reduce_context(history, last)
        analysis = {
            "task_type": state.task_type,
            "risk_level": state.risk_level,
            "route": choose_route(state),
        }
        first_line = last.strip().splitlines()[0] if last.strip() else ""
        looks_like_command = first_line.startswith(("$", "sudo", "rm ", "git ",
                                                    "curl ", "wget ", "dd "))
        if looks_like_command:
            scan = scan_command(first_line.lstrip("$ "))
            analysis["command_scan"] = {
                "blocked": scan.blocked, "reasons": scan.reasons,
                "warnings": scan.warnings,
            }
        return analysis

    def _outbound_privacy_check(self, messages: list[dict]) -> list[str]:
        blocklist = load_blocklist(self.project_root)
        text = "\n".join(m["content"] for m in messages)
        return [term for term, _ in scan_text(text, blocklist.terms)]

    # ---- backends ------------------------------------------------------

    @staticmethod
    def _find_claude_cli() -> str | None:
        """Claude Code CLI, if installed and on PATH."""
        return shutil.which("claude")

    @staticmethod
    def _resolve_work_dirs(work_dirs) -> list[Path]:
        resolved = []
        for raw in work_dirs or []:
            path = Path(str(raw)).expanduser()
            if not path.is_absolute():
                raise ChatError(f"work_dir must be an absolute path: {raw}")
            if not path.is_dir():
                raise ChatError(f"work_dir does not exist: {raw}")
            resolved.append(path.resolve())
        return resolved

    def _call_claude_cli(self, cli: str, messages: list[dict],
                         agent_mode: bool = False,
                         allow_edits: bool = False,
                         work_dirs: list[Path] | None = None) -> str:
        """Headless call through Claude Code — reuses the user's existing
        Claude subscription login; no API key required.

        agent_mode grants read-only file/web tools; allow_edits adds
        write/edit tools with auto-accepted edits. Bash is never granted.
        """
        lines = []
        for m in messages[:-1]:
            speaker = "User" if m["role"] == "user" else "Assistant"
            lines.append(f"{speaker}: {m['content']}")
        transcript = "\n".join(lines)
        prompt = messages[-1]["content"]
        if transcript:
            prompt = (f"Conversation so far:\n{transcript}\n\n"
                      f"User: {prompt}")

        cmd = [cli, "-p", prompt, "--output-format", "json",
               "--append-system-prompt", SYSTEM_PROMPT]
        cwd = self.project_root
        timeout = CLI_TIMEOUT
        if agent_mode:
            timeout = AGENT_TIMEOUT
            tools = AGENT_TOOLS_EDIT if allow_edits else AGENT_TOOLS_READ
            cmd += ["--allowedTools", tools]
            if allow_edits:
                cmd += ["--permission-mode", "acceptEdits"]
            dirs = list(work_dirs or [])
            if dirs:
                cwd = dirs[0]
                for extra in dirs[1:]:
                    cmd += ["--add-dir", str(extra)]

        proc = subprocess.run(
            cmd, cwd=str(cwd),
            capture_output=True, text=True, timeout=timeout)
        if proc.returncode != 0:
            raise RuntimeError(
                f"claude CLI exited {proc.returncode}: {proc.stderr[:300]}")
        data = json.loads(proc.stdout)
        reply = data.get("result") if isinstance(data, dict) else None
        if not reply:
            raise RuntimeError("claude CLI returned no result text")
        return str(reply)

    def _call_model(self, messages: list[dict]) -> str:
        api_key = self._api_key()
        body = json.dumps({
            "model": self.model,
            "max_tokens": 1024,
            "system": SYSTEM_PROMPT,
            "messages": messages,
        }).encode("utf-8")
        request = urllib.request.Request(
            API_URL, data=body, method="POST",
            headers={
                "content-type": "application/json",
                "x-api-key": api_key,
                "anthropic-version": API_VERSION,
            })
        with urllib.request.urlopen(request, timeout=90) as response:
            data = json.loads(response.read().decode("utf-8"))
        parts = [b.get("text", "") for b in data.get("content", [])
                 if b.get("type") == "text"]
        return "\n".join(p for p in parts if p) or "(empty model response)"

    def _offline_reply(self, messages: list[dict], analysis: dict,
                       note: str) -> str:
        last = messages[-1]["content"]
        lines = [note, ""]
        scan = analysis.get("command_scan")
        if scan:
            if scan["blocked"]:
                lines.append("Command guard: BLOCKED — "
                             + "; ".join(scan["reasons"]))
            elif scan["warnings"]:
                lines.append("Command guard: caution — "
                             + "; ".join(scan["warnings"]))
            else:
                lines.append("Command guard: no destructive pattern found.")
        error = self.small_agent.run("extract_first_error_line", last)["result"]
        if error:
            lines.append(f"First error in your message: {error}")
        lines.append(f"Task type: {analysis['task_type']} | "
                     f"risk: {analysis['risk_level']} | "
                     f"route: {' -> '.join(analysis['route'])}")
        return "\n".join(lines)

    # ---- entry point ---------------------------------------------------

    def chat(self, messages, agent_mode: bool = False,
             allow_edits: bool = False, work_dirs=None) -> dict:
        messages = _validate_messages(messages)
        analysis = self._analyze(messages)
        resolved_dirs = self._resolve_work_dirs(work_dirs)
        analysis["agent_mode"] = agent_mode
        analysis["allow_edits"] = bool(agent_mode and allow_edits)

        privacy_hits = self._outbound_privacy_check(messages)
        if privacy_hits:
            reply = self._offline_reply(
                messages, analysis,
                "This conversation contains restricted internal terms, so it "
                "was answered locally and never sent to an external model.")
            return {"reply": reply, "mode": "privacy_blocked",
                    "analysis": analysis, "model": None}

        # Agent mode needs tool use, which only the CLI backend provides;
        # the direct API path stays text-only.
        if self._api_key() and not agent_mode:
            try:
                reply = self._call_model(messages)
                return {"reply": reply, "mode": "model",
                        "analysis": analysis, "model": self.model}
            except (urllib.error.URLError, urllib.error.HTTPError,
                    TimeoutError, json.JSONDecodeError) as exc:
                reply = self._offline_reply(
                    messages, analysis,
                    f"The external model is unreachable ({exc}); "
                    "here is the local analysis instead.")
                return {"reply": reply, "mode": "offline_fallback",
                        "analysis": analysis, "model": self.model}

        cli = self._find_claude_cli()
        if cli:
            try:
                reply = self._call_claude_cli(
                    cli, messages, agent_mode=agent_mode,
                    allow_edits=agent_mode and allow_edits,
                    work_dirs=resolved_dirs)
                mode = "claude_agent" if agent_mode else "claude_subscription"
                return {"reply": reply, "mode": mode,
                        "analysis": analysis, "model": "claude-code-cli"}
            except (RuntimeError, OSError, subprocess.TimeoutExpired,
                    json.JSONDecodeError) as exc:
                reply = self._offline_reply(
                    messages, analysis,
                    f"Claude Code CLI was found but the call failed ({exc}); "
                    "here is the local analysis instead. Try `claude` in a "
                    "terminal to check your login.")
                return {"reply": reply, "mode": "offline_fallback",
                        "analysis": analysis, "model": "claude-code-cli"}

        if agent_mode:
            reply = self._offline_reply(
                messages, analysis,
                "Agent mode needs the Claude Code CLI (file/web tools), "
                "but it was not found on PATH. Install and log in to "
                "Claude Code, then retry.")
            return {"reply": reply, "mode": "offline",
                    "analysis": analysis, "model": None}

        reply = self._offline_reply(
            messages, analysis,
            "No AI backend found, so I answered with the local "
            "deterministic assistant. Either set ANTHROPIC_API_KEY (env or "
            ".env file), or install and log in to Claude Code — it will be "
            "auto-detected and use your Claude subscription.")
        return {"reply": reply, "mode": "offline",
                "analysis": analysis, "model": None}
