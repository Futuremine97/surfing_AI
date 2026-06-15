"""Tests for persistent background jobs (survive across CLI/shell calls)."""

import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from harness import bg_jobs

CLI = ROOT / "scripts" / "surfing_ai"


# allowlisted long-runner: python3 is on the private-mode allowlist and the
# -c body has no shell metacharacters (no ; | & $ etc.). Inner quotes are
# kept so shlex.split yields the code as a single argv element.
SLEEP = 'python3 -c "__import__(\'time\').sleep(30)"'


def test_start_quick_job_then_exits():
    with tempfile.TemporaryDirectory() as d:
        job = bg_jobs.start("echo hi", d)
        assert job.status == "running" and job.pid > 0
        for _ in range(40):
            rec = bg_jobs.get(d, job.id)
            if rec["status"] != "running":
                break
            time.sleep(0.05)
        rec = bg_jobs.get(d, job.id)
        assert rec["status"] == "exited"
        assert rec["returncode"] == 0
        assert "hi" in bg_jobs.logs(d, job.id)


def test_blocked_command_is_not_launched():
    with tempfile.TemporaryDirectory() as d:
        for cmd in ("git push origin main", "rm -rf /", "scp f host:/"):
            job = bg_jobs.start(cmd, d)
            assert job.status == "blocked", cmd
            assert job.pid == -1
            assert job.reasons


def test_stop_long_job():
    with tempfile.TemporaryDirectory() as d:
        job = bg_jobs.start(SLEEP, d)
        assert job.status == "running"
        assert bg_jobs._alive(job.pid)
        rec = bg_jobs.stop(d, job.id)
        assert rec["status"] == "stopped"
        time.sleep(0.2)
        assert not bg_jobs._alive(job.pid)


def test_prune_keeps_only_running():
    with tempfile.TemporaryDirectory() as d:
        a = bg_jobs.start("echo done", d)
        b = bg_jobs.start(SLEEP, d)
        time.sleep(0.3)
        bg_jobs.list_jobs(d)
        removed = bg_jobs.prune(d)
        assert removed >= 1
        ids = {r["id"] for r in bg_jobs.list_jobs(d)}
        assert b.id in ids and a.id not in ids
        bg_jobs.stop(d, b.id)


def test_persists_across_separate_cli_processes():
    """The real requirement: a job started by one CLI call is visible to a
    *different* CLI invocation, and can be stopped from there."""
    with tempfile.TemporaryDirectory() as d:
        env = dict(os.environ)
        start = subprocess.run(
            [sys.executable, str(CLI), "bg", "start", SLEEP,
             "--root", d], capture_output=True, text=True, timeout=20)
        assert start.returncode == 0, start.stderr
        # e.g. "started ab12cd34  pid 12345"
        job_id = start.stdout.split()[1]

        listed = subprocess.run(
            [sys.executable, str(CLI), "bg", "list", "--root", d],
            capture_output=True, text=True, timeout=20)
        assert job_id in listed.stdout
        assert "running" in listed.stdout

        stopped = subprocess.run(
            [sys.executable, str(CLI), "bg", "stop", job_id, "--root", d],
            capture_output=True, text=True, timeout=20)
        assert "stopped" in stopped.stdout
        time.sleep(0.2)
        rec = bg_jobs.get(d, job_id)
        assert rec["status"] == "stopped"


if __name__ == "__main__":
    import traceback
    fns = [v for k, v in dict(globals()).items() if k.startswith("test_")]
    p = 0
    for fn in fns:
        try:
            fn(); p += 1; print("PASS", fn.__name__)
        except Exception:
            print("FAIL", fn.__name__); traceback.print_exc()
    print(f"{p}/{len(fns)} passed")
