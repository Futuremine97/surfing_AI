#!/usr/bin/env python3
"""Experiment harness for the surfing-ai reverse-question driver.

Runs scripted answer scenarios through ask.resolve() and checks that the
assembled command matches the expectation. Prints a table and exits non-zero
on any mismatch.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from ask import load_spec, resolve  # noqa: E402

# (name, command_key, answers, expected_command)
SCENARIOS = [
    (
        "cmux / defaults",
        "cmux",
        {"mode": {"value": "local-only"},
         "tab_plan": {"value": "multi"}, "use_par": {"value": "yes"}},
        "surfing-ai",
    ),
    (
        "cmux / redacted-external",
        "cmux",
        {"mode": {"value": "redacted-external"}},
        "surfing-ai --mode redacted-external",
    ),
    (
        "exec / git status preset",
        "exec",
        {"command_string": {"value": "git status"}},
        'surfing-ai exec "git status"',
    ),
    (
        "exec / custom input",
        "exec",
        {"command_string": {"value": "custom",
                            "inputs": {"command_string": "python3 -V"}}},
        'surfing-ai exec "python3 -V"',
    ),
    (
        "par / custom list",
        "par",
        {"command_list": {"value": "custom",
                          "inputs": {"command_list": '"git status" "ls -la"'}}},
        'surfing-ai par "git status" "ls -la"',
    ),
    (
        "terminal-private / audit + custom root",
        "terminal-private",
        {"mode": {"value": "audit"},
         "root": {"value": "custom", "inputs": {"root": "/tmp/work"}}},
        "surfing-ai terminal-private --mode audit --root /tmp/work",
    ),
    (
        "tmux-private / defaults",
        "tmux-private",
        {"mode": {"value": "local-only"}, "root": {"value": "default"},
         "dry_run": {"value": "no"}},
        "surfing-ai tmux-private",
    ),
    (
        "tmux-private / dry-run",
        "tmux-private",
        {"mode": {"value": "local-only"}, "root": {"value": "default"},
         "dry_run": {"value": "yes"}},
        "surfing-ai tmux-private --dry-run",
    ),
    (
        "max-procs / exact panes",
        "max-procs",
        {"run_or_grid": {"value": "run",
                         "inputs": {"run": '"cmd a" "cmd b"'}},
         "sizing": {"value": "exact"},
         "panes": {"value": "custom", "inputs": {"panes": "4"}},
         "mode": {"value": "local-only"}, "root": {"value": "default"}},
        'surfing-ai max-procs --panes 4 --run "cmd a" "cmd b"',
    ),
    (
        "max-procs / thread budget 70%",
        "max-procs",
        {"run_or_grid": {"value": "grid"},
         "sizing": {"value": "percent"},
         "thread_budget": {"value": "70"},
         "mode": {"value": "local-only"}, "root": {"value": "default"}},
        "surfing-ai max-procs --threads 70",
    ),
    (
        "max-procs / thread budget 100% (panes skipped by ask_if)",
        "max-procs",
        {"run_or_grid": {"value": "grid"},
         "sizing": {"value": "percent"},
         "thread_budget": {"value": "100"},
         "panes": {"value": "custom", "inputs": {"panes": "99"}},
         "mode": {"value": "local-only"}, "root": {"value": "default"}},
        "surfing-ai max-procs --threads 100",
    ),
    (
        "desktop / open + custom port",
        "desktop",
        {"open": {"value": "yes"},
         "host_port": {"value": "port", "inputs": {"port": "9000"}},
         "token": {"value": "random"}},
        "surfing-ai desktop --port 9000 --open",
    ),
    (
        "desktop / host+port+token",
        "desktop",
        {"open": {"value": "no"},
         "host_port": {"value": "both",
                       "inputs": {"host": "0.0.0.0", "port": "8080"}},
         "token": {"value": "custom", "inputs": {"token": "secret"}}},
        "surfing-ai desktop --host 0.0.0.0 --port 8080 --token secret",
    ),
    (
        "approvals / list",
        "approvals",
        {"action": {"value": "list"}},
        "surfing-ai approvals list",
    ),
    (
        "approvals / deny with reason (conditional)",
        "approvals",
        {"action": {"value": "deny"},
         "id": {"value": "custom", "inputs": {"id": "7"}},
         "reason": {"value": "custom", "inputs": {"reason": "risky"}}},
        "surfing-ai approvals deny 7 --reason risky",
    ),
    (
        "approvals / approve (reason skipped by ask_if)",
        "approvals",
        {"action": {"value": "approve"},
         "id": {"value": "custom", "inputs": {"id": "3"}},
         "reason": {"value": "custom", "inputs": {"reason": "ignored"}}},
        "surfing-ai approvals approve 3",
    ),
    (
        "backend-health / static",
        "backend-health",
        {},
        "surfing-ai backend-health",
    ),
]


def main() -> int:
    spec = load_spec()
    width = max(len(n) for n, *_ in SCENARIOS)
    passed = 0
    for name, key, answers, expected in SCENARIOS:
        got = resolve(spec, key, answers)
        ok = got == expected
        passed += ok
        mark = "PASS" if ok else "FAIL"
        print(f"[{mark}] {name:<{width}}  ->  {got}")
        if not ok:
            print(f"        expected: {expected}")
    total = len(SCENARIOS)
    print(f"\n{passed}/{total} scenarios passed")
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
