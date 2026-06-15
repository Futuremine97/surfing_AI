"""Tests for cowork mode — the long-running proactive agentic loop."""

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from harness import autopilot

CLI = ROOT / "scripts" / "surfing_ai"


def test_start_creates_session_and_journal():
    with tempfile.TemporaryDirectory() as d:
        s = autopilot.start("triage the failing tests", d)
        assert s.state["status"] == "active"
        assert s.dir.is_dir()
        j = s.read_journal()
        assert j and j[0]["type"] == "mission"


def test_playbook_runs_then_monitors():
    with tempfile.TemporaryDirectory() as d:
        s = autopilot.start("review the repo", d)
        n = len(autopilot.PLAYBOOK)
        autopilot.run(s, cycles=n)
        assert s.state["cursor"] == n
        assert s.state["status"] == "monitoring"
        types = {e["type"] for e in s.read_journal()}
        assert "plan" in types and "reflection" in types
        # one more tick → proactive monitor entry
        entry = autopilot.tick(s)
        assert entry["type"] == "monitor"


def test_resumable_across_loads():
    with tempfile.TemporaryDirectory() as d:
        s = autopilot.start("keep an eye on health", d)
        autopilot.run(s, cycles=2)
        step = s.state["step"]
        again = autopilot.load(d, s.sid)          # fresh object, same disk
        assert again.state["step"] == step
        autopilot.run(again, cycles=1)
        assert again.state["step"] == step + 1


def test_risky_shell_is_gated_not_executed():
    with tempfile.TemporaryDirectory() as d:
        s = autopilot.start("x", d)
        rc, msg = s.run_shell("git push origin main")
        assert rc is None                          # blocked
        assert "BLOCKED" in msg
        assert any(e["type"] == "approval_request" for e in s.read_journal())


def test_stop_halts_progress():
    with tempfile.TemporaryDirectory() as d:
        s = autopilot.start("y", d)
        autopilot.stop(s)
        before = s.state["step"]
        autopilot.run(s, cycles=3)
        assert s.state["step"] == before          # no progress after stop


def test_cross_process_session():
    """Start in one CLI process; advance + inspect in separate ones."""
    with tempfile.TemporaryDirectory() as d:
        env = dict(os.environ)
        start = subprocess.run(
            [sys.executable, str(CLI), "cowork", "start",
             "audit the build", "--root", d],
            capture_output=True, text=True, timeout=30, env=env)
        assert start.returncode == 0, start.stderr
        sid = start.stdout.split()[2]             # "cowork session <id> ..."

        run = subprocess.run(
            [sys.executable, str(CLI), "cowork", "run", "-s", sid,
             "-c", "4", "--root", d],
            capture_output=True, text=True, timeout=30, env=env)
        assert run.returncode == 0, run.stderr
        assert "#1" in run.stdout

        st = subprocess.run(
            [sys.executable, str(CLI), "cowork", "status", "-s", sid,
             "--root", d],
            capture_output=True, text=True, timeout=30, env=env)
        data = json.loads(st.stdout)
        assert data["session"] == sid and data["step"] >= 4


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
