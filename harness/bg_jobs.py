"""Background jobs that persist across shell / CLI calls.

Each `surfing_ai exec` (and most CLI calls) spawns a fresh, short-lived
process, so a command started inside one call dies with it. This module
launches long-running commands *detached* — in their own process session
(`setsid`) with output redirected to a log file — and records them in a
JSON registry on disk. A later, unrelated CLI call reads the same registry
to list, inspect, stop, or tail those jobs.

Safety: every command is scanned by `safety_barrier.scan_command` before
launch, so destructive / publishing patterns are refused exactly as in the
private-mode REPL. Jobs run under the project root.
"""

from __future__ import annotations

import json
import os
import shlex
import signal
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from uuid import uuid4

from harness.terminal_private_mode import check_command

REGISTRY = "bg_jobs.json"
LOG_DIR = "bg_logs"

IS_WINDOWS = os.name == "nt"


@dataclass
class Job:
    id: str
    command: str
    pid: int
    status: str             # running | exited | stopped | blocked | ended
    started_at: float
    log: str
    ended_at: float | None = None
    returncode: int | None = None
    reasons: list[str] = field(default_factory=list)
    alternative: str = ""
    boot_id: str = ""        # OS boot when launched; reboot ⇒ process gone

    def to_dict(self) -> dict:
        return self.__dict__.copy()


# ---------------------------------------------------------------- store

def _paths(root: str | Path) -> tuple[Path, Path]:
    root = Path(root)
    return root / REGISTRY, (root / LOG_DIR)


def _read(root: str | Path) -> list[dict]:
    reg, _ = _paths(root)
    try:
        return json.loads(reg.read_text())
    except Exception:
        return []


def _write(root: str | Path, records: list[dict]) -> None:
    reg, _ = _paths(root)
    reg.parent.mkdir(parents=True, exist_ok=True)
    reg.write_text(json.dumps(records, indent=2) + "\n", encoding="utf-8")


# ---------------------------------------------------------------- liveness

def _alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if IS_WINDOWS:  # best-effort without psutil
        out = subprocess.run(["tasklist", "/FI", f"PID eq {pid}"],
                             capture_output=True, text=True)
        return str(pid) in out.stdout
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _refresh(root: str | Path) -> list[dict]:
    """Update statuses from the OS and captured return codes; persist."""
    from harness.system_identity import rebooted_since
    _, logdir = _paths(root)
    records = _read(root)
    changed = False
    for rec in records:
        if rec.get("status") != "running":
            continue
        # reboot wins over PID liveness: after a reboot the PID may be
        # reused by an unrelated process, so never trust _alive() then.
        if rebooted_since(rec.get("boot_id")):
            rc_file = logdir / f"{rec['id']}.rc"
            rc = None
            try:
                rc = int(rc_file.read_text().strip())
            except Exception:
                pass
            rec["status"] = "ended"
            rec["returncode"] = rc
            rec["ended_at"] = time.time()
            rec.setdefault("reasons", []).append("machine rebooted")
            changed = True
            continue
        if _alive(rec["pid"]):
            continue
        # process is gone — read the captured return code if present
        rc_file = logdir / f"{rec['id']}.rc"
        rc = None
        try:
            rc = int(rc_file.read_text().strip())
        except Exception:
            pass
        rec["status"] = "exited"
        rec["returncode"] = rc
        rec["ended_at"] = time.time()
        changed = True
    if changed:
        _write(root, records)
    return records


# ---------------------------------------------------------------- actions

def _spawn_daemon(command: str, root: str | Path, log_path: Path,
                  rc_path: Path) -> int:
    """POSIX double-fork so the job is reparented to init and never becomes
    a zombie of this (possibly long-lived) process. Returns the job PID.

    The job stays in its own session/process group, so `stop()` can signal
    the whole group. A shell wrapper records the exit code to `rc_path`.
    """
    r, w = os.pipe()
    pid1 = os.fork()
    if pid1 == 0:                       # ---- first child ----
        os.close(r)
        os.setsid()                     # new session: detach from terminal
        pid2 = os.fork()
        if pid2 > 0:                    # first child reports grandchild pid
            os.write(w, str(pid2).encode())
            os.close(w)
            os._exit(0)
        # ---- grandchild: supervise the real job, capture its exit code ----
        os.close(w)
        out = os.open(str(log_path),
                      os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o644)
        os.dup2(out, 1)
        os.dup2(out, 2)
        nul = os.open(os.devnull, os.O_RDONLY)
        os.dup2(nul, 0)
        try:
            os.chdir(str(root))
        except OSError:
            pass
        # run as a direct argv (no shell) so the command is not re-parsed;
        # the child inherits this session/group, so stop() reaches it.
        rc = 127
        try:
            child = subprocess.Popen(shlex.split(command))
            rc = child.wait()
        except Exception:
            rc = 127
        try:
            Path(rc_path).write_text(str(rc))
        except Exception:
            pass
        os._exit(0)
    # ---- parent ----
    os.close(w)
    os.waitpid(pid1, 0)                 # reap the short-lived first child
    data = os.read(r, 32)
    os.close(r)
    return int(data or b"-1")


def start(command: str, root: str | Path) -> Job:
    command = command.strip()
    if not command:
        raise ValueError("command is required")
    root = Path(root)
    decision = check_command(command)   # same allowlist as private-mode REPL
    job_id = uuid4().hex[:8]
    _, logdir = _paths(root)
    logdir.mkdir(parents=True, exist_ok=True)
    log_path = logdir / f"{job_id}.log"

    if not decision.allowed:
        job = Job(id=job_id, command=command, pid=-1, status="blocked",
                  started_at=time.time(), log=str(log_path),
                  reasons=[decision.reason], alternative=decision.alternative)
        records = _read(root)
        records.append(job.to_dict())
        _write(root, records)
        return job

    rc_path = logdir / f"{job_id}.rc"
    if IS_WINDOWS:
        log_fh = open(log_path, "wb")
        proc = subprocess.Popen(
            ["cmd", "/c", f"{command} & echo %ERRORLEVEL% > "
             f"\"{rc_path}\""],
            cwd=str(root), stdout=log_fh,
            stderr=subprocess.STDOUT,
            creationflags=getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
            | getattr(subprocess, "DETACHED_PROCESS", 0))
        log_fh.close()
        pid = proc.pid
    else:
        pid = _spawn_daemon(command, root, log_path, rc_path)

    from harness.system_identity import boot_id
    job = Job(id=job_id, command=command, pid=pid, status="running",
              started_at=time.time(), log=str(log_path),
              boot_id=boot_id())
    records = _read(root)
    records.append(job.to_dict())
    _write(root, records)
    return job


def list_jobs(root: str | Path) -> list[dict]:
    return _refresh(root)


def get(root: str | Path, job_id: str) -> dict | None:
    for rec in _refresh(root):
        if rec["id"] == job_id:
            return rec
    return None


def stop(root: str | Path, job_id: str) -> dict:
    rec = get(root, job_id)
    if rec is None:
        raise KeyError(f"no such job: {job_id}")
    if rec["status"] == "running" and _alive(rec["pid"]):
        try:
            if IS_WINDOWS:
                subprocess.run(["taskkill", "/PID", str(rec["pid"]),
                                "/T", "/F"], capture_output=True)
            else:
                os.killpg(os.getpgid(rec["pid"]), signal.SIGTERM)
                for _ in range(20):
                    if not _alive(rec["pid"]):
                        break
                    time.sleep(0.05)
                if _alive(rec["pid"]):
                    os.killpg(os.getpgid(rec["pid"]), signal.SIGKILL)
        except ProcessLookupError:
            pass
    records = _read(root)
    for r in records:
        if r["id"] == job_id:
            r["status"] = "stopped"
            r["ended_at"] = time.time()
    _write(root, records)
    return get(root, job_id)


def logs(root: str | Path, job_id: str, tail: int = 40) -> str:
    rec = get(root, job_id)
    if rec is None:
        raise KeyError(f"no such job: {job_id}")
    try:
        lines = Path(rec["log"]).read_text(errors="replace").splitlines()
    except FileNotFoundError:
        return "(no output yet)"
    return "\n".join(lines[-tail:]) if tail else "\n".join(lines)


def prune(root: str | Path) -> int:
    """Drop finished/stopped/blocked jobs from the registry; keep logs."""
    records = _refresh(root)
    keep = [r for r in records if r["status"] == "running"]
    removed = len(records) - len(keep)
    _write(root, keep)
    return removed


# ---------------------------------------------------------------- render

def format_table(root: str | Path) -> str:
    records = _refresh(root)
    if not records:
        return "no background jobs"
    icon = {"running": "●", "exited": "✓", "stopped": "■", "blocked": "⨯",
            "ended": "⏹"}
    rows = ["  id        state     pid     command",
            "  --------  --------  ------  -----------------------------"]
    for r in records:
        rc = "" if r.get("returncode") is None else f" rc={r['returncode']}"
        state = f"{icon.get(r['status'], '?')} {r['status']}{rc}"
        pid = r["pid"] if r["pid"] > 0 else "-"
        cmd = r["command"]
        cmd = cmd if len(cmd) <= 40 else cmd[:37] + "..."
        rows.append(f"  {r['id']:<8}  {state:<14}  {str(pid):<6}  {cmd}")
    return "\n".join(rows)
