"""Chat agent: lets a user talk to an AI model through the harness gates.

Every outgoing message passes the same checks as any other task:
context reduction + routing (so the UI can show how the harness would
handle the request), a command risk scan when the text looks like shell,
and an outbound privacy gate — text matching the restricted-term
blocklist never leaves the machine.

Uses the Anthropic API when ANTHROPIC_API_KEY is set (stdlib urllib, no
SDK required). Falls back to a deterministic offline assistant otherwise.
"""

from __future__ import annotations

import json
import os
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
MAX_MESSAGES = 40
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

    def chat(self, messages) -> dict:
        messages = _validate_messages(messages)
        analysis = self._analyze(messages)

        privacy_hits = self._outbound_privacy_check(messages)
        if privacy_hits:
            reply = self._offline_reply(
                messages, analysis,
                "This conversation contains restricted internal terms, so it "
                "was answered locally and never sent to an external model.")
            return {"reply": reply, "mode": "privacy_blocked",
                    "analysis": analysis, "model": None}

        if self._api_key():
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

        reply = self._offline_reply(
            messages, analysis,
            "No ANTHROPIC_API_KEY found, so I answered with the local "
            "deterministic assistant. Set it as an environment variable or "
            "put ANTHROPIC_API_KEY=... in the project's .env file, then "
            "restart the server to chat with the full model.")
        return {"reply": reply, "mode": "offline",
                "analysis": analysis, "model": None}
