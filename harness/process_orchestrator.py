"""Maximum-process orchestration.

One feature, three frontends:
- desktop app  -> bridge endpoint spawns up to max_processes() sessions
- tmux         -> tiled grid with one private REPL per pane
- plain terminal -> headless ParallelRunner fans commands out across
  N PrivateTerminal workers (or prints the manual commands)

Every worker is a full PrivateTerminal, so the allowlist, file guard,
redaction, and audit invariants hold identically at any parallelism.
Each worker gets its own audit directory (tagged) so logs never mix.
"""

from __future__ import annotations

import os
import threading
from pathlib import Path

from harness.audit_log import AuditSession
from harness.terminal_private_mode import DEFAULT_MODE, PrivateTerminal


def max_processes(reserve: int = 1) -> int:
    """CPU-bound parallel session budget: cores minus a reserve for the
    UI/bridge itself, never below 1."""
    cores = os.cpu_count() or 2
    return max(1, cores - max(0, reserve))


class ParallelRunner:
    """N private-terminal workers executing a command list in parallel.

    Commands are distributed round-robin; each worker runs its share
    sequentially on its own thread, so a single PrivateTerminal is
    never used concurrently.
    """

    def __init__(self, root: str | Path = ".", mode: str = DEFAULT_MODE,
                 workers: int | None = None):
        self.workers = max(1, workers or max_processes())
        self.root = Path(root)
        self.terminals = [
            PrivateTerminal(
                root=self.root, mode=mode,
                audit=AuditSession(self.root, mode=mode, tag=f"w{i}"),
                input_fn=lambda prompt="": "",   # approvals default to N
                output_fn=lambda *a, **k: None)
            for i in range(self.workers)]
        self.closed = False

    def run(self, commands: list[str]) -> list[dict]:
        buckets: list[list[tuple[int, str]]] = [[] for _ in
                                                range(self.workers)]
        for index, command in enumerate(commands):
            buckets[index % self.workers].append((index, command))

        results: list[dict | None] = [None] * len(commands)

        def work(worker_index: int) -> None:
            terminal = self.terminals[worker_index]
            for index, command in buckets[worker_index]:
                output = terminal.handle(command)
                results[index] = {
                    "index": index,
                    "worker": worker_index,
                    "command": command,
                    "blocked": str(output).startswith("BLOCKED"),
                    "output": str(output),
                }

        threads = [threading.Thread(target=work, args=(i,), daemon=True)
                   for i in range(self.workers)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        return [r for r in results if r is not None]

    def aggregate_counters(self) -> dict:
        total = {"external_backend_calls": 0, "mcp_calls": 0,
                 "blocked_commands": 0, "files_sent_external": 0}
        for terminal in self.terminals:
            counters = terminal.audit.counters
            total["external_backend_calls"] += counters.external_backend_calls
            total["mcp_calls"] += counters.mcp_calls
            total["blocked_commands"] += counters.blocked_commands
            total["files_sent_external"] += counters.files_sent_external
        return total

    def close(self) -> list[Path]:
        if self.closed:
            return []
        self.closed = True
        return [terminal.close() for terminal in self.terminals]


def manual_terminal_commands(panes: int | None = None,
                             mode: str = DEFAULT_MODE) -> list[str]:
    """What to run by hand, one per terminal window, when neither the
    desktop app nor tmux is available."""
    count = panes or max_processes()
    return [f"python3 scripts/surfing_ai terminal-private --mode {mode}"
            for _ in range(count)]
