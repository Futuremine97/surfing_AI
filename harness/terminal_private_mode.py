"""Terminal private mode: a REPL for working on private material with
hard guarantees about what can leave the machine.

Modes (three):
- ``local-only`` (default): allowlisted shell commands only; every
  external backend / MCP call is refused outright.
- ``redacted-external``: an external prompt may be sent, but only after
  (1) redaction, (2) a written preview, (3) an explicit ``y`` approval
  (default is No). File contents are never sent in any mode.
- ``audit``: nothing executes; every action is logged as a dry-run plan.

Security invariants enforced here:
- external backends / MCP default OFF; calls possible only in
  redacted-external after preview + explicit approval
- raw file contents are never transmitted -> files_sent_external == 0
- command execution is allowlist-only; destructive / publishing
  patterns are BLOCKED with a reason and an alternative
- the file access guard works independently of .gitignore
- an audit trail is always written; secret values appear in no output
"""

from __future__ import annotations

import re
import shlex
import subprocess
from pathlib import Path

from harness.approval_queue import ApprovalQueue
from harness.audit_log import AuditSession
from harness.backend_health import format_health, summarize_health
from harness.file_access_guard import FileAccessGuard
from harness.safety_barrier import scan_command

MODES = ("local-only", "redacted-external", "audit")
DEFAULT_MODE = "local-only"

EXEC_TIMEOUT = 120

# ---- command policy --------------------------------------------------------

# (regex, reason, alternative) — checked before everything else so the
# user gets a specific reason, not just "not in allowlist".
BLOCKED_COMMAND_PATTERNS = [
    (re.compile(r"\brm\s+-[a-zA-Z]*[rf][a-zA-Z]*\s"),
     "recursive/forced delete",
     "delete one named file at a time, or move it to a trash folder"),
    (re.compile(r"\bgit\s+push\b"),
     "push publishes content outside this machine",
     "review with 'git log' here; push manually outside private mode"),
    (re.compile(r"\bgit\s+add\s+(-A\b|--all\b|\.(\s|$))"),
     "bulk staging can pick up private files",
     "stage explicitly: git add <specific-file>"),
    (re.compile(r"\b(scp|sftp|ftp)\b|\brsync\b[^\n]*\s\S+:"),
     "network file copy sends files off-machine",
     "keep files local; export through the release guard pipeline"),
    (re.compile(r"\bmkfs(\.|\s)|\bdd\b[^\n]*\bof=/dev/"),
     "disk formatting / raw device write",
     "none — never needed in a working session"),
    (re.compile(r"\bsudo\b"),
     "privilege escalation",
     "run the underlying command without sudo if it is allowlisted"),
    (re.compile(r"\b(curl|wget)\b[^\n]*\|\s*(sh|bash|zsh)\b"),
     "piping a download into a shell",
     "download, read the script, then run it explicitly"),
]

SHELL_METACHARACTERS = re.compile(r"[|;&`$<>]")

# First token (or 'git <subcommand>') must be on this list.
ALLOWLIST = {
    "ls", "pwd", "cat", "head", "tail", "wc", "grep", "rg", "find",
    "echo", "which", "file", "stat", "du", "df", "date", "uname",
    "python", "python3", "pytest", "diff", "sort", "uniq", "tree",
}
GIT_SUBCOMMAND_ALLOWLIST = {"status", "diff", "log", "show", "branch"}

# Commands whose file arguments must pass the file access guard.
READ_COMMANDS = {"cat", "head", "tail", "grep", "rg", "wc", "diff",
                 "sort", "uniq", "file", "stat"}


class PolicyDecision:
    def __init__(self, allowed: bool, reason: str = "",
                 alternative: str = ""):
        self.allowed = allowed
        self.reason = reason
        self.alternative = alternative


def check_command(command: str,
                  guard: FileAccessGuard | None = None) -> PolicyDecision:
    """Allowlist policy: specific blocked patterns first, then shell
    metacharacters, then the allowlist, then safety_barrier, then the
    file access guard on read targets."""
    stripped = command.strip()
    if not stripped:
        return PolicyDecision(False, "empty command", "type :help")

    for pattern, reason, alternative in BLOCKED_COMMAND_PATTERNS:
        if pattern.search(stripped + " "):
            return PolicyDecision(False, reason, alternative)

    if SHELL_METACHARACTERS.search(stripped):
        return PolicyDecision(
            False, "shell metacharacters are not allowed in private mode",
            "run commands one at a time without pipes/redirection")

    try:
        tokens = shlex.split(stripped)
    except ValueError as exc:
        return PolicyDecision(False, f"unparseable command: {exc}",
                              "fix the quoting and retry")

    head = tokens[0]
    if head == "git":
        if len(tokens) < 2 or tokens[1] not in GIT_SUBCOMMAND_ALLOWLIST:
            sub = tokens[1] if len(tokens) > 1 else "(none)"
            return PolicyDecision(
                False, f"git subcommand '{sub}' is not allowlisted",
                f"allowed: git {', git '.join(sorted(GIT_SUBCOMMAND_ALLOWLIST))}")
    elif head not in ALLOWLIST:
        return PolicyDecision(
            False, f"'{head}' is not on the private-mode allowlist",
            "see :help for the allowlist; ask for an addition if needed")

    scan = scan_command(stripped)
    if scan.blocked:
        return PolicyDecision(False,
                              "; ".join(scan.reasons) or "safety barrier",
                              "use a narrower, explicit command")

    if guard is not None and head in READ_COMMANDS:
        for arg in tokens[1:]:
            if arg.startswith("-"):
                continue
            decision = guard.check(arg)
            if not decision.allowed:
                return PolicyDecision(
                    False, f"file access denied: {decision.reason}",
                    "private paths stay local; work on a copy outside "
                    "the deny list if it is safe to do so")
    return PolicyDecision(True)


# ---- redaction -------------------------------------------------------------

REDACTION_PATTERNS = [
    (re.compile(r"sk-[A-Za-z0-9_-]{8,}"), "[REDACTED:api-key]"),
    (re.compile(r"AKIA[0-9A-Z]{12,}"), "[REDACTED:aws-key]"),
    (re.compile(r"ghp_[A-Za-z0-9]{20,}"), "[REDACTED:github-token]"),
    (re.compile(r"xox[baprs]-[A-Za-z0-9-]{10,}"), "[REDACTED:slack-token]"),
    (re.compile(r"AIza[0-9A-Za-z_-]{30,}"), "[REDACTED:google-key]"),
    (re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._\-]{10,}"),
     "Bearer [REDACTED:token]"),
    (re.compile(r"(?i)\b([a-z0-9_]*(?:api[_-]?key|token|secret|password|"
                r"passwd|credential)s?)\s*[=:]\s*\S+"),
     r"\1=[REDACTED]"),
]


def redact(text: str) -> str:
    for pattern, replacement in REDACTION_PATTERNS:
        text = pattern.sub(replacement, text)
    return text


def build_external_preview(backend: str, redacted_prompt: str) -> str:
    return "\n".join([
        "EXTERNAL PROMPT PREVIEW (exactly this text would be sent)",
        f"backend: {backend}",
        f"prompt_chars: {len(redacted_prompt)}",
        "files_sent: 0 (file contents are never transmitted)",
        "---",
        redacted_prompt,
        "---",
    ])


# ---- REPL ------------------------------------------------------------------

HELP = """\
terminal private mode — commands
  :mode                show current mode
  :mode <name>         switch mode (local-only | redacted-external | audit)
  :read <path>         read a file locally (file access guard applies)
  :ask <backend> <prompt>
                       external prompt; redacted-external mode only,
                       preview + explicit y approval (default N)
  :health              backend health (safe vocabulary only)
  :approvals           list pending approval requests
  :help                this text
  :quit                end session and write summary
Shell commands are allowlist-only: """ + ", ".join(sorted(ALLOWLIST)) + (
    "; git " + "/".join(sorted(GIT_SUBCOMMAND_ALLOWLIST)))

QUIT = object()  # sentinel returned by handle() on :quit


class PrivateTerminal:
    def __init__(self, root: str | Path = ".", mode: str = DEFAULT_MODE,
                 audit: AuditSession | None = None,
                 queue: ApprovalQueue | None = None,
                 backend_caller=None, input_fn=input, output_fn=print):
        if mode not in MODES:
            raise ValueError(f"unknown mode '{mode}'; choose from {MODES}")
        self.root = Path(root)
        self.mode = mode
        self.guard = FileAccessGuard(self.root)
        self.audit = audit or AuditSession(self.root, mode=mode)
        self.queue = queue or ApprovalQueue(
            self.audit.dir / "approvals_queue.jsonl")
        # callable(backend, redacted_prompt) -> str; never receives files
        self.backend_caller = backend_caller
        self.input_fn = input_fn
        self.output_fn = output_fn
        self.closed = False

    # ---- pieces ----------------------------------------------------------

    def _blocked(self, command: str, decision: PolicyDecision) -> str:
        self.audit.log_blocked(command, decision.reason)
        return (f"BLOCKED: {decision.reason}\n"
                f"alternative: {decision.alternative}")

    def run_shell(self, command: str) -> str:
        decision = check_command(command, guard=self.guard)
        if not decision.allowed:
            return self._blocked(command, decision)
        if self.mode == "audit":
            self.audit.log_command(command, returncode=None)
            return f"DRY-RUN (audit mode, not executed): {command}"
        try:
            proc = subprocess.run(
                shlex.split(command), cwd=self.root, capture_output=True,
                text=True, timeout=EXEC_TIMEOUT)
        except (OSError, subprocess.TimeoutExpired) as exc:
            self.audit.log_command(command, returncode=-1)
            return f"command failed to run: {exc}"
        self.audit.log_command(command, returncode=proc.returncode)
        return redact((proc.stdout + proc.stderr).strip())

    def read_file(self, target: str) -> str:
        decision = self.guard.check(target)
        if not decision.allowed:
            self.audit.log_blocked(f":read {target}", decision.reason)
            return (f"BLOCKED: {decision.reason}\n"
                    "alternative: private paths are readable only outside "
                    "this harness, by you directly")
        path = (self.root / target if not Path(target).is_absolute()
                else Path(target))
        if not path.is_file():
            return f"not a file: {decision.path}"
        self.audit.log_tool_call("read_local", {"path": decision.path})
        return path.read_text(encoding="utf-8", errors="replace")

    def ask_external(self, backend: str, prompt: str) -> str:
        if self.mode != "redacted-external":
            self.audit.log_blocked(f":ask {backend}",
                                   f"external OFF in {self.mode} mode")
            return (f"BLOCKED: external backends are OFF in '{self.mode}' "
                    "mode\nalternative: switch with ':mode "
                    "redacted-external' (preview + approval still apply)")

        redacted_prompt = redact(prompt)
        preview = build_external_preview(backend, redacted_prompt)
        preview_path = self.audit.save_preview(f"{backend}", preview)
        request = self.queue.request(
            "external_prompt", f"{backend}: {redacted_prompt[:60]}",
            {"preview": str(preview_path)})
        self.output_fn(preview)

        answer = (self.input_fn(f"send to {backend}? [y/N] ") or "").strip()
        approved = answer.lower() == "y"
        record = {"id": request["id"], "backend": backend,
                  "approved": approved}
        if not approved:
            self.queue.deny(request["id"], "user declined (default N)")
            self.audit.log_approval({**record, "status": "denied"})
            return "not sent (approval denied; default is N)"

        self.queue.approve(request["id"])
        self.audit.log_approval({**record, "status": "approved"})
        self.audit.log_external_call(backend, len(redacted_prompt),
                                     files_sent=0)
        if self.backend_caller is None:
            return ("approved — no backend caller configured; "
                    "prompt logged, nothing transmitted")
        response = self.backend_caller(backend, redacted_prompt)
        return redact(str(response))

    # ---- dispatch --------------------------------------------------------

    def handle(self, line: str):
        line = line.strip()
        if not line:
            return ""
        if not line.startswith(":"):
            return self.run_shell(line)

        parts = line.split(None, 2)
        command = parts[0]
        if command == ":quit":
            return QUIT
        if command == ":help":
            return HELP
        if command == ":mode":
            if len(parts) == 1:
                return f"mode: {self.mode}"
            new_mode = parts[1]
            if new_mode not in MODES:
                return f"unknown mode '{new_mode}'; choose from {MODES}"
            self.mode = new_mode
            self.audit.log_tool_call("mode_switch", {"mode": new_mode})
            return f"mode: {self.mode}"
        if command == ":read":
            if len(parts) < 2:
                return "usage: :read <path>"
            return self.read_file(parts[1])
        if command == ":ask":
            if len(parts) < 3:
                return "usage: :ask <backend> <prompt>"
            return self.ask_external(parts[1], parts[2])
        if command == ":health":
            rows = summarize_health(project_root=str(self.root))
            self.audit.save_backend_health({"rows": rows})
            return format_health(rows)
        if command == ":approvals":
            pending = self.queue.pending()
            if not pending:
                return "no pending approvals"
            return "\n".join(f"#{r['id']} [{r['kind']}] {r['label']}"
                             for r in pending)
        return f"unknown command {command}; type :help"

    def close(self) -> Path:
        if not self.closed:
            self.closed = True
            return self.audit.finalize()
        return self.audit.dir / "summary.md"


def run_repl(root: str | Path = ".", mode: str = DEFAULT_MODE,
             input_fn=input, output_fn=print, backend_caller=None) -> Path:
    terminal = PrivateTerminal(root=root, mode=mode, input_fn=input_fn,
                               output_fn=output_fn,
                               backend_caller=backend_caller)
    output_fn(f"surfing_ai terminal private mode — mode={mode} "
              f"(type :help, :quit to end)")
    output_fn(f"audit: {terminal.audit.dir}")
    try:
        while True:
            try:
                line = input_fn("private> ")
            except (EOFError, KeyboardInterrupt):
                break
            result = terminal.handle(line)
            if result is QUIT:
                break
            if result:
                output_fn(result)
    finally:
        summary = terminal.close()
        output_fn(f"summary written: {summary}")
    return summary
