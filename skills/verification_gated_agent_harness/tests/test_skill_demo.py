"""Smoke test: the skill demo runs end to end without errors."""

import subprocess
import sys
from pathlib import Path

DEMO = Path(__file__).resolve().parents[1] / "scripts" / "run_skill_demo.py"


def test_demo_runs_clean():
    proc = subprocess.run([sys.executable, str(DEMO)],
                          capture_output=True, text=True, timeout=60)
    assert proc.returncode == 0, proc.stderr
    assert "audit: PASS" in proc.stdout
    assert "high-risk gate: APPROVED" in proc.stdout
