"""tmux adapter: a 4-pane private-mode workspace.

Panes: (0) private REPL, (1) commands log tail, (2) approvals watcher,
(3) backend health. If tmux is not installed the adapter returns a
TMUX_NOT_FOUND status with a plain-terminal fallback command instead of
failing.
"""

from __future__ import annotations

import shlex
import shutil
import subprocess
from pathlib import Path

SESSION_NAME = "surfing_ai_private"


def tmux_available() -> bool:
    return shutil.which("tmux") is not None


def fallback_command() -> str:
    return "python3 scripts/surfing_ai terminal-private"


def pane_commands(root: str | Path = ".", mode: str = "local-only") -> list[tuple[str, str]]:
    root = Path(root)
    cli = "python3 scripts/surfing_ai"
    logs_glob = "reports/surfing_ai_terminal_*"
    return [
        ("repl", f"{cli} terminal-private --mode {mode}"),
        ("log", "sh -c 'while true; do tail -n 20 "
                f"$(ls -dt {logs_glob} 2>/dev/null | head -1)/commands.log "
                "2>/dev/null; sleep 5; clear; done'"),
        ("approvals", f"sh -c 'while true; do {cli} approvals list; "
                      "sleep 10; clear; done'"),
        ("health", f"sh -c '{cli} backend-health; "
                   "echo; echo \"(static snapshot — rerun to refresh)\"; "
                   "exec sh'"),
    ]


def build_tmux_commands(session: str = SESSION_NAME,
                        root: str | Path = ".",
                        mode: str = "local-only") -> list[list[str]]:
    panes = pane_commands(root, mode)
    root = str(Path(root))
    cmds = [
        ["tmux", "new-session", "-d", "-s", session, "-c", root,
         panes[0][1]],
        ["tmux", "split-window", "-h", "-t", f"{session}:0", "-c", root,
         panes[1][1]],
        ["tmux", "split-window", "-v", "-t", f"{session}:0.0", "-c", root,
         panes[2][1]],
        ["tmux", "split-window", "-v", "-t", f"{session}:0.1", "-c", root,
         panes[3][1]],
        ["tmux", "select-pane", "-t", f"{session}:0.0"],
    ]
    return cmds


def build_grid_commands(session: str, root: str | Path, panes: int,
                        mode: str = "local-only") -> list[list[str]]:
    """N-pane tiled grid, one private REPL per pane (max-process)."""
    root = str(Path(root))
    repl = f"python3 scripts/surfing_ai terminal-private --mode {mode}"
    cmds = [["tmux", "new-session", "-d", "-s", session, "-c", root, repl]]
    for _ in range(max(1, panes) - 1):
        cmds.append(["tmux", "split-window", "-t", session, "-c", root,
                     repl])
        cmds.append(["tmux", "select-layout", "-t", session, "tiled"])
    return cmds


def launch_grid(session: str = "surfing_ai_grid", root: str | Path = ".",
                panes: int | None = None, mode: str = "local-only",
                dry_run: bool = False) -> dict:
    """tmux tiled grid with one REPL per pane; TMUX_NOT_FOUND fallback
    returns the manual one-terminal-per-window commands instead."""
    from harness.process_orchestrator import (manual_terminal_commands,
                                              max_processes)
    count = panes or max_processes()
    if not tmux_available():
        return {"status": "TMUX_NOT_FOUND",
                "message": "tmux is not installed; run these manually, "
                           "one per terminal window",
                "panes": count,
                "manual_commands": manual_terminal_commands(count, mode)}

    commands = build_grid_commands(session, root, count, mode)
    if dry_run:
        return {"status": "DRY_RUN", "panes": count,
                "commands": [" ".join(shlex.quote(p) for p in c)
                             for c in commands]}
    for command in commands:
        proc = subprocess.run(command, capture_output=True, text=True)
        if proc.returncode != 0:
            return {"status": "TMUX_ERROR",
                    "command": " ".join(command),
                    "stderr": proc.stderr.strip()[:300],
                    "fallback": fallback_command()}
    return {"status": "LAUNCHED", "session": session, "panes": count,
            "attach_command": f"tmux attach -t {session}"}


def launch(session: str = SESSION_NAME, root: str | Path = ".",
           mode: str = "local-only", attach: bool = True,
           dry_run: bool = False) -> dict:
    if not tmux_available():
        return {"status": "TMUX_NOT_FOUND",
                "message": "tmux is not installed; falling back to the "
                           "plain-terminal REPL",
                "fallback": fallback_command()}

    commands = build_tmux_commands(session, root, mode)
    if dry_run:
        return {"status": "DRY_RUN",
                "commands": [" ".join(shlex.quote(p) for p in c)
                             for c in commands]}

    for command in commands:
        proc = subprocess.run(command, capture_output=True, text=True)
        if proc.returncode != 0:
            return {"status": "TMUX_ERROR",
                    "command": " ".join(command),
                    "stderr": proc.stderr.strip()[:300],
                    "fallback": fallback_command()}
    result = {"status": "LAUNCHED", "session": session, "panes": 4}
    if attach:
        # exec-style attach is left to the caller's terminal; emit the
        # command so non-tty contexts (tests, CI) never hang.
        result["attach_command"] = f"tmux attach -t {session}"
    return result
