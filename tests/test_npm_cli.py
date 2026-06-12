"""npm CLI wrapper tests (node required; every test degrades to a
clean skip-style pass if node is unavailable)."""

import json
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CLI = ROOT / "cli" / "surfing-ai.js"
NODE = shutil.which("node")


def run_cli(*args, input_text=None, timeout=60):
    return subprocess.run([NODE, str(CLI), *args], capture_output=True,
                          text=True, input=input_text, timeout=timeout,
                          cwd=ROOT)


def test_version_matches_package_json():
    if not NODE:
        return
    package = json.loads((ROOT / "package.json").read_text("utf-8"))
    proc = run_cli("--version")
    assert proc.returncode == 0
    assert proc.stdout.strip() == package["version"]


def test_help_lists_concurrency_features():
    if not NODE:
        return
    out = run_cli("--help").stdout
    for needle in ("exec", "par", "Ctrl+T", "max-procs", "desktop"):
        assert needle in out


def test_exec_one_shot():
    if not NODE:
        return
    proc = run_cli("exec", "echo npm-bridge")
    assert proc.returncode == 0
    assert "npm-bridge" in proc.stdout


def test_exec_blocked_command_stays_blocked():
    if not NODE:
        return
    proc = run_cli("exec", "git push origin main")
    assert "BLOCKED" in proc.stdout


def test_par_runs_parallel_workers():
    if not NODE:
        return
    proc = run_cli("par", "echo one", "echo two", timeout=120)
    assert proc.returncode == 0
    assert "one" in proc.stdout and "two" in proc.stdout
    assert "files_sent_external': 0" in proc.stdout


def test_no_tty_refuses_tui():
    if not NODE:
        return
    proc = run_cli()
    assert proc.returncode == 1
    assert "no TTY" in proc.stderr


def test_package_json_bin_and_files():
    package = json.loads((ROOT / "package.json").read_text("utf-8"))
    assert package["bin"]["surfing-ai"] == "cli/surfing-ai.js"
    assert "harness/*.py" in package["files"]
    assert "scripts/surfing_ai" in package["files"]
    first_line = CLI.read_text("utf-8").splitlines()[0]
    assert first_line.startswith("#!/usr/bin/env node")
