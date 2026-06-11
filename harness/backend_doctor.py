"""Backend doctor: find every AI agent CLI, its auth state, and how to
connect it — fast checks only (file probes + --version style commands),
never a slow model call.

For each backend we report: binary path, version, whether credentials
exist, which API-key env var applies, and the exact login command. The
web UI can then launch that login in a terminal with one click.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import asdict, dataclass, field
from pathlib import Path

PROBE_TIMEOUT = 10


@dataclass
class BackendStatus:
    backend: str
    label: str
    binary: str
    path: str = ""
    version: str = ""
    installed: bool = False
    authenticated: bool | None = None   # None = unknown
    auth_detail: str = ""
    key_env: str = ""
    key_present: bool = False
    login_command: str = ""
    install_command: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


def _run(cmd: list[str], timeout: int = PROBE_TIMEOUT) -> tuple[int, str]:
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True,
                              timeout=timeout)
        return proc.returncode, (proc.stdout + proc.stderr).strip()
    except (OSError, subprocess.TimeoutExpired) as exc:
        return -1, str(exc)


def _version(cli: str) -> str:
    code, out = _run([cli, "--version"])
    return out.splitlines()[0][:80] if code == 0 and out else ""


def _env_key(name: str, project_root: Path) -> bool:
    if os.environ.get(name):
        return True
    env_file = project_root / ".env"
    if env_file.is_file():
        for line in env_file.read_text(encoding="utf-8",
                                       errors="ignore").splitlines():
            if line.strip().startswith(name + "="):
                return bool(line.split("=", 1)[1].strip())
    return False


def diagnose(home: str | Path | None = None,
             project_root: str | Path = ".") -> list[dict]:
    home = Path(home) if home else Path.home()
    project_root = Path(project_root)
    statuses: list[BackendStatus] = []

    # ---- Claude Code ----------------------------------------------------
    claude = BackendStatus(
        backend="claude", label="Claude Code", binary="claude",
        key_env="ANTHROPIC_API_KEY",
        login_command="claude /login",
        install_command="npm install -g @anthropic-ai/claude-code")
    claude.path = shutil.which("claude") or ""
    claude.installed = bool(claude.path)
    if claude.installed:
        claude.version = _version(claude.path)
        creds = home / ".claude" / ".credentials.json"
        if creds.is_file():
            claude.authenticated = True
            claude.auth_detail = f"credentials file: {creds}"
        else:
            # macOS stores OAuth in the Keychain; file absence is not
            # conclusive, so probe cheaply.
            claude.authenticated = None
            claude.auth_detail = ("no credentials file found (may use "
                                  "Keychain); run the login if chat fails")
    claude.key_present = _env_key("ANTHROPIC_API_KEY", project_root)
    statuses.append(claude)

    # ---- Codex ----------------------------------------------------------
    codex = BackendStatus(
        backend="codex", label="Codex (ChatGPT)", binary="codex",
        key_env="OPENAI_API_KEY",
        login_command="codex login",
        install_command="npm install -g @openai/codex")
    codex.path = shutil.which("codex") or ""
    codex.installed = bool(codex.path)
    if codex.installed:
        codex.version = _version(codex.path)
        code, out = _run([codex.path, "login", "status"])
        codex.authenticated = code == 0
        codex.auth_detail = out[:200]
    codex.key_present = _env_key("OPENAI_API_KEY", project_root)
    statuses.append(codex)

    # ---- Gemini / Antigravity -------------------------------------------
    gemini = BackendStatus(
        backend="gemini", label="Gemini (Antigravity)", binary="gemini",
        key_env="GEMINI_API_KEY",
        login_command="gemini",
        install_command="npm install -g @google/gemini-cli")
    gemini.path = shutil.which("gemini") or shutil.which("antigravity") or ""
    gemini.installed = bool(gemini.path)
    if gemini.installed:
        gemini.version = _version(gemini.path)
        oauth = home / ".gemini" / "oauth_creds.json"
        gemini.authenticated = oauth.is_file() or None
        gemini.auth_detail = (f"oauth file: {oauth}" if oauth.is_file()
                              else "no oauth file; first run opens login")
    gemini.key_present = (_env_key("GEMINI_API_KEY", project_root)
                          or _env_key("GOOGLE_API_KEY", project_root))
    statuses.append(gemini)

    return [s.to_dict() for s in statuses]


LOGIN_COMMANDS = {
    "claude": "claude /login",
    "codex": "codex login",
    "gemini": "gemini",
}


def launch_login(backend: str) -> dict:
    """Open a terminal running the backend's login flow (macOS/Linux).
    Commands are fixed strings — no user input reaches the shell."""
    command = LOGIN_COMMANDS.get(backend)
    if not command:
        raise ValueError(f"unknown backend: {backend}")
    import platform
    system = platform.system()
    if system == "Darwin":
        script = f'tell application "Terminal" to do script "{command}"'
        code, out = _run(["osascript", "-e", script,
                          "-e", 'tell application "Terminal" to activate'],
                         timeout=15)
        if code != 0:
            raise ValueError(f"could not open Terminal: {out[:200]}")
        return {"launched": command, "terminal": "Terminal.app"}
    if system == "Linux":
        for term in ("x-terminal-emulator", "gnome-terminal", "konsole",
                     "xterm"):
            if shutil.which(term):
                subprocess.Popen([term, "-e", command])
                return {"launched": command, "terminal": term}
        raise ValueError(f"no terminal emulator found; run manually: {command}")
    raise ValueError(f"unsupported platform {system}; run manually: {command}")
